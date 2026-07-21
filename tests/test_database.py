"""Tests for SQLite database initialization."""

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


def test_init_database_creates_file_and_tables(db_path: Path) -> None:
    database = init_database(db_path)

    assert db_path.exists()
    assert set(database.table_names()) == EXPECTED_TABLES

    database.close()


def test_schema_version_is_recorded(db_path: Path) -> None:
    database = init_database(db_path)
    connection = database.connect()

    version = Database.get_schema_version(connection)
    assert version == SCHEMA_VERSION

    database.close()


def test_initialize_is_idempotent(db_path: Path) -> None:
    first = init_database(db_path)
    first.close()

    second = init_database(db_path)
    assert set(second.table_names()) == EXPECTED_TABLES
    second.close()


def test_businesses_place_id_is_unique(db_path: Path) -> None:
    database = init_database(db_path)
    database.execute(
        """
        INSERT INTO businesses (place_id, business_name)
        VALUES (?, ?)
        """,
        ("ChIJtest123", "Test Electricians"),
    )
    database.commit()

    with pytest.raises(sqlite3.IntegrityError):
        database.execute(
            """
            INSERT INTO businesses (place_id, business_name)
            VALUES (?, ?)
            """,
            ("ChIJtest123", "Duplicate Business"),
        )

    database.close()


def test_foreign_keys_enabled(db_path: Path) -> None:
    database = init_database(db_path)
    connection = database.connect()
    row = connection.execute("PRAGMA foreign_keys").fetchone()

    assert row is not None
    assert int(row[0]) == 1

    database.close()
