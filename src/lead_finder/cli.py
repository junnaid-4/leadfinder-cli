"""Typer CLI entry point."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console

from lead_finder.config import AppConfig, EnvSettings, load_config
from lead_finder.database import init_database
from lead_finder.lead_scoring import (
    SCORING_VERSION,
    BusinessScoringInput,
    calculate_lead_score,
)
from lead_finder.logging_config import setup_logging
from lead_finder.models import SearchRunStatus
from lead_finder.places_client import (
    FIELD_MASK,
    PlacesClient,
    build_places_cache_key,
)
from lead_finder.website_checker import WebsiteCheckResult, WebsiteStatus

app = typer.Typer(
    name="lead-finder",
    help="Local Business Website Lead Finder — internal lead-generation tool.",
    no_args_is_help=True,
)
console = Console()


def _resolve_config(config: Path) -> AppConfig:
    return load_config(config)


def _not_implemented(command: str) -> None:
    console.print(
        f"[yellow]{command} is not implemented yet (Stage 2+).[/yellow]",
        highlight=False,
    )
    raise typer.Exit(code=0)


@app.command("validate-config")
def validate_config(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to YAML configuration file."),
    ] = Path("config.yaml"),
) -> None:
    """Validate configuration file and environment settings."""
    app_config = _resolve_config(config)
    setup_logging(app_config)
    console.print("[green]Configuration is valid.[/green]")
    console.print(f"Project: {app_config.project.name}")
    console.print(f"Location: {app_config.search.location}")
    console.print(f"Queries: {len(app_config.search.queries)}")


@app.command()
def estimate(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to YAML configuration file."),
    ] = Path("config.yaml"),
) -> None:
    """Estimate API usage and run scope (placeholder)."""
    _resolve_config(config)
    _not_implemented("estimate")


@app.command()
def collect(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to YAML configuration file."),
    ] = Path("config.yaml"),
    force_refresh: Annotated[
        bool,
        typer.Option("--force-refresh", help="Ignore cached Places responses."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Estimate and validate without API calls."),
    ] = False,
) -> None:
    """Collect businesses from Google Places."""
    app_config = _resolve_config(config)
    setup_logging(app_config)

    try:
        env = EnvSettings()
        api_key = env.require_api_key()
        has_api_key = True
    except Exception:
        has_api_key = False
        api_key = ""

    if dry_run:
        console.print("[yellow]DRY RUN MODE ENABLED[/yellow]")
        console.print("Configuration valid: Yes")
        console.print(f"API key available: {'Yes' if has_api_key else 'No'}")
        console.print(f"Queries: {app_config.search.queries}")
        console.print(f"Location: {app_config.search.location}")
        console.print(f"Max Results Per Query: {app_config.search.max_results_per_query}")
        console.print(f"Max Total Results: {app_config.search.max_total_results}")
        console.print(f"Max API Requests: {app_config.search.max_api_requests}")
        console.print("No network requests will be made.")
        return

    if not has_api_key:
        console.print("[red]API key is missing but required for collection.[/red]")
        raise typer.Exit(code=1)

    db = init_database(app_config.database_path())
    run_id = db.create_search_run(
        app_config.project.name, app_config.search.location, dry_run=False
    )

    total_discovered = 0
    total_duplicates = 0
    api_requests = 0
    cached_used = 0
    failed_queries = 0

    location = app_config.search.location
    client = PlacesClient(api_key)

    async def _run_collection() -> None:
        nonlocal total_discovered, total_duplicates, api_requests
        nonlocal cached_used, failed_queries

        for query_base in app_config.search.queries:
            if total_discovered >= app_config.search.max_total_results:
                break
            if api_requests >= app_config.search.max_api_requests:
                break

            query = f"{query_base} in {location}"
            page_token = None
            query_results = 0

            while True:
                if query_results >= app_config.search.max_results_per_query:
                    break
                if total_discovered >= app_config.search.max_total_results:
                    break
                if api_requests >= app_config.search.max_api_requests:
                    break

                cache_key = build_places_cache_key(
                    query=query,
                    location=location,
                    field_mask=FIELD_MASK,
                    page_token=page_token,
                )
                cached_data = None

                if not force_refresh:
                    cached_data = db.get_cached_api_response(cache_key)

                if cached_data:
                    data = json.loads(cached_data)
                    cached_used += 1
                else:
                    try:
                        data = await client.search_text(query, page_token)
                        api_requests += 1

                        expires_dt = datetime.now(tz=UTC) + timedelta(
                            days=app_config.cache.places_ttl_days
                        )
                        expires = expires_dt.strftime("%Y-%m-%d %H:%M:%S")
                        db.save_cached_api_response(
                            cache_key, "searchText", json.dumps(data), expires
                        )
                    except Exception as e:
                        console.print(f"[red]Error fetching query '{query}': {e}[/red]")
                        failed_queries += 1
                        break

                places = data.get("places", [])
                if not places:
                    break

                for place in places:
                    if (
                        total_discovered >= app_config.search.max_total_results
                        or query_results >= app_config.search.max_results_per_query
                    ):
                        break

                    place_id = place.get("id")
                    if not place_id:
                        continue

                    name = place.get("displayName", {}).get("text", "Unknown")
                    is_new = db.insert_or_update_business(
                        place_id, name, query_base, location, place
                    )
                    if is_new:
                        total_discovered += 1
                        query_results += 1
                    else:
                        total_duplicates += 1

                page_token = data.get("nextPageToken")
                if not page_token:
                    break

            db.add_search_query_log(run_id, query_base, location, query_results)

    try:
        asyncio.run(_run_collection())
        status = SearchRunStatus.COMPLETED
    except Exception as e:
        console.print(f"[red]Fatal error during collection: {e}[/red]")
        status = SearchRunStatus.FAILED

    db.update_search_run(run_id, status.value, total_discovered, total_duplicates, api_requests)

    console.print("\n[bold]Collection Summary[/bold]")
    console.print(f"Queries processed: {len(app_config.search.queries)}")
    console.print(f"Live API requests used: {api_requests}")
    console.print(f"Cached responses used: {cached_used}")
    console.print(f"Unique businesses saved: {total_discovered}")
    console.print(f"Duplicates merged: {total_duplicates}")
    console.print(f"Failed queries: {failed_queries}")
    console.print(f"Database path: {app_config.database_path()}")


@app.command("check-websites")
def check_websites(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to YAML configuration file."),
    ] = Path("config.yaml"),
    force_refresh: Annotated[
        bool,
        typer.Option("--force-refresh", help="Re-check websites ignoring cache."),
    ] = False,
) -> None:
    """Check business websites for availability and classify them."""
    app_config = _resolve_config(config)
    setup_logging(app_config)

    if not app_config.website_check.enabled:
        console.print("[yellow]Website checking is disabled in configuration.[/yellow]")
        return

    db = init_database(app_config.database_path())
    businesses = db.get_businesses_needing_checks(force_refresh=force_refresh)

    if not businesses:
        console.print("No businesses need website checking.")
        return

    console.print(f"Checking {len(businesses)} websites...")

    from lead_finder.website_checker import WebsiteChecker, WebsiteStatus

    checker = WebsiteChecker(app_config.website_check)
    counts = {status: 0 for status in WebsiteStatus}

    async def _process_all() -> None:
        async def _check_and_save(business_row: Any) -> None:
            b_id = business_row["id"]
            name = business_row["business_name"]
            url = business_row["website_url"]
            try:
                result = await checker.check_website(b_id, url)
                db.save_website_check_result(
                    business_id=result.business_id,
                    original_url=result.original_url,
                    normalized_url=result.normalized_url,
                    final_url=result.final_url,
                    status=result.status.value,
                    http_status=result.http_status,
                    redirect_count=result.redirect_count,
                    response_time_ms=result.response_time_ms,
                    content_type=result.content_type,
                    error_type=result.error_type,
                    error_message=result.error_message,
                )
                counts[result.status] += 1
            except Exception as e:
                console.print(f"[red]Error checking {name}: {e}[/red]")
                counts[WebsiteStatus.UNKNOWN_ERROR] += 1

        tasks = [_check_and_save(row) for row in businesses]
        await asyncio.gather(*tasks)
        await checker.close()

    try:
        asyncio.run(_process_all())
    except KeyboardInterrupt:
        console.print("\n[yellow]Website checking interrupted.[/yellow]")

    summary_labels = {
        WebsiteStatus.NO_WEBSITE: "No website",
        WebsiteStatus.WORKING: "Working",
        WebsiteStatus.UNREACHABLE: "Unreachable",
        WebsiteStatus.TIMEOUT: "Timeout",
        WebsiteStatus.DNS_ERROR: "DNS errors",
        WebsiteStatus.SSL_ERROR: "SSL errors",
        WebsiteStatus.HTTP_ERROR: "HTTP errors",
        WebsiteStatus.BLOCKED: "Blocked",
        WebsiteStatus.INVALID_URL: "Invalid URLs",
        WebsiteStatus.REDIRECT_LOOP: "Redirect loop",
        WebsiteStatus.UNKNOWN_ERROR: "Other failures",
    }

    console.print("\n[bold]Website Check Summary[/bold]")
    console.print(f"Businesses processed: {len(businesses)}")
    for status, label in summary_labels.items():
        count = counts[status]
        if count > 0:
            console.print(f"{label}: {count}")

    console.print(f"Database path: {app_config.database_path()}")


@app.command()
def score_leads(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to YAML configuration file."),
    ] = Path("config.yaml"),
    force_refresh: Annotated[
        bool,
        typer.Option("--force-refresh", help="Score already scored businesses again."),
    ] = False,
) -> None:
    """Calculate and assign lead scores to businesses."""
    app_config = _resolve_config(config)
    setup_logging(app_config)

    db = init_database(app_config.database_path())
    try:
        businesses = db.get_businesses_to_score(force_refresh=force_refresh)
    finally:
        db.close()

    if not businesses:
        console.print("No businesses available to score.", style="yellow")
        raise typer.Exit()

    considered = len(businesses)
    scored = 0
    skipped_existing = 0
    unscorable = 0
    failed = 0

    priority_counts = {
        "very_high": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "very_low": 0,
    }

    db = init_database(app_config.database_path())

    total_score = 0
    highest_score = -1

    try:
        all_businesses_cursor = db.execute("SELECT id, place_id FROM businesses")
        all_businesses = all_businesses_cursor.fetchall()

        scored_ids_cursor = db.execute("SELECT DISTINCT business_id FROM lead_scores")
        scored_ids = {row[0] for row in scored_ids_cursor.fetchall()}
    except Exception as e:
        console.print(f"Error initializing data: {e}", style="red")
        db.close()
        raise typer.Exit(1) from e

    considered = len(all_businesses)

    if force_refresh:
        to_process = all_businesses
        skipped_existing = 0
    else:
        to_process = [b for b in all_businesses if b["id"] not in scored_ids]
        skipped_existing = considered - len(to_process)

    if not to_process:
        console.print("No businesses available to score.", style="yellow")
        db.close()
        raise typer.Exit()

    try:
        full_rows = db.get_businesses_to_score(force_refresh=True)
    except Exception as e:
        console.print(f"Error fetching data: {e}", style="red")
        db.close()
        raise typer.Exit(1) from e

    process_ids = {b["id"] for b in to_process}

    for row in full_rows:
        b_id = row["business_id"]
        if b_id not in process_ids:
            continue

        place_id = row["place_id"]
        if not place_id or not place_id.strip():
            unscorable += 1
            logging.getLogger(__name__).warning(
                f"Business {b_id} is unscorable due to missing place_id"
            )
            continue

        try:
            b_input = BusinessScoringInput(
                business_id=b_id,
                place_id=place_id,
                name=row["business_name"],
                phone=row["phone"],
                address=row["formatted_address"],
                rating=row["rating"],
                review_count=row["user_rating_count"],
                business_status=row["business_status"],
            )

            ws_status_str = row["website_check_status"]
            if ws_status_str:
                try:
                    ws_status = WebsiteStatus(ws_status_str)
                except ValueError:
                    ws_status = WebsiteStatus.UNKNOWN_ERROR

                wc_input = WebsiteCheckResult(
                    business_id=b_id,
                    original_url=row["website_original_url"],
                    normalized_url=row["website_normalized_url"],
                    final_url=row["website_final_url"],
                    status=ws_status,
                    http_status=row["website_http_status"],
                    redirect_count=row["website_redirect_count"] or 0,
                    response_time_ms=row["website_response_time_ms"],
                    content_type=row["website_content_type"],
                    error_type=row["website_error_type"],
                    error_message=row["website_error_message"],
                )
            else:
                wc_input = None

            result = calculate_lead_score(b_input, wc_input, app_config.lead_scoring)

            components_list = [
                {"rule": c.rule, "points": c.points, "explanation": c.explanation}
                for c in result.components
            ]

            db.save_lead_score(
                business_id=b_id,
                raw_score=result.raw_score,
                final_score=result.final_score,
                priority=result.priority.value,
                score_breakdown_json=json.dumps(components_list),
                scoring_version=SCORING_VERSION,
                scored_at=result.scored_at.isoformat(),
            )

            scored += 1
            priority_counts[result.priority.value] += 1
            total_score += result.final_score
            if result.final_score > highest_score:
                highest_score = result.final_score

        except Exception as e:
            failed += 1
            logging.getLogger(__name__).exception(f"Failed to score business {b_id}: {e}")

    db.close()

    avg_score = (total_score / scored) if scored > 0 else 0

    console.print("\n[bold]Lead Scoring Summary[/bold]")
    console.print(f"Businesses considered: {considered}")
    console.print(f"Businesses scored: {scored}")
    console.print(f"Skipped existing scores: {skipped_existing}")
    console.print(f"Unscorable businesses: {unscorable}")
    console.print(f"Failed records: {failed}")
    console.print("")
    console.print(f"Very high priority: {priority_counts['very_high']}")
    console.print(f"High priority: {priority_counts['high']}")
    console.print(f"Medium priority: {priority_counts['medium']}")
    console.print(f"Low priority: {priority_counts['low']}")
    console.print(f"Very low priority: {priority_counts['very_low']}")
    console.print("")
    console.print(f"Average score: {avg_score:.1f}")
    console.print(f"Highest score: {max(highest_score, 0)}")
    console.print(f"Database path: {app_config.database_path()}")
    console.print(f"Scoring version: {SCORING_VERSION}")


@app.command()
def explain_score(
    business_id: int,
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to YAML configuration file."),
    ] = Path("config.yaml"),
) -> None:
    """Explain the latest lead score for a business."""
    app_config = _resolve_config(config)
    setup_logging(app_config)

    db = init_database(app_config.database_path())

    try:
        # Get business name
        b_cursor = db.execute("SELECT business_name FROM businesses WHERE id = ?", (business_id,))
        b_row = b_cursor.fetchone()
        if not b_row:
            console.print(f"Business ID {business_id} not found.", style="red")
            raise typer.Exit(1)

        b_name = b_row["business_name"]

        # Get latest score
        s_cursor = db.execute(
            """
            SELECT final_score, priority, scoring_version, score_breakdown_json
            FROM lead_scores
            WHERE business_id = ?
            ORDER BY scored_at DESC, id DESC
            LIMIT 1
            """,
            (business_id,),
        )
        s_row = s_cursor.fetchone()
        if not s_row:
            console.print(
                f"No score found for business '{b_name}' (ID {business_id}).", style="yellow"
            )
            raise typer.Exit()

        console.print(f"[bold]Business:[/bold] {b_name}")
        console.print(f"[bold]Latest score:[/bold] {s_row['final_score']}")
        console.print(f"[bold]Priority:[/bold] {s_row['priority']}")
        console.print(f"[bold]Scoring version:[/bold] {s_row['scoring_version']}")
        console.print("\n[bold]Score Breakdown:[/bold]")

        components = json.loads(s_row["score_breakdown_json"])
        for comp in components:
            rule = comp.get("rule", "unknown")
            points = comp.get("points", 0)
            explanation = comp.get("explanation", "")
            sign = "+" if points >= 0 else ""
            console.print(f"- {explanation} ({rule}): {sign}{points}")

    finally:
        db.close()


@app.command()
def export(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to YAML configuration file."),
    ] = Path("config.yaml"),
) -> None:
    """Export results to CSV files (placeholder)."""
    _resolve_config(config)
    _not_implemented("export")


@app.command()
def run(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to YAML configuration file."),
    ] = Path("config.yaml"),
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Estimate and validate without API calls."),
    ] = False,
    force_refresh: Annotated[
        bool,
        typer.Option("--force-refresh", help="Ignore cached data."),
    ] = False,
) -> None:
    """Run the full pipeline (placeholder)."""
    _resolve_config(config)
    if dry_run:
        console.print("Dry run mode enabled.", highlight=False)
    if force_refresh:
        console.print("Force refresh requested.", highlight=False)
    _not_implemented("run")


def main() -> None:
    """Console script entry point."""
    app()


if __name__ == "__main__":
    main()
