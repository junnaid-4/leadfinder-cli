"""Tests for SQLite database initialization and merging."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from lead_finder.database import SCHEMA_VERSION, Database, init_database

EXPECTED_TABLES = {
    "schema_version",
    "search_runs",
    "search_queries",
    "businesses",
    "website_checks",
    "cached_api_responses",
}


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_lead_finder.db"


@pytest.fixture
def db(db_path: Path) -> Database:
    database = init_database(db_path)
    yield database
    database.close()


def test_init_database_creates_file_and_tables(db_path: Path, db: Database) -> None:
    assert db_path.exists()
    assert set(db.table_names()) == EXPECTED_TABLES


def test_schema_version_is_recorded(db: Database) -> None:
    connection = db.connect()
    version = Database.get_schema_version(connection)
    assert version == SCHEMA_VERSION


def test_initialize_is_idempotent(db_path: Path, db: Database) -> None:
    second = init_database(db_path)
    assert set(second.table_names()) == EXPECTED_TABLES
    second.close()


def test_businesses_place_id_is_unique(db: Database) -> None:
    """4. Place-ID deduplication (SQL constraints)."""
    db.execute(
        """
        INSERT INTO businesses (place_id, business_name)
        VALUES (?, ?)
        """,
        ("ChIJtest123", "Test Electricians"),
    )
    db.commit()

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """
            INSERT INTO businesses (place_id, business_name)
            VALUES (?, ?)
            """,
            ("ChIJtest123", "Duplicate Business"),
        )


def test_foreign_keys_enabled(db: Database) -> None:
    connection = db.connect()
    row = connection.execute("PRAGMA foreign_keys").fetchone()
    assert row is not None
    assert int(row[0]) == 1


def test_insert_or_update_business_merging(db: Database) -> None:
    """4. Deduplication, 5. Merging, 6. Empty-string vs null, 31. Missing fields."""

    # Insert initially with missing/null fields
    is_new = db.insert_or_update_business(
        place_id="P1",
        name="Missing Fields Plumbers",
        query="plumbers",
        location="Manchester",
        data={
            "primaryType": "plumber",
            # other fields missing
        },
    )
    assert is_new is True

    # Read back
    row = db.execute("SELECT * FROM businesses WHERE place_id = 'P1'").fetchone()
    assert row["business_name"] == "Missing Fields Plumbers"
    assert row["website_url"] is None
    assert row["address"] is None

    # Update with some good fields, but empty strings for others
    is_new_again = db.insert_or_update_business(
        place_id="P1",
        name="Good Plumbers",
        query="plumbers",
        location="Manchester",
        data={
            "primaryType": "plumber",
            "websiteUri": "https://example.com",
            # Empty string should not overwrite anything, but it's null currently anyway
            "formattedAddress": "",
        },
    )
    assert is_new_again is False

    row = db.execute("SELECT * FROM businesses WHERE place_id = 'P1'").fetchone()
    assert row["website_url"] == "https://example.com"
    assert row["business_name"] == "Good Plumbers"  # Overwritten
    assert row["address"] is None  # Remains null since we sent ""

    # Update with empty strings where we already have good data
    db.insert_or_update_business(
        place_id="P1",
        name="",  # Empty string, should NOT overwrite
        query="plumbers",
        location="Manchester",
        data={
            "websiteUri": "",  # Empty string, should NOT overwrite
        },
    )

    row = db.execute("SELECT * FROM businesses WHERE place_id = 'P1'").fetchone()
    assert row["website_url"] == "https://example.com"  # Preserved!
    assert row["business_name"] == "Good Plumbers"  # Preserved!


def test_all_discovery_queries_preserved(db: Database) -> None:
    """33. All discovery queries preserved for the business."""
    # We log discovery queries in `search_queries`, which links to `search_runs`.
    # Let's verify we can record multiple queries.
    run1 = db.create_search_run("test", "Manchester", False)
    db.add_search_query_log(run1, "plumbers", "Manchester", 10)

    run2 = db.create_search_run("test", "Manchester", False)
    db.add_search_query_log(run2, "electricians", "Manchester", 5)

    # They are preserved in `search_queries`
    queries = db.execute("SELECT query_text FROM search_queries").fetchall()
    assert len(queries) == 2
    assert queries[0]["query_text"] == "plumbers"
    assert queries[1]["query_text"] == "electricians"
