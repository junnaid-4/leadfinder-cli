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
    business_id INTEGER NOT NULL,
    original_url TEXT,
    normalized_url TEXT,
    final_url TEXT,
    status TEXT NOT NULL,
    http_status INTEGER,
    redirect_count INTEGER NOT NULL DEFAULT 0,
    response_time_ms INTEGER,
    content_type TEXT,
    error_type TEXT,
    error_message TEXT,
    checked_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
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
CREATE INDEX IF NOT EXISTS idx_website_checks_business_id ON website_checks(business_id);
CREATE INDEX IF NOT EXISTS idx_website_checks_status ON website_checks(status);
CREATE INDEX IF NOT EXISTS idx_website_checks_checked_at ON website_checks(checked_at);
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
        self._migrate_website_checks_schema(connection)
        self._migrate_lead_scores_schema(connection)
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

    def _migrate_lead_scores_schema(self, connection: sqlite3.Connection) -> None:
        """Create the lead_scores table if missing."""
        cursor = connection.execute("PRAGMA table_info(lead_scores)")
        columns = {row["name"] for row in cursor.fetchall()}

        if not columns:
            connection.execute(
                """
                CREATE TABLE lead_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    business_id INTEGER NOT NULL,
                    raw_score INTEGER NOT NULL,
                    final_score INTEGER NOT NULL,
                    priority TEXT NOT NULL,
                    score_breakdown_json TEXT NOT NULL,
                    scoring_version TEXT NOT NULL,
                    scored_at TEXT NOT NULL,
                    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_lead_scores_business_id ON lead_scores(business_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_lead_scores_final_score ON lead_scores(final_score)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_lead_scores_priority ON lead_scores(priority)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_lead_scores_scored_at ON lead_scores(scored_at)"
            )
            connection.commit()

    def _migrate_website_checks_schema(self, connection: sqlite3.Connection) -> None:
        """Migrate the website_checks table from Stage 1/2 to Stage 3 safely."""
        cursor = connection.execute("PRAGMA table_info(website_checks)")
        columns = {row["name"] for row in cursor.fetchall()}

        if not columns or "business_id" in columns:
            return  # Either doesn't exist yet or is already the new schema

        # Old schema has 'place_id'. We create a new table, copy data, and swap.
        connection.execute(
            """
            CREATE TABLE website_checks_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL,
                original_url TEXT,
                normalized_url TEXT,
                final_url TEXT,
                status TEXT NOT NULL,
                http_status INTEGER,
                redirect_count INTEGER NOT NULL DEFAULT 0,
                response_time_ms INTEGER,
                content_type TEXT,
                error_type TEXT,
                error_message TEXT,
                checked_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
            )
            """
        )

        connection.execute(
            """
            INSERT INTO website_checks_new (
                business_id, original_url, normalized_url, final_url, status,
                http_status, redirect_count, response_time_ms, content_type,
                error_type, error_message, checked_at
            )
            SELECT
                b.id, wc.original_url, wc.original_url, wc.final_url,
                COALESCE(wc.issue_type, 'unknown_error'),
                wc.final_status_code, wc.redirect_count, wc.response_time_ms,
                wc.content_type, wc.issue_type, wc.issue_description,
                COALESCE(wc.checked_at, wc.created_at)
            FROM website_checks wc
            JOIN businesses b ON b.place_id = wc.place_id
            """
        )

        connection.execute("DROP TABLE website_checks")
        connection.execute("ALTER TABLE website_checks_new RENAME TO website_checks")
        connection.commit()

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

    def get_businesses_needing_checks(self, force_refresh: bool = False) -> list[sqlite3.Row]:
        """Return businesses needing website checks."""
        sql = """
            SELECT id, place_id, business_name, website_url
            FROM businesses
        """
        if not force_refresh:
            sql += """
                WHERE NOT EXISTS (
                    SELECT 1 FROM website_checks
                    WHERE website_checks.business_id = businesses.id
                )
            """
        cursor = self.execute(sql)
        return cursor.fetchall()

    def save_website_check_result(
        self,
        business_id: int,
        original_url: str | None,
        normalized_url: str | None,
        final_url: str | None,
        status: str,
        http_status: int | None,
        redirect_count: int,
        response_time_ms: int | None,
        content_type: str | None,
        error_type: str | None,
        error_message: str | None,
    ) -> None:
        self.execute(
            """
            INSERT INTO website_checks (
                business_id, original_url, normalized_url, final_url, status,
                http_status, redirect_count, response_time_ms, content_type,
                error_type, error_message, checked_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                business_id,
                original_url,
                normalized_url,
                final_url,
                status,
                http_status,
                redirect_count,
                response_time_ms,
                content_type,
                error_type,
                error_message,
            ),
        )
        self.commit()

    def get_businesses_to_score(self, force_refresh: bool = False) -> list[sqlite3.Row]:
        """Return businesses needing lead scoring, paired with their latest website check."""
        # Using a correlated subquery to get the latest website check reliably
        sql = """
            SELECT
                b.id as business_id,
                b.place_id,
                b.business_name,
                b.phone,
                b.address as formatted_address,
                b.rating,
                b.review_count as user_rating_count,
                b.business_status,
                wc.original_url as website_original_url,
                wc.normalized_url as website_normalized_url,
                wc.final_url as website_final_url,
                wc.status as website_check_status,
                wc.http_status as website_http_status,
                wc.redirect_count as website_redirect_count,
                wc.response_time_ms as website_response_time_ms,
                wc.content_type as website_content_type,
                wc.error_type as website_error_type,
                wc.error_message as website_error_message
            FROM businesses b
            LEFT JOIN website_checks wc ON wc.id = (
                SELECT id FROM website_checks
                WHERE business_id = b.id
                ORDER BY checked_at DESC, id DESC
                LIMIT 1
            )
        """
        if not force_refresh:
            sql += """
                WHERE NOT EXISTS (
                    SELECT 1 FROM lead_scores
                    WHERE lead_scores.business_id = b.id
                )
            """
        cursor = self.execute(sql)
        return cursor.fetchall()

    def save_lead_score(
        self,
        business_id: int,
        raw_score: int,
        final_score: int,
        priority: str,
        score_breakdown_json: str,
        scoring_version: str,
        scored_at: str,
    ) -> None:
        self.execute(
            """
            INSERT INTO lead_scores (
                business_id, raw_score, final_score, priority,
                score_breakdown_json, scoring_version, scored_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                business_id,
                raw_score,
                final_score,
                priority,
                score_breakdown_json,
                scoring_version,
                scored_at,
            ),
        )
        self.commit()

    def count_candidate_businesses(self) -> int:
        """Return the total number of businesses considered for export."""
        cursor = self.execute("SELECT count(*) FROM businesses")
        row = cursor.fetchone()
        if row is None:
            return 0
        return int(row[0])

    def get_leads_for_export(self) -> list[sqlite3.Row]:
        """Fetch all businesses with their latest website checks and lead scores."""
        sql = """
            SELECT
                b.id as business_id,
                b.place_id,
                b.business_name,
                b.phone,
                b.address,
                b.rating,
                b.review_count,
                b.business_status,
                wc.original_url as website_original_url,
                wc.normalized_url as website_normalized_url,
                wc.final_url as website_final_url,
                wc.status as website_status,
                wc.http_status,
                wc.checked_at as website_checked_at,
                ls.raw_score,
                ls.final_score,
                ls.priority,
                ls.scoring_version,
                ls.score_breakdown_json,
                ls.scored_at,
                b.search_query as discovery_queries,
                b.google_maps_url
            FROM businesses b
            LEFT JOIN website_checks wc ON wc.id = (
                SELECT id FROM website_checks
                WHERE business_id = b.id
                ORDER BY checked_at DESC, id DESC
                LIMIT 1
            )
            LEFT JOIN lead_scores ls ON ls.id = (
                SELECT id FROM lead_scores
                WHERE business_id = b.id
                ORDER BY scored_at DESC, id DESC
                LIMIT 1
            )
        """
        cursor = self.execute(sql)
        return cursor.fetchall()


def init_database(path: Path) -> Database:
    """Initialize database at the given path."""
    database = Database(path)
    database.initialize()
    return database
