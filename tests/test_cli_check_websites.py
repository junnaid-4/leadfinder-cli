import sqlite3

import httpx
import pytest
import respx
from typer.testing import CliRunner

from lead_finder.cli import app
from lead_finder.database import init_database


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test.db"
    db = init_database(db_path)

    # Insert some dummy businesses
    db.execute(
        "INSERT INTO businesses (id, place_id, business_name, website_url) VALUES (?, ?, ?, ?)",
        (1, "place_1", "Biz 1", "https://example.com/1"),
    )
    db.execute(
        "INSERT INTO businesses (id, place_id, business_name, website_url) VALUES (?, ?, ?, ?)",
        (2, "place_2", "Biz 2", "https://example.com/2"),
    )
    db.execute(
        "INSERT INTO businesses (id, place_id, business_name, website_url) VALUES (?, ?, ?, ?)",
        (3, "place_3", "Biz 3", None),  # no website
    )
    db.commit()

    yield db_path
    db.close()


@pytest.fixture
def temp_config(tmp_path, temp_db):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"""
project:
  name: "Test Project"
search:
  location: "Test City"
  queries: ["Test"]
website_check:
  enabled: true
  concurrency: 2
database:
  path: "{temp_db.as_posix()}"
""")
    return config_path


@respx.mock
def test_cli_check_websites_success(temp_config, temp_db):
    respx.get("https://example.com/1").mock(return_value=httpx.Response(200))
    respx.get("https://example.com/2").mock(return_value=httpx.Response(404))

    runner = CliRunner()
    result = runner.invoke(app, ["check-websites", "-c", str(temp_config)])

    assert result.exit_code == 0
    assert "Website checks completed: 3" in result.stdout
    assert "Working: 1" in result.stdout
    assert "HTTP errors: 1" in result.stdout
    assert "No website: 1" in result.stdout

    db = init_database(temp_db)
    cursor = db.execute("SELECT status FROM website_checks ORDER BY business_id")
    statuses = [row[0] for row in cursor.fetchall()]
    assert statuses == ["working", "http_error", "no_website"]


@respx.mock
def test_cli_check_websites_force_refresh_and_history(temp_config, temp_db):
    db = init_database(temp_db)

    # Requirement 10: A missing website persists a no_website row
    db.save_website_check_result(3, None, None, None, "no_website", None, 0, None, None, None, None)

    db.save_website_check_result(
        1,
        "https://example.com/1",
        "https://example.com/1",
        "https://example.com/1",
        "working",
        200,
        0,
        100,
        "text/html",
        None,
        None,
    )

    respx.get("https://example.com/2").mock(return_value=httpx.Response(200))
    runner = CliRunner()

    # Requirement 7: An already checked business is skipped when force_refresh=False
    result = runner.invoke(app, ["check-websites", "-c", str(temp_config)])
    assert "Website checks completed: 1" in result.stdout

    # Requirement 8 & 9: force_refresh=True inserts a second historical check result
    respx.get("https://example.com/1").mock(return_value=httpx.Response(200))
    result = runner.invoke(app, ["check-websites", "-c", str(temp_config), "--force-refresh"])
    assert "Website checks completed: 3" in result.stdout

    db = init_database(temp_db)
    cursor = db.execute("SELECT count(*) FROM website_checks WHERE business_id = 1")
    count = cursor.fetchone()[0]
    assert count == 2  # history preserved!


@respx.mock
def test_cli_check_websites_continues_on_failure(temp_config, temp_db):
    # Requirement 11: One website failure does not stop other businesses
    respx.get("https://example.com/1").mock(side_effect=RuntimeError("Unexpected disaster!"))
    respx.get("https://example.com/2").mock(return_value=httpx.Response(200))

    runner = CliRunner()
    result = runner.invoke(app, ["check-websites", "-c", str(temp_config)])

    assert result.exit_code == 0
    assert "Website checks completed: 3" in result.stdout
    assert "Working: 1" in result.stdout
    assert "Other failures: 1" in result.stdout


def test_database_migration_idempotent_no_data_loss(tmp_path):
    db_path = tmp_path / "mig_test.db"

    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE website_checks (
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
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE businesses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            place_id TEXT NOT NULL UNIQUE,
            business_name TEXT NOT NULL,
            website_url TEXT
        );
        INSERT INTO businesses (id, place_id, business_name, website_url)
        VALUES (10, 'old_place', 'Old Biz', 'http://old.com');
        INSERT INTO website_checks (place_id, original_url, issue_type)
        VALUES ('old_place', 'http://old.com', 'working');
    """)
    conn.close()

    # Requirement 12: previous schema migrates without data loss
    db = init_database(db_path)

    cursor = db.execute("PRAGMA table_info(website_checks)")
    cols = {row["name"] for row in cursor.fetchall()}
    assert "business_id" in cols
    assert "place_id" not in cols

    cursor = db.execute("SELECT business_id, status FROM website_checks")
    row = cursor.fetchone()
    assert row["business_id"] == 10
    assert row["status"] == "working"

    # Requirement 13: Running twice makes no further schema or data changes
    db2 = init_database(db_path)
    cursor2 = db2.execute("SELECT count(*) FROM website_checks")
    assert cursor2.fetchone()[0] == 1


@respx.mock
def test_cli_summary_counts_all(temp_config, temp_db):
    # Requirement 14: CLI summary counts all relevant classifications correctly
    db = init_database(temp_db)
    # Insert more dummy businesses
    db.execute(
        "INSERT INTO businesses (id, place_id, business_name, website_url) "
        "VALUES (4, 'p4', 'B4', 'https://example.com/4')"
    )
    db.execute(
        "INSERT INTO businesses (id, place_id, business_name, website_url) "
        "VALUES (5, 'p5', 'B5', 'https://example.com/5')"
    )
    db.execute(
        "INSERT INTO businesses (id, place_id, business_name, website_url) "
        "VALUES (6, 'p6', 'B6', 'https://example.com/6')"
    )
    db.commit()

    respx.get("https://example.com/1").mock(return_value=httpx.Response(200))
    respx.get("https://example.com/2").mock(return_value=httpx.Response(404))
    respx.get("https://example.com/4").mock(side_effect=httpx.ConnectTimeout("T"))
    respx.get("https://example.com/5").mock(side_effect=httpx.ConnectError("NameResolutionError"))
    respx.get("https://example.com/6").mock(return_value=httpx.Response(403))

    runner = CliRunner()
    result = runner.invoke(app, ["check-websites", "-c", str(temp_config)])

    assert "Website checks completed: 6" in result.stdout
    assert "Working: 1" in result.stdout
    assert "HTTP errors: 1" in result.stdout
    assert "Timeout: 1" in result.stdout
    assert "DNS" in result.stdout
    assert "Blocked: 1" in result.stdout
    assert "No website: 1" in result.stdout
