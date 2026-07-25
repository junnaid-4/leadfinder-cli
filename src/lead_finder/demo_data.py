"""Deterministic, network-free fictional portfolio demonstration."""

from __future__ import annotations

import csv
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import openpyxl

from lead_finder.config import AppConfig
from lead_finder.database import init_database
from lead_finder.pipeline import (
    ExportSummary,
    ScoringSummary,
    _promote_candidates,
    export_lead_files,
    score_businesses,
)
from lead_finder.website_checker import WebsiteStatus

DEMO_TIMESTAMP = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


class DemoSafetyError(ValueError):
    """The supplied configuration is not safe for demo-owned replacement."""


@dataclass(frozen=True)
class FictionalBusiness:
    place_id: str
    name: str
    category: str
    address: str
    phone: str | None
    website: str | None
    rating: float
    reviews: int
    business_status: str
    website_status: WebsiteStatus
    http_status: int | None = None
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class DemoSummary:
    businesses_inserted: int
    scoring: ScoringSummary
    exports: ExportSummary
    database_path: Path


FICTIONAL_BUSINESSES: tuple[FictionalBusiness, ...] = (
    FictionalBusiness(
        "demo-place-001",
        "Northstar Electrical Services",
        "electrician",
        "101 Aurora Way, Exampleton, Fictionland 00001",
        "+1 202-555-0101",
        None,
        4.9,
        240,
        "OPERATIONAL",
        WebsiteStatus.NO_WEBSITE,
    ),
    FictionalBusiness(
        "demo-place-002",
        "Cedar & Stone Plumbing",
        "plumber",
        "202 Cedar Court, Exampleton, Fictionland 00002",
        "+1 202-555-0102",
        "https://cedar-stone.example.com",
        4.6,
        125,
        "OPERATIONAL",
        WebsiteStatus.DNS_ERROR,
        error_type="NameResolutionError",
        error_message="Fictional reserved domain could not be resolved",
    ),
    FictionalBusiness(
        "demo-place-003",
        "BrightPath Dental Studio",
        "dentist",
        "303 Bright Avenue, Sample City, Fictionland 00003",
        "+1 202-555-0103",
        "https://brightpath.example.org",
        4.8,
        180,
        "OPERATIONAL",
        WebsiteStatus.WORKING,
        200,
    ),
    FictionalBusiness(
        "demo-place-004",
        "Blue Lantern Bakery",
        "bakery",
        "404 Lantern Lane, Sample City, Fictionland 00004",
        "+1 202-555-0104",
        "https://blue-lantern.example.net",
        4.2,
        58,
        "OPERATIONAL",
        WebsiteStatus.TIMEOUT,
        error_type="ConnectTimeout",
        error_message="Fictional connection timed out",
    ),
    FictionalBusiness(
        "demo-place-005",
        "Silver Oak Landscaping",
        "landscaper",
        "505 Silver Oak Road, Mocksville, Fictionland 00005",
        None,
        None,
        3.7,
        32,
        "OPERATIONAL",
        WebsiteStatus.NO_WEBSITE,
    ),
    FictionalBusiness(
        "demo-place-006",
        "Harborview Auto Care",
        "car_repair",
        "606 Harbor View, Mocksville, Fictionland 00006",
        "+1 202-555-0106",
        "https://harborview.example.com",
        4.1,
        110,
        "OPERATIONAL",
        WebsiteStatus.SSL_ERROR,
        error_type="ConnectError",
        error_message="Fictional certificate verification failed",
    ),
    FictionalBusiness(
        "demo-place-007",
        "Atlas Home Repairs",
        "general_contractor",
        "707 Atlas Street, Exampleton, Fictionland 00007",
        "+1 202-555-0107",
        "https://atlas.example.org",
        3.5,
        12,
        "OPERATIONAL",
        WebsiteStatus.UNREACHABLE,
        error_type="ConnectError",
        error_message="Fictional host unreachable",
    ),
    FictionalBusiness(
        "demo-place-008",
        "Willow & Finch Florists",
        "florist",
        "808 Willow Walk, Sample City, Fictionland 00008",
        None,
        "https://willow-finch.example.net",
        4.0,
        8,
        "OPERATIONAL",
        WebsiteStatus.HTTP_ERROR,
        404,
        error_type="HTTPStatusError",
        error_message="Fictional page returned HTTP 404",
    ),
    FictionalBusiness(
        "demo-place-009",
        "Summit Heating Solutions",
        "hvac_contractor",
        "909 Summit Rise, Mocksville, Fictionland 00009",
        "+1 202-555-0109",
        "https://summit.example.com",
        4.7,
        95,
        "OPERATIONAL",
        WebsiteStatus.HTTP_ERROR,
        503,
        error_type="HTTPStatusError",
        error_message="Fictional service returned HTTP 503",
    ),
    FictionalBusiness(
        "demo-place-010",
        "Maple Street Tutors",
        "tutoring_service",
        "110 Maple Street, Exampleton, Fictionland 00010",
        None,
        "not a valid url",
        3.2,
        6,
        "OPERATIONAL",
        WebsiteStatus.INVALID_URL,
        error_type="InvalidURL",
        error_message="Fictional URL is invalid",
    ),
    FictionalBusiness(
        "demo-place-011",
        "Emberline Café",
        "cafe",
        "111 Ember Lane, Sample City, Fictionland 00011",
        "+1 202-555-0111",
        "https://emberline.example.org",
        4.5,
        75,
        "CLOSED_TEMPORARILY",
        WebsiteStatus.WORKING,
        200,
    ),
    FictionalBusiness(
        "demo-place-012",
        "Clearview Cleaning Co.",
        "cleaning_service",
        "112 Clearview Close, Mocksville, Fictionland 00012",
        None,
        "https://clearview.invalid",
        2.8,
        2,
        "OPERATIONAL",
        WebsiteStatus.WORKING,
        200,
    ),
)


def demo_output_paths(config: AppConfig) -> tuple[Path, Path, Path]:
    """Return the exact database, CSV, and XLSX targets for a demo."""
    output_dir = config.export_directory().resolve()
    return config.database_path(), output_dir / "leads.csv", output_dir / "leads.xlsx"


def validate_demo_targets(config: AppConfig, project_root: Path) -> tuple[Path, Path, Path]:
    """Verify that only explicitly demo-owned project paths can be replaced."""
    root = project_root.resolve()
    database, csv_path, xlsx_path = demo_output_paths(config)
    output_dir = csv_path.parent
    if not config.demo.enabled:
        raise DemoSafetyError("Demo mode is not enabled in this configuration")
    if database.name != "demo_lead_finder.db":
        raise DemoSafetyError("Demo database must be named demo_lead_finder.db")
    if output_dir.name != "demo_output":
        raise DemoSafetyError("Demo export directory must be named demo_output")
    forbidden = {Path("/").resolve(), Path.home().resolve(), Path.cwd().resolve(), root}
    if output_dir in forbidden:
        raise DemoSafetyError("Demo export directory is a dangerous target")
    if not database.is_relative_to(root) or not output_dir.is_relative_to(root):
        raise DemoSafetyError("Demo targets must stay inside the project working tree")
    return database, csv_path, xlsx_path


def _stage_config(config: AppConfig, staging: Path) -> AppConfig:
    raw = config.model_dump()
    raw["database"]["path"] = str(staging / "data" / "demo_lead_finder.db")
    raw["export"]["output_directory"] = str(staging / "demo_output")
    raw["output"]["directory"] = str(staging / "demo_output")
    return AppConfig.model_validate(raw)


def _seed_demo(config: AppConfig) -> int:
    db = init_database(config.database_path())
    inserted = 0
    try:
        for item in FICTIONAL_BUSINESSES:
            data: dict[str, object] = {
                "primaryType": item.category,
                "types": [item.category],
                "formattedAddress": item.address,
                "nationalPhoneNumber": item.phone,
                "internationalPhoneNumber": item.phone,
                "googleMapsUri": f"https://maps.example.com/{item.place_id}",
                "websiteUri": item.website,
                "rating": item.rating,
                "userRatingCount": item.reviews,
                "businessStatus": item.business_status,
            }
            if db.insert_or_update_business(
                item.place_id, item.name, "fictional demo", config.search.location, data
            ):
                inserted += 1
            row = db.execute(
                "SELECT id FROM businesses WHERE place_id = ?", (item.place_id,)
            ).fetchone()
            if row is None:
                raise RuntimeError(f"Failed to insert fictional business {item.place_id}")
            normalized = item.website if item.website and "://" in item.website else None
            final_url = normalized if item.website_status is WebsiteStatus.WORKING else None
            db.save_website_check_result(
                int(row["id"]),
                item.website,
                normalized,
                final_url,
                item.website_status.value,
                item.http_status,
                0,
                120 if item.website_status is WebsiteStatus.WORKING else None,
                "text/html" if item.website_status is WebsiteStatus.WORKING else None,
                item.error_type,
                item.error_message,
            )
        fixed = DEMO_TIMESTAMP.strftime("%Y-%m-%d %H:%M:%S")
        db.execute("UPDATE businesses SET collected_at = ?, updated_at = ?", (fixed, fixed))
        db.execute("UPDATE website_checks SET checked_at = ?", (fixed,))
        db.commit()
    finally:
        db.close()
    return inserted


def _validate_staged_demo(database: Path, csv_path: Path, xlsx_path: Path) -> None:
    connection = sqlite3.connect(database)
    try:
        businesses = int(connection.execute("SELECT count(*) FROM businesses").fetchone()[0])
        scores = int(connection.execute("SELECT count(*) FROM lead_scores").fetchone()[0])
    finally:
        connection.close()
    expected = len(FICTIONAL_BUSINESSES)
    if businesses != expected or scores != expected:
        raise RuntimeError("Staged demo database failed count validation")
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != expected:
        raise RuntimeError("Staged demo CSV failed row validation")
    workbook = openpyxl.load_workbook(xlsx_path, read_only=True)
    try:
        worksheet = workbook.active
        if worksheet is None or worksheet.max_row != expected + 1:
            raise RuntimeError("Staged demo XLSX failed row validation")
    finally:
        workbook.close()


def run_demo(config: AppConfig, *, project_root: Path, overwrite: bool = False) -> DemoSummary:
    """Build, validate, and safely promote the fully fictional demo."""
    database, csv_path, xlsx_path = validate_demo_targets(config, project_root)
    existing = [path for path in (database, csv_path, xlsx_path) if path.exists()]
    if existing and not overwrite:
        raise FileExistsError("Demo data or output already exists")

    root = project_root.resolve()
    with tempfile.TemporaryDirectory(prefix=".leadfinder-demo-", dir=root) as temporary:
        staging = Path(temporary)
        staged_config = _stage_config(config, staging)
        inserted = _seed_demo(staged_config)
        scoring = score_businesses(staged_config, scored_at=DEMO_TIMESTAMP)
        exports = export_lead_files(staged_config, fmt="both")
        staged_database, staged_csv, staged_xlsx = demo_output_paths(staged_config)
        _validate_staged_demo(staged_database, staged_csv, staged_xlsx)

        database.parent.mkdir(parents=True, exist_ok=True)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        _promote_candidates(
            {
                database: staged_database,
                csv_path: staged_csv,
                xlsx_path: staged_xlsx,
            },
            staging,
        )
    final_exports = ExportSummary(exports.considered, exports.rows_exported, (csv_path, xlsx_path))
    return DemoSummary(inserted, scoring, final_exports, database)
