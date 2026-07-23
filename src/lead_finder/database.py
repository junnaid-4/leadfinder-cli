"""SQLite database initialization and connection management."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS search_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_name TEXT NOT NULL,
    search_location TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    started_at TEXT,
    finished_at TEXT,
    businesses_discovered INTEGER NOT NULL DEFAULT 0,
    duplicates_removed INTEGER NOT NULL DEFAULT 0,
    api_requests_used INTEGER NOT NULL DEFAULT 0,
    website_checks_completed INTEGER NOT NULL DEFAULT 0,
    dry_run INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS search_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_run_id INTEGER NOT NULL,
    query_text TEXT NOT NULL,
    location TEXT NOT NULL,
    results_returned INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (search_run_id) REFERENCES search_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    place_id TEXT NOT NULL UNIQUE,
    business_name TEXT NOT NULL,
    category TEXT,
    additional_categories TEXT,
    address TEXT,
    city TEXT,
    postal_code TEXT,
    phone TEXT,
    international_phone TEXT,
    google_maps_url TEXT,
    website_url TEXT,
    rating REAL,
    review_count INTEGER,
    business_status TEXT,
    opening_hours_status TEXT,
    search_query TEXT,
    search_location TEXT,
    lead_category TEXT NOT NULL DEFAULT 'UNCHECKED',
    manual_review_required INTEGER NOT NULL DEFAULT 0,
    collected_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS website_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    place_id TEXT NOT NULL,
    original_url TEXT,
    final_url TEXT,
    initial_status_code INTEGER,
    final_status_code INTEGER,
    redirect_count INTEGER NOT NULL DEFAULT 0,
    response_time_ms INTEGER,
    content_type TEXT,
    check_attempts INTEGER NOT NULL DEFAULT 0,
    issue_type TEXT,
    issue_description TEXT,
    important_broken_page TEXT,
    lead_category TEXT NOT NULL DEFAULT 'UNCHECKED',
    checked_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (place_id) REFERENCES businesses(place_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cached_api_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_key TEXT NOT NULL UNIQUE,
    endpoint TEXT NOT NULL,
    response_body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_businesses_place_id ON businesses(place_id);
CREATE INDEX IF NOT EXISTS idx_website_checks_place_id ON website_checks(place_id);
CREATE INDEX IF NOT EXISTS idx_cached_api_expires ON cached_api_responses(expires_at);
CREATE INDEX IF NOT EXISTS idx_search_queries_run_id ON search_queries(search_run_id);
"""


class Database:
    """SQLite database wrapper."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._connection: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        """Open a connection, creating the database file if needed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self._connection is None:
            self._connection = sqlite3.connect(self.path)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
        return self._connection

    def close(self) -> None:
        """Close the active connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def initialize(self) -> int:
        """Create schema if missing and return schema version."""
        connection = self.connect()
        connection.executescript(CREATE_TABLES_SQL)
        version = self.get_schema_version(connection)
        if version is None:
            connection.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
            connection.commit()
            return SCHEMA_VERSION
        if version != SCHEMA_VERSION:
            msg = f"Unsupported schema version {version}. Expected version {SCHEMA_VERSION}."
            raise RuntimeError(msg)
        connection.commit()
        return version

    @staticmethod
    def get_schema_version(connection: sqlite3.Connection) -> int | None:
        """Return stored schema version, or None if unset."""
        cursor = connection.execute("SELECT version FROM schema_version LIMIT 1")
        row = cursor.fetchone()
        if row is None:
            return None
        return int(row[0])

    def table_names(self) -> list[str]:
        """Return user table names for inspection and tests."""
        connection = self.connect()
        cursor = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )
        return [str(row[0]) for row in cursor.fetchall()]

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        """Execute SQL on the active connection."""
        connection = self.connect()
        return connection.execute(sql, parameters)

    def commit(self) -> None:
        """Commit pending changes."""
        connection = self.connect()
        connection.commit()

    def get_cached_api_response(self, cache_key: str) -> str | None:
        cursor = self.execute(
            "SELECT response_body FROM cached_api_responses "
            "WHERE cache_key = ? AND expires_at > datetime('now')",
            (cache_key,),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def save_cached_api_response(
        self, cache_key: str, endpoint: str, response_body: str, expires_at: str
    ) -> None:
        self.execute(
            """
            INSERT INTO cached_api_responses (
                cache_key, endpoint, response_body, created_at, expires_at
            )
            VALUES (?, ?, ?, datetime('now'), ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                response_body=excluded.response_body,
                created_at=excluded.created_at,
                expires_at=excluded.expires_at
            """,
            (cache_key, endpoint, response_body, expires_at),
        )
        self.commit()

    def insert_or_update_business(
        self,
        place_id: str,
        name: str,
        query: str,
        location: str,
        data: dict[str, Any],
    ) -> bool:
        """Insert or update a business if it exists. Returns True if inserted."""
        cursor = self.execute("SELECT id FROM businesses WHERE place_id = ?", (place_id,))
        exists = cursor.fetchone() is not None

        category = data.get("primaryType")
        types_list = data.get("types", [])
        additional = ",".join(types_list) if types_list else None

        rating = data.get("rating")
        review_count = data.get("userRatingCount")

        opening_hours = data.get("currentOpeningHours")
        if opening_hours:
            open_status = "open" if opening_hours.get("openNow") else "closed"
        else:
            open_status = None

        if not exists:
            self.execute(
                """
                INSERT INTO businesses (
                    place_id, business_name, category, additional_categories,
                    address, phone, international_phone, google_maps_url,
                    website_url, rating, review_count, business_status,
                    opening_hours_status, search_query, search_location, collected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    place_id,
                    name,
                    category,
                    additional,
                    data.get("formattedAddress"),
                    data.get("nationalPhoneNumber"),
                    data.get("internationalPhoneNumber"),
                    data.get("googleMapsUri"),
                    data.get("websiteUri"),
                    rating,
                    review_count,
                    data.get("businessStatus"),
                    open_status,
                    query,
                    location,
                ),
            )
            return True
        else:
            self.execute(
                """
                UPDATE businesses
                SET
                    business_name = COALESCE(NULLIF(?, ''), business_name),
                    category = COALESCE(NULLIF(?, ''), category),
                    additional_categories = COALESCE(NULLIF(?, ''), additional_categories),
                    address = COALESCE(NULLIF(?, ''), address),
                    phone = COALESCE(NULLIF(?, ''), phone),
                    international_phone = COALESCE(NULLIF(?, ''), international_phone),
                    google_maps_url = COALESCE(NULLIF(?, ''), google_maps_url),
                    website_url = COALESCE(NULLIF(?, ''), website_url),
                    rating = COALESCE(?, rating),
                    review_count = COALESCE(?, review_count),
                    business_status = COALESCE(NULLIF(?, ''), business_status),
                    updated_at = datetime('now')
                WHERE place_id = ?
                """,
                (
                    name,
                    category,
                    additional,
                    data.get("formattedAddress"),
                    data.get("nationalPhoneNumber"),
                    data.get("internationalPhoneNumber"),
                    data.get("googleMapsUri"),
                    data.get("websiteUri"),
                    rating,
                    review_count,
                    data.get("businessStatus"),
                    place_id,
                ),
            )
            return False

    def create_search_run(self, config_name: str, location: str, dry_run: bool) -> int:
        cursor = self.execute(
            """
            INSERT INTO search_runs (config_name, search_location, status, started_at, dry_run)
            VALUES (?, ?, 'RUNNING', datetime('now'), ?)
            """,
            (config_name, location, 1 if dry_run else 0),
        )
        self.commit()
        return int(cursor.lastrowid) if cursor.lastrowid else 0

    def update_search_run(
        self, run_id: int, status: str, discovered: int, duplicates: int, api_requests: int
    ) -> None:
        self.execute(
            """
            UPDATE search_runs
            SET status = ?,
                finished_at = datetime('now'),
                businesses_discovered = businesses_discovered + ?,
                duplicates_removed = duplicates_removed + ?,
                api_requests_used = api_requests_used + ?
            WHERE id = ?
            """,
            (status, discovered, duplicates, api_requests, run_id),
        )
        self.commit()

    def add_search_query_log(
        self, run_id: int, query: str, location: str, results_returned: int
    ) -> None:
        self.execute(
            """
            INSERT INTO search_queries (search_run_id, query_text, location, results_returned)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, query, location, results_returned),
        )
        self.commit()


def init_database(path: Path) -> Database:
    """Initialize database at the given path."""
    database = Database(path)
    database.initialize()
    return database
