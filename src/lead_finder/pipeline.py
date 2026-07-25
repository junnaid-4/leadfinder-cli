"""Reusable services for LeadFinder pipeline stages."""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import httpx
import openpyxl

from lead_finder.config import AppConfig
from lead_finder.database import Database, init_database
from lead_finder.exporter import LeadExportRow, export_to_csv, export_to_xlsx
from lead_finder.lead_scoring import (
    SCORING_VERSION,
    BusinessScoringInput,
    LeadPriority,
    calculate_lead_score,
)
from lead_finder.places_client import (
    FIELD_MASK,
    PlacesAPIError,
    PlacesClient,
    build_places_cache_key,
)
from lead_finder.website_checker import WebsiteChecker, WebsiteCheckResult, WebsiteStatus

ExportFormat = Literal["csv", "xlsx", "both"]
PRIORITIES = tuple(LeadPriority)
logger = logging.getLogger(__name__)


class PipelineStageError(RuntimeError):
    """A required pipeline stage could not complete reliably."""


class WebsiteCheckStageError(PipelineStageError):
    """Website results could not be checked or persisted reliably."""


@dataclass(frozen=True)
class CollectionSummary:
    discovered: int
    duplicates: int
    api_requests: int
    cached_responses: int
    failed_queries: int


@dataclass(frozen=True)
class WebsiteCheckSummary:
    processed: int
    persisted: int
    failed: int
    counts: dict[WebsiteStatus, int]


@dataclass(frozen=True)
class ScoringSummary:
    considered: int
    scored: int
    skipped_existing: int
    unscorable: int
    failed: int
    priority_counts: dict[LeadPriority, int]
    average_score: float
    highest_score: int


@dataclass(frozen=True)
class ExportSummary:
    considered: int
    rows_exported: int
    output_paths: tuple[Path, ...]


@dataclass(frozen=True)
class ExportSelection:
    considered: int
    rows: list[LeadExportRow]


async def _collect_query(
    config: AppConfig,
    db: Database,
    client: PlacesClient,
    query_base: str,
    counters: dict[str, int],
    *,
    force_refresh: bool,
) -> int:
    query = f"{query_base} in {config.search.location}"
    page_token: str | None = None
    query_results = 0
    while (
        query_results < config.search.max_results_per_query
        and counters["discovered"] < config.search.max_total_results
        and counters["api_requests"] < config.search.max_api_requests
    ):
        cache_key = build_places_cache_key(
            query=query,
            location=config.search.location,
            field_mask=FIELD_MASK,
            page_token=page_token,
        )
        cached_data = None if force_refresh else db.get_cached_api_response(cache_key)
        if cached_data is not None:
            data = json.loads(cached_data)
            counters["cached"] += 1
        else:
            try:
                data = await client.search_text(query, page_token)
            except (PlacesAPIError, httpx.HTTPError) as exc:
                logger.error("Collection query failed for %s: %s", query, exc)
                counters["failed_queries"] += 1
                break
            counters["api_requests"] += 1
            expires = datetime.now(tz=UTC) + timedelta(days=config.cache.places_ttl_days)
            db.save_cached_api_response(
                cache_key,
                "searchText",
                json.dumps(data),
                expires.strftime("%Y-%m-%d %H:%M:%S"),
            )

        places = data.get("places", [])
        if not isinstance(places, list) or not places:
            break
        for place in places:
            if (
                counters["discovered"] >= config.search.max_total_results
                or query_results >= config.search.max_results_per_query
            ):
                break
            if not isinstance(place, dict):
                continue
            place_id = place.get("id")
            if not isinstance(place_id, str) or not place_id:
                continue
            display_name = place.get("displayName")
            name = (
                display_name.get("text", "Unknown") if isinstance(display_name, dict) else "Unknown"
            )
            if db.insert_or_update_business(
                place_id, str(name), query_base, config.search.location, place
            ):
                counters["discovered"] += 1
                query_results += 1
            else:
                counters["duplicates"] += 1
        next_token = data.get("nextPageToken")
        page_token = next_token if isinstance(next_token, str) else None
        if page_token is None:
            break
    return query_results


async def _collect_async(
    config: AppConfig,
    db: Database,
    api_key: str,
    *,
    force_refresh: bool,
) -> CollectionSummary:
    counters = {
        "discovered": 0,
        "duplicates": 0,
        "api_requests": 0,
        "cached": 0,
        "failed_queries": 0,
    }
    run_id = db.create_search_run(config.project.name, config.search.location, dry_run=False)
    client: PlacesClient | None = None
    try:
        client = PlacesClient(api_key)
        for query_base in config.search.queries:
            if (
                counters["discovered"] >= config.search.max_total_results
                or counters["api_requests"] >= config.search.max_api_requests
            ):
                break
            query_results = await _collect_query(
                config,
                db,
                client,
                query_base,
                counters,
                force_refresh=force_refresh,
            )
            db.add_search_query_log(run_id, query_base, config.search.location, query_results)
        db.update_search_run(
            run_id,
            "COMPLETED",
            counters["discovered"],
            counters["duplicates"],
            counters["api_requests"],
        )
    except Exception:
        try:
            db.update_search_run(
                run_id,
                "FAILED",
                counters["discovered"],
                counters["duplicates"],
                counters["api_requests"],
            )
        except Exception:
            logger.exception("Failed to finalize search run %s as FAILED", run_id)
        raise
    finally:
        if client is not None:
            await client.close()

    return CollectionSummary(
        counters["discovered"],
        counters["duplicates"],
        counters["api_requests"],
        counters["cached"],
        counters["failed_queries"],
    )


def collect_businesses(
    config: AppConfig, api_key: str, *, force_refresh: bool = False
) -> CollectionSummary:
    """Collect and persist businesses through Google Places."""
    db = init_database(config.database_path())
    try:
        return asyncio.run(_collect_async(config, db, api_key, force_refresh=force_refresh))
    finally:
        db.close()


async def _check_websites_async(
    config: AppConfig, db: Database, *, force_refresh: bool
) -> WebsiteCheckSummary:
    businesses = db.get_businesses_needing_checks(force_refresh=force_refresh)
    counts = {status: 0 for status in WebsiteStatus}
    if not businesses:
        return WebsiteCheckSummary(0, 0, 0, counts)
    checker = WebsiteChecker(config.website_check)
    failures: list[Exception] = []
    persisted = 0

    async def check_one(row: sqlite3.Row) -> None:
        nonlocal persisted
        try:
            result = await checker.check_website(row["id"], row["website_url"])
        except Exception as exc:
            failures.append(exc)
            logger.exception("Website checker failed for business %s", row["id"])
            return

        try:
            db.save_website_check_result(
                result.business_id,
                result.original_url,
                result.normalized_url,
                result.final_url,
                result.status.value,
                result.http_status,
                result.redirect_count,
                result.response_time_ms,
                result.content_type,
                result.error_type,
                result.error_message,
            )
        except Exception as exc:
            failures.append(exc)
            logger.exception("Could not persist website result for business %s", row["id"])
            return
        counts[result.status] += 1
        persisted += 1

    try:
        await asyncio.gather(*(check_one(row) for row in businesses))
    finally:
        await checker.close()
    if failures:
        raise WebsiteCheckStageError(
            f"{len(failures)} of {len(businesses)} website results failed"
        ) from failures[0]
    return WebsiteCheckSummary(len(businesses), persisted, 0, counts)


def check_business_websites(
    config: AppConfig, *, force_refresh: bool = False
) -> WebsiteCheckSummary:
    """Check websites and persist classifications."""
    if not config.website_check.enabled:
        return WebsiteCheckSummary(0, 0, 0, {status: 0 for status in WebsiteStatus})
    db = init_database(config.database_path())
    try:
        return asyncio.run(_check_websites_async(config, db, force_refresh=force_refresh))
    finally:
        db.close()


def _website_result(row: sqlite3.Row) -> WebsiteCheckResult | None:
    status_value = row["website_check_status"]
    if not status_value:
        return None
    try:
        status = WebsiteStatus(status_value)
    except ValueError:
        status = WebsiteStatus.UNKNOWN_ERROR
    return WebsiteCheckResult(
        business_id=row["business_id"],
        original_url=row["website_original_url"],
        normalized_url=row["website_normalized_url"],
        final_url=row["website_final_url"],
        status=status,
        http_status=row["website_http_status"],
        redirect_count=row["website_redirect_count"] or 0,
        response_time_ms=row["website_response_time_ms"],
        content_type=row["website_content_type"],
        error_type=row["website_error_type"],
        error_message=row["website_error_message"],
    )


def score_businesses(
    config: AppConfig,
    *,
    force_refresh: bool = False,
    scored_at: datetime | None = None,
) -> ScoringSummary:
    """Calculate and persist scores while preserving score history."""
    db = init_database(config.database_path())
    try:
        all_rows = db.get_businesses_to_score(force_refresh=True)
        scored_ids = {
            int(row[0])
            for row in db.execute("SELECT DISTINCT business_id FROM lead_scores").fetchall()
        }
        rows = (
            all_rows
            if force_refresh
            else [row for row in all_rows if int(row["business_id"]) not in scored_ids]
        )
        priority_counts = {priority: 0 for priority in PRIORITIES}
        scored = unscorable = failed = total_score = 0
        highest = 0
        for row in rows:
            place_id = row["place_id"]
            if not isinstance(place_id, str) or not place_id.strip():
                unscorable += 1
                continue
            try:
                business = BusinessScoringInput(
                    business_id=row["business_id"],
                    place_id=place_id,
                    name=row["business_name"],
                    phone=row["phone"],
                    address=row["formatted_address"],
                    rating=row["rating"],
                    review_count=row["user_rating_count"],
                    business_status=row["business_status"],
                )
                result = calculate_lead_score(business, _website_result(row), config.lead_scoring)
                components = [
                    {"rule": c.rule, "points": c.points, "explanation": c.explanation}
                    for c in result.components
                ]
                timestamp = scored_at or result.scored_at
                db.save_lead_score(
                    row["business_id"],
                    result.raw_score,
                    result.final_score,
                    result.priority.value,
                    json.dumps(components),
                    SCORING_VERSION,
                    timestamp.isoformat(),
                )
                scored += 1
                priority_counts[result.priority] += 1
                total_score += result.final_score
                highest = max(highest, result.final_score)
            except Exception:
                failed += 1
                logger.exception("Scoring failed for business %s", row["business_id"])
        return ScoringSummary(
            considered=len(all_rows),
            scored=scored,
            skipped_existing=len(all_rows) - len(rows),
            unscorable=unscorable,
            failed=failed,
            priority_counts=priority_counts,
            average_score=total_score / scored if scored else 0.0,
            highest_score=highest,
        )
    finally:
        db.close()


def prepare_export_rows(
    config: AppConfig,
    *,
    minimum_score: int | None = None,
    priorities: list[str] | None = None,
    include_unscored: bool | None = None,
    limit: int | None = None,
) -> ExportSelection:
    """Select, filter, and sort export rows using one canonical implementation."""
    resolved_minimum = config.export.minimum_score if minimum_score is None else minimum_score
    resolved_priorities = config.export.priorities if priorities is None else priorities
    resolved_unscored = (
        config.export.include_unscored if include_unscored is None else include_unscored
    )
    db = init_database(config.database_path())
    try:
        considered = db.count_candidate_businesses()
        db_rows = db.get_leads_for_export()
    finally:
        db.close()

    rows: list[LeadExportRow] = []
    for db_row in db_rows:
        row = LeadExportRow.from_sqlite_row(db_row)
        if row.final_score is not None:
            if row.final_score < resolved_minimum:
                continue
            if resolved_priorities and row.priority not in resolved_priorities:
                continue
        else:
            if not resolved_unscored:
                continue
            if resolved_priorities and "unscored" not in resolved_priorities:
                continue
            if (
                row.business_status in ("CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY")
                or not row.place_id
            ):
                continue
        rows.append(row)

    priority_order = {
        "very_high": 0,
        "high": 1,
        "medium": 2,
        "low": 3,
        "very_low": 4,
        None: 5,
    }
    rows.sort(
        key=lambda row: (
            priority_order.get(row.priority, 5),
            -(row.final_score if row.final_score is not None else -1),
            -(row.review_count if row.review_count is not None else -1),
            row.business_name.lower(),
            row.business_id,
        )
    )
    if limit is not None and limit > 0:
        rows = rows[:limit]
    return ExportSelection(considered, rows)


def _validate_csv(path: Path) -> None:
    with path.open(encoding="utf-8", newline="") as handle:
        next(csv.reader(handle))


def _validate_xlsx(path: Path) -> None:
    workbook = openpyxl.load_workbook(path, read_only=True)
    workbook.close()


def _promote_candidates(candidates: dict[Path, Path], backup_dir: Path) -> None:
    backups: dict[Path, Path] = {}
    promoted: list[Path] = []
    try:
        for final in candidates:
            if final.exists():
                backup = backup_dir / f"{len(backups)}-{final.name}"
                final.replace(backup)
                backups[final] = backup
        for final, candidate in candidates.items():
            candidate.replace(final)
            promoted.append(final)
    except Exception:
        for final in promoted:
            final.unlink(missing_ok=True)
        for final, backup in backups.items():
            if backup.exists():
                backup.replace(final)
        raise


def export_lead_files(
    config: AppConfig,
    *,
    fmt: ExportFormat,
    output_dir: Path | None = None,
    overwrite: bool = False,
) -> ExportSummary:
    """Export the latest eligible leads to one or both supported formats."""
    directory = (output_dir or config.export_directory()).resolve()
    paths: list[Path] = []
    if fmt in ("csv", "both"):
        paths.append(directory / "leads.csv")
    if fmt in ("xlsx", "both"):
        paths.append(directory / "leads.xlsx")
    existing = [path for path in paths if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(existing[0])
    selection = prepare_export_rows(config)
    if not selection.rows:
        return ExportSummary(selection.considered, 0, ())
    directory.mkdir(parents=True, exist_ok=True)

    if fmt == "csv":
        export_to_csv(selection.rows, paths[0])
    elif fmt == "xlsx":
        export_to_xlsx(selection.rows, paths[0])
    else:
        with tempfile.TemporaryDirectory(prefix=".leadfinder-export-", dir=directory) as temporary:
            staging = Path(temporary)
            csv_candidate = staging / "leads.csv"
            xlsx_candidate = staging / "leads.xlsx"
            export_to_csv(selection.rows, csv_candidate)
            export_to_xlsx(selection.rows, xlsx_candidate)
            _validate_csv(csv_candidate)
            _validate_xlsx(xlsx_candidate)
            _promote_candidates(
                {
                    directory / "leads.csv": csv_candidate,
                    directory / "leads.xlsx": xlsx_candidate,
                },
                staging,
            )
    return ExportSummary(selection.considered, len(selection.rows), tuple(paths))
