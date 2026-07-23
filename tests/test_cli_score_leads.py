from pathlib import Path

import pytest
from typer.testing import CliRunner

from lead_finder.cli import app
from lead_finder.database import init_database

runner = CliRunner()


@pytest.fixture
def temp_config(tmp_path: Path):
    db_path = tmp_path / "test.db"
    config_file = tmp_path / "config.yaml"

    config_content = f"""
project:
  name: "Test Project"
search:
  location: "New York, NY"
  queries:
    - "plumbers"
database:
  path: "{db_path.as_posix()}"
lead_scoring:
  enabled: true
  weights:
    no_website: 40
    missing_name: -20
    phone_missing: 0
    phone_present: 0
  thresholds:
    very_high: 80
    high: 60
    medium: 40
    low: 20
"""
    config_file.write_text(config_content)

    # Initialize DB with some data
    db = init_database(db_path)
    # Business 1: Missing website, should get 40 points (Medium)
    db.execute(
        "INSERT INTO businesses (id, place_id, business_name, website_url) "
        "VALUES (1, 'p1', 'Business 1', NULL)"
    )
    # Business 2: Missing website, Missing name, should get 20 points (Low)
    db.execute(
        "INSERT INTO businesses (id, place_id, business_name, website_url) "
        "VALUES (2, 'p2', '', NULL)"
    )
    # Business 3: Invalid place_id
    db.execute(
        "INSERT INTO businesses (id, place_id, business_name, website_url) "
        "VALUES (3, '', 'Invalid Place', NULL)"
    )

    db.save_website_check_result(
        business_id=1,
        original_url=None,
        normalized_url=None,
        final_url=None,
        status="no_website",
        http_status=None,
        redirect_count=0,
        response_time_ms=None,
        content_type=None,
        error_type=None,
        error_message=None,
    )
    db.save_website_check_result(
        business_id=2,
        original_url=None,
        normalized_url=None,
        final_url=None,
        status="no_website",
        http_status=None,
        redirect_count=0,
        response_time_ms=None,
        content_type=None,
        error_type=None,
        error_message=None,
    )
    db.commit()
    db.close()

    return config_file, db_path


def test_score_leads_success(temp_config):
    config_file, db_path = temp_config

    result = runner.invoke(app, ["score-leads", "--config", str(config_file)])

    assert result.exit_code == 0
    assert "Businesses considered: 3" in result.stdout
    assert "Businesses scored: 2" in result.stdout
    assert "Skipped existing scores: 0" in result.stdout
    assert "Unscorable businesses: 1" in result.stdout  # Business 3
    assert "Failed records: 0" in result.stdout

    assert "Medium priority: 1" in result.stdout
    assert "Low priority: 1" in result.stdout

    # Check persistence
    db = init_database(db_path)
    scores = db.execute("SELECT * FROM lead_scores ORDER BY business_id").fetchall()
    db.close()

    assert len(scores) == 2
    assert scores[0]["business_id"] == 1
    assert scores[0]["final_score"] == 40
    assert scores[0]["priority"] == "medium"

    assert scores[1]["business_id"] == 2
    assert scores[1]["final_score"] == 20
    assert scores[1]["priority"] == "low"


def test_existing_score_skipped_by_default(temp_config):
    config_file, db_path = temp_config

    # Run once
    runner.invoke(app, ["score-leads", "--config", str(config_file)])

    # Run twice
    result2 = runner.invoke(app, ["score-leads", "--config", str(config_file)])

    assert result2.exit_code == 0
    assert "Businesses considered: 3" in result2.stdout
    assert "Businesses scored: 0" in result2.stdout
    assert "Skipped existing scores: 2" in result2.stdout

    db = init_database(db_path)
    scores = db.execute("SELECT id FROM lead_scores").fetchall()
    db.close()
    assert len(scores) == 2  # No new scores added


def test_force_refresh_creates_history(temp_config):
    config_file, db_path = temp_config

    # Run once
    runner.invoke(app, ["score-leads", "--config", str(config_file)])

    # Run twice with force_refresh
    result2 = runner.invoke(app, ["score-leads", "--config", str(config_file), "--force-refresh"])

    assert result2.exit_code == 0
    assert "Businesses scored: 2" in result2.stdout
    assert "Skipped existing scores: 0" in result2.stdout

    db = init_database(db_path)
    scores = db.execute("SELECT business_id FROM lead_scores ORDER BY business_id").fetchall()
    db.close()
    assert len(scores) == 4  # 2 from first run, 2 from second run


def test_latest_website_check_is_used(tmp_path: Path):
    db_path = tmp_path / "test.db"
    config_file = tmp_path / "config.yaml"
    config_file.write_text(f"""
project:
  name: "Test"
search:
  location: "NY"
  queries: ["q"]
database:
  path: "{db_path.as_posix()}"
lead_scoring:
  enabled: true
  weights:
    working: 0
    timeout: 20
    phone_missing: 0
    phone_present: 0
""")
    db = init_database(db_path)
    db.execute("INSERT INTO businesses (id, place_id, business_name) VALUES (1, 'p1', 'B1')")

    # Old check: working
    db.execute(
        "INSERT INTO website_checks "
        "(business_id, status, checked_at) "
        "VALUES (1, 'working', '2000-01-01 00:00:00')"
    )
    # New check: timeout
    db.execute(
        "INSERT INTO website_checks "
        "(business_id, status, checked_at) "
        "VALUES (1, 'timeout', '2025-01-01 00:00:00')"
    )
    db.commit()
    db.close()

    result = runner.invoke(app, ["score-leads", "--config", str(config_file)])
    assert result.exit_code == 0

    db = init_database(db_path)
    score_row = db.execute(
        "SELECT raw_score, score_breakdown_json "
        "FROM lead_scores WHERE business_id = 1"
    ).fetchone()
    db.close()

    assert score_row["raw_score"] == 20  # Picked up the timeout

    breakdown = score_row["score_breakdown_json"]
    assert "timeout" in breakdown
    assert "working" not in breakdown


def test_migration_is_idempotent(temp_config):
    _, db_path = temp_config

    # init_database already ran once in fixture. Run again.
    db = init_database(db_path)

    # Should not crash.
    tables = db.table_names()
    assert "lead_scores" in tables
    db.close()


def test_explain_score(temp_config):
    config_file, _ = temp_config
    runner.invoke(app, ["score-leads", "--config", str(config_file)])

    result = runner.invoke(app, ["explain-score", "1", "--config", str(config_file)])
    assert result.exit_code == 0
    assert "Business 1" in result.stdout
    assert "Latest score" in result.stdout
    assert "no_website" in result.stdout
