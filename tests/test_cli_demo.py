"""Tests for the zero-key fictional demonstration."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from lead_finder.cli import app
from lead_finder.demo_data import FICTIONAL_BUSINESSES

runner = CliRunner()


@pytest.fixture
def demo_config(tmp_path: Path) -> Path:
    repository_root = Path(__file__).resolve().parents[1]
    source = yaml.safe_load((repository_root / "config.demo.yaml").read_text(encoding="utf-8"))
    source["database"]["path"] = str(tmp_path / "data" / "demo_lead_finder.db")
    source["export"]["output_directory"] = str(tmp_path / "demo_output")
    source["output"]["directory"] = str(tmp_path / "demo_output")
    config = tmp_path / "config.demo.yaml"
    config.write_text(yaml.safe_dump(source), encoding="utf-8")
    return config


def test_demo_is_network_free_and_needs_no_key(
    demo_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)

    def network_forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("demo attempted network access")

    monkeypatch.setattr("httpx.AsyncClient", network_forbidden)
    result = runner.invoke(app, ["demo", "--config", str(demo_config)])

    assert result.exit_code == 0, result.stdout
    assert "Businesses inserted: 12" in result.stdout
    assert "Businesses scored: 12" in result.stdout


def test_demo_persists_checks_scores_priorities_and_exports(demo_config: Path) -> None:
    result = runner.invoke(app, ["demo", "--config", str(demo_config)])
    assert result.exit_code == 0, result.stdout

    db_path = demo_config.parent / "data" / "demo_lead_finder.db"
    csv_path = demo_config.parent / "demo_output" / "leads.csv"
    xlsx_path = demo_config.parent / "demo_output" / "leads.xlsx"
    assert db_path.exists()
    assert csv_path.exists()
    assert xlsx_path.exists()

    connection = sqlite3.connect(db_path)
    business_count = connection.execute("SELECT count(*) FROM businesses").fetchone()[0]
    check_count = connection.execute("SELECT count(*) FROM website_checks").fetchone()[0]
    score_count = connection.execute("SELECT count(*) FROM lead_scores").fetchone()[0]
    priorities = {row[0] for row in connection.execute("SELECT DISTINCT priority FROM lead_scores")}
    statuses = {row[0] for row in connection.execute("SELECT DISTINCT status FROM website_checks")}
    connection.close()

    assert business_count == len(FICTIONAL_BUSINESSES) == 12
    assert check_count == 12
    assert score_count == 12
    assert len(priorities) >= 3
    assert {
        "no_website",
        "working",
        "unreachable",
        "dns_error",
        "ssl_error",
        "timeout",
        "http_error",
        "invalid_url",
    } <= statuses


def test_demo_is_deterministic_with_overwrite(demo_config: Path) -> None:
    first = runner.invoke(app, ["demo", "--config", str(demo_config)])
    assert first.exit_code == 0
    csv_path = demo_config.parent / "demo_output" / "leads.csv"
    first_csv = csv_path.read_bytes()

    refused = runner.invoke(app, ["demo", "--config", str(demo_config)])
    assert refused.exit_code == 1
    assert "Use --overwrite" in refused.stdout
    assert csv_path.read_bytes() == first_csv

    replaced = runner.invoke(app, ["demo", "--config", str(demo_config), "--overwrite"])
    assert replaced.exit_code == 0, replaced.stdout
    assert csv_path.read_bytes() == first_csv


def test_demo_data_is_clearly_fictional_and_secret_free(demo_config: Path) -> None:
    result = runner.invoke(app, ["demo", "--config", str(demo_config)])
    assert result.exit_code == 0
    csv_path = demo_config.parent / "demo_output" / "leads.csv"
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert all(row["place_id"].startswith("demo-place-") for row in rows)
    assert all("Fictionland" in row["address"] for row in rows)
    text = csv_path.read_text(encoding="utf-8")
    assert "AIza" not in text
    assert "GOOGLE_MAPS_API_KEY" not in text
    assert all(
        business.website is None
        or business.website == "not a valid url"
        or any(domain in business.website for domain in (".example.", ".invalid"))
        for business in FICTIONAL_BUSINESSES
    )
