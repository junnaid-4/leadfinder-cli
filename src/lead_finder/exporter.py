"""Export businesses and their analysis data to structured files."""

from __future__ import annotations

import csv
import json
import logging
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LeadExportRow:
    """A flattened representation of a business and its latest checks."""

    business_id: int
    place_id: str
    business_name: str
    phone: str | None
    address: str | None
    rating: float | None
    review_count: int | None
    business_status: str | None
    original_website: str | None
    normalized_website: str | None
    final_website: str | None
    website_status: str | None
    http_status: int | None
    website_checked_at: str | None
    raw_score: int | None
    final_score: int | None
    priority: str | None
    scoring_version: str | None
    score_breakdown: str | None
    scored_at: str | None
    discovery_queries: str | None
    google_maps_url: str | None

    @classmethod
    def from_sqlite_row(cls, row: sqlite3.Row) -> LeadExportRow:
        """Create from a database row."""
        return cls(
            business_id=row["business_id"],
            place_id=row["place_id"],
            business_name=row["business_name"],
            phone=row["phone"],
            address=row["address"],
            rating=row["rating"],
            review_count=row["review_count"],
            business_status=row["business_status"],
            original_website=row["website_original_url"],
            normalized_website=row["website_normalized_url"],
            final_website=row["website_final_url"],
            website_status=row["website_status"],
            http_status=row["http_status"],
            website_checked_at=row["website_checked_at"],
            raw_score=row["raw_score"],
            final_score=row["final_score"],
            priority=row["priority"],
            scoring_version=row["scoring_version"],
            score_breakdown=row["score_breakdown_json"],
            scored_at=row["scored_at"],
            discovery_queries=row["discovery_queries"],
            google_maps_url=row["google_maps_url"],
        )


EXPORT_COLUMNS: tuple[str, ...] = (
    "business_id",
    "place_id",
    "business_name",
    "phone",
    "address",
    "rating",
    "review_count",
    "business_status",
    "original_website",
    "normalized_website",
    "final_website",
    "website_status",
    "http_status",
    "website_checked_at",
    "raw_score",
    "final_score",
    "priority",
    "scoring_version",
    "score_breakdown",
    "scored_at",
    "discovery_queries",
    "google_maps_url",
)


def sanitize_spreadsheet_text(value: str | None) -> str:
    """Prevent formula injection in CSV/XLSX by escaping dangerous characters."""
    if value is None:
        return ""

    text = str(value)
    stripped = text.lstrip()
    if stripped.startswith(("=", "+", "-", "@")):
        return f"'{text}"
    return text


def format_breakdown(json_str: str | None) -> str | None:
    """Format the breakdown JSON compactly for export, returning None if invalid."""
    if not json_str:
        return None
    try:
        data = json.loads(json_str)
        return json.dumps(data, separators=(",", ":"))
    except json.JSONDecodeError:
        return None


def convert_row_for_export(row: LeadExportRow) -> dict[str, Any]:
    """Convert LeadExportRow to a dictionary, applying formatting and sanitization."""
    # We maintain strict order using EXPORT_COLUMNS
    result = {}
    for col in EXPORT_COLUMNS:
        val = getattr(row, col)

        # Format the breakdown compactly
        if col == "score_breakdown":
            val = format_breakdown(val)

        # Apply formula injection protection to strings
        if isinstance(val, str):
            val = sanitize_spreadsheet_text(val)

        result[col] = val
    return result


def export_to_csv(rows: list[LeadExportRow], output_path: Path) -> None:
    """Export rows to a CSV file atomically."""
    # Write to temp file first
    fd, temp_path_str = tempfile.mkstemp(dir=output_path.parent, prefix="export_", suffix=".csv")
    temp_path = Path(temp_path_str)

    try:
        with open(fd, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=EXPORT_COLUMNS)
            writer.writeheader()
            for row in rows:
                dict_row = convert_row_for_export(row)
                writer.writerow(dict_row)

        # Atomic replace
        temp_path.replace(output_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def export_to_xlsx(rows: list[LeadExportRow], output_path: Path) -> None:
    """Export rows to an XLSX file atomically."""
    # Write to temp file first
    fd, temp_path_str = tempfile.mkstemp(dir=output_path.parent, prefix="export_", suffix=".xlsx")
    temp_path = Path(temp_path_str)

    import os

    os.close(fd)  # openpyxl needs to open it by filename, so close the fd

    try:
        wb = openpyxl.Workbook()
        default_sheet = wb.active
        if default_sheet is not None:
            wb.remove(default_sheet)

        ws: Worksheet = wb.create_sheet("Leads")

        # Write header
        ws.append(EXPORT_COLUMNS)

        # Bold header
        for cell in ws[1]:
            cell.font = Font(bold=True)

        # Freeze panes at A2
        ws.freeze_panes = "A2"

        # Write rows
        for row in rows:
            dict_row = convert_row_for_export(row)
            row_values = [
                dict_row[column] if dict_row[column] is not None else ""
                for column in EXPORT_COLUMNS
            ]
            ws.append(row_values)

        # Autofilter
        if len(rows) > 0:
            last_col = get_column_letter(len(EXPORT_COLUMNS))
            last_row = len(rows) + 1
            ws.auto_filter.ref = f"A1:{last_col}{last_row}"

        # Adjust column widths safely
        for col_idx in range(1, len(EXPORT_COLUMNS) + 1):
            col_letter = get_column_letter(col_idx)
            ws.column_dimensions[col_letter].width = 15

        wb.save(temp_path)
        wb.close()

        # Atomic replace
        temp_path.replace(output_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
