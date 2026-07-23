from pathlib import Path

import pytest
from typer.testing import CliRunner

from lead_finder.cli import app
from lead_finder.database import init_database

runner = CliRunner()


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    db = init_database(db_path)

    # Insert businesses
    db.execute(
        "INSERT INTO businesses (place_id, business_name, business_status, review_count) VALUES "
        "('P1', 'Business A', 'OPERATIONAL', 10),"
        "('P2', 'Business B', 'OPERATIONAL', 20),"
        "('P3', 'Business C', 'CLOSED_PERMANENTLY', 30),"
        "('P4', 'Business D', 'OPERATIONAL', 40)"
    )

    # Insert website checks (testing latest selection & ID resolution)
    # Business 1 has two checks
    db.save_website_check_result(
        business_id=1,
        original_url="http://a.com",
        normalized_url="https://a.com",
        final_url="https://a.com",
        status="timeout",
        http_status=0,
        redirect_count=0,
        response_time_ms=None,
        content_type=None,
        error_type=None,
        error_message=None,
    )
    db.execute("UPDATE website_checks SET checked_at = '2023-01-01T00:00:00Z' WHERE id = 1")

    db.save_website_check_result(
        business_id=1,
        original_url="http://a.com",
        normalized_url="https://a.com",
        final_url="https://a.com",
        status="working",
        http_status=200,
        redirect_count=0,
        response_time_ms=100,
        content_type="text/html",
        error_type=None,
        error_message=None,
    )
    db.execute("UPDATE website_checks SET checked_at = '2023-01-02T00:00:00Z' WHERE id = 2")

    # Business 2 has two checks with identical timestamps (should pick highest ID)
    db.save_website_check_result(
        business_id=2,
        original_url="http://b.com",
        normalized_url="https://b.com",
        final_url="https://b.com",
        status="timeout",
        http_status=0,
        redirect_count=0,
        response_time_ms=None,
        content_type=None,
        error_type=None,
        error_message=None,
    )
    db.execute("UPDATE website_checks SET checked_at = '2023-01-01T00:00:00Z' WHERE id = 3")

    db.save_website_check_result(
        business_id=2,
        original_url="http://b.com",
        normalized_url="https://b.com",
        final_url="https://b.com",
        status="working",
        http_status=200,
        redirect_count=0,
        response_time_ms=100,
        content_type="text/html",
        error_type=None,
        error_message=None,
    )
    db.execute("UPDATE website_checks SET checked_at = '2023-01-01T00:00:00Z' WHERE id = 4")

    # Insert lead scores
    db.save_lead_score(
        business_id=1,
        raw_score=90,
        final_score=90,
        priority="very_high",
        score_breakdown_json='{"test":1}',
        scoring_version="v1",
        scored_at="2023-01-01T00:00:00Z",
    )
    db.save_lead_score(
        business_id=1,
        raw_score=80,
        final_score=80,
        priority="high",
        score_breakdown_json='{"test":2}',
        scoring_version="v1",
        scored_at="2023-01-02T00:00:00Z",
    )

    # Business 2 score
    db.save_lead_score(
        business_id=2,
        raw_score=40,
        final_score=40,
        priority="medium",
        score_breakdown_json='{"test":3}',
        scoring_version="v1",
        scored_at="2023-01-01T00:00:00Z",
    )

    # Business 3 is permanently closed and unscored.
    # Business 4 is unscored and operational.

    db.close()
    return db_path


@pytest.fixture
def temp_config(tmp_path: Path, temp_db: Path) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"""
project:
  name: "Test"
search:
  location: "Test"
  queries: ["test"]
output:
  directory: "{tmp_path}/output"
database:
  path: "{temp_db}"
export:
  default_format: csv
  output_directory: "{tmp_path}/exports"
  include_unscored: false
  minimum_score: 0
  priorities: []
    """)
    return config_path


def test_export_leads_basic_csv(temp_config: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "export-leads",
            "--config",
            str(temp_config),
        ],
    )
    assert result.exit_code == 0
    assert "Rows exported: 2" in result.stdout
    assert "Unscored rows included: 0" in result.stdout

    export_dir = tmp_path / "exports"
    csv_file = export_dir / "leads.csv"
    assert csv_file.exists()

    # Check absolute path printed
    assert str(csv_file.resolve()) in result.stdout

    # Check content to verify latest score / website check
    content = csv_file.read_text()
    assert "working" in content  # latest website check for B1 and B2
    assert "high" in content  # latest score for B1


def test_export_leads_limit_applied_after_sorting(temp_config: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "export-leads",
            "--config",
            str(temp_config),
            "--limit",
            "1",
        ],
    )
    assert result.exit_code == 0
    assert "Rows exported: 1" in result.stdout

    # B1 has 'high' (1), B2 has 'medium' (2). Priority sort puts B1 first.
    content = (tmp_path / "exports" / "leads.csv").read_text()
    assert "Business A" in content
    assert "Business B" not in content


def test_export_leads_include_unscored(temp_config: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "export-leads",
            "--config",
            str(temp_config),
            "--include-unscored",
        ],
    )
    assert result.exit_code == 0
    assert "Rows exported: 3" in result.stdout  # B1, B2, B4 (B3 is closed)
    assert "Unscored rows included: 1" in result.stdout

    content = (tmp_path / "exports" / "leads.csv").read_text()
    assert "Business D" in content


def test_export_leads_yaml_unscored_overridden(tmp_path: Path, temp_db: Path) -> None:
    config_path = tmp_path / "config2.yaml"
    config_path.write_text(f"""
project:
  name: "Test"
search:
  location: "Test"
  queries: ["test"]
database:
  path: "{temp_db}"
export:
  default_format: csv
  output_directory: "{tmp_path}/exports"
  include_unscored: true
    """)
    # YAML says true, CLI overrides to false
    result = runner.invoke(
        app,
        [
            "export-leads",
            "--config",
            str(config_path),
            "--exclude-unscored",
        ],
    )
    assert result.exit_code == 0
    assert "Rows exported: 2" in result.stdout


def test_export_leads_priority_filter(temp_config: Path) -> None:
    result = runner.invoke(
        app,
        [
            "export-leads",
            "--config",
            str(temp_config),
            "--priority",
            "medium",
        ],
    )
    assert result.exit_code == 0
    assert "Rows exported: 1" in result.stdout
    assert "medium" in result.stdout


def test_export_leads_min_score(temp_config: Path) -> None:
    result = runner.invoke(
        app,
        [
            "export-leads",
            "--config",
            str(temp_config),
            "--min-score",
            "50",
        ],
    )
    assert result.exit_code == 0
    assert "Rows exported: 1" in result.stdout


def test_export_leads_format_suffix_mismatch(temp_config: Path, tmp_path: Path) -> None:
    output = tmp_path / "test.xlsx"
    result = runner.invoke(
        app,
        [
            "export-leads",
            "--config",
            str(temp_config),
            "--format",
            "csv",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 1
    assert "suffix does not match" in result.stdout


def test_export_leads_suffix_appended(temp_config: Path, tmp_path: Path) -> None:
    output = tmp_path / "test_no_ext"
    result = runner.invoke(
        app,
        [
            "export-leads",
            "--config",
            str(temp_config),
            "--format",
            "xlsx",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0
    assert (tmp_path / "test_no_ext.xlsx").exists()


def test_export_leads_existing_directory(temp_config: Path, tmp_path: Path) -> None:
    output = tmp_path / "my_dir"
    output.mkdir()
    result = runner.invoke(
        app,
        [
            "export-leads",
            "--config",
            str(temp_config),
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 1
    assert "directory, not a file" in result.stdout


def test_export_leads_zero_rows(temp_config: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "export-leads",
            "--config",
            str(temp_config),
            "--min-score",
            "100",
        ],
    )
    assert result.exit_code == 0
    assert "Rows matching filters: 0" in result.stdout
    assert not (tmp_path / "exports" / "leads.csv").exists()


def test_export_leads_rejects_existing_without_overwrite(temp_config: Path, tmp_path: Path) -> None:
    output = tmp_path / "test.csv"
    output.write_text("existing")
    result = runner.invoke(
        app,
        [
            "export-leads",
            "--config",
            str(temp_config),
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 1
    assert "already exists" in result.stdout


def test_export_leads_overwrites_existing(temp_config: Path, tmp_path: Path) -> None:
    output = tmp_path / "test.csv"
    output.write_text("existing")
    result = runner.invoke(
        app,
        [
            "export-leads",
            "--config",
            str(temp_config),
            "--output",
            str(output),
            "--overwrite",
        ],
    )
    assert result.exit_code == 0
    assert output.read_text() != "existing"


def test_export_leads_database_unchanged(temp_config: Path, temp_db: Path) -> None:
    db1 = temp_db.read_bytes()
    result = runner.invoke(
        app,
        [
            "export-leads",
            "--config",
            str(temp_config),
        ],
    )
    assert result.exit_code == 0
    db2 = temp_db.read_bytes()
    assert db1 == db2  # Read only operation
