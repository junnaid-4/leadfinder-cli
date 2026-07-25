"""Tests for full-pipeline CLI orchestration."""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest
import yaml
from typer.testing import CliRunner

from lead_finder.cli import app
from lead_finder.pipeline import (
    CollectionSummary,
    ExportSummary,
    ScoringSummary,
    WebsiteCheckSummary,
)
from lead_finder.website_checker import WebsiteStatus

runner = CliRunner()


@pytest.fixture
def run_config(tmp_path: Path) -> Path:
    config = {
        "project": {"name": "Pipeline Test"},
        "search": {
            "location": "Test Place",
            "queries": ["test"],
            "max_results_per_query": 5,
            "max_total_results": 10,
            "max_api_requests": 2,
        },
        "database": {"path": str(tmp_path / "pipeline.db")},
        "logging": {"file": False, "console": False, "directory": str(tmp_path / "logs")},
        "export": {"output_directory": str(tmp_path / "exports")},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


def test_run_dry_run_has_no_side_effects_or_network(
    run_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("dry run invoked a side-effecting service")

    monkeypatch.setattr("lead_finder.cli.setup_logging", forbidden)
    monkeypatch.setattr("lead_finder.cli.collect_businesses", forbidden)
    monkeypatch.setattr("lead_finder.cli.check_business_websites", forbidden)
    result = runner.invoke(
        app, ["run", "--config", str(run_config), "--dry-run", "--format", "both"]
    )

    assert result.exit_code == 0, result.stdout
    assert "DRY RUN" in result.stdout
    assert "Maximum API requests: 2" in result.stdout
    assert not (run_config.parent / "pipeline.db").exists()
    assert not (run_config.parent / "exports").exists()
    assert not (run_config.parent / "logs").exists()


def _install_successful_stages(
    monkeypatch: pytest.MonkeyPatch, events: list[str], tmp_path: Path
) -> None:
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

    def collect(*args: object, **kwargs: object) -> CollectionSummary:
        events.append(f"collect:{kwargs.get('force_refresh')}")
        return CollectionSummary(3, 0, 1, 0, 0)

    def checks(*args: object, **kwargs: object) -> WebsiteCheckSummary:
        events.append(f"check:{kwargs.get('force_refresh')}")
        return WebsiteCheckSummary(3, 3, 0, {status: 0 for status in WebsiteStatus})

    def scoring(*args: object, **kwargs: object) -> ScoringSummary:
        events.append(f"score:{kwargs.get('force_refresh')}")
        return ScoringSummary(
            3,
            3,
            0,
            0,
            0,
            {"very_high": 1, "high": 1, "medium": 1, "low": 0, "very_low": 0},
            70.0,
            90,
        )

    def exporting(*args: object, **kwargs: object) -> ExportSummary:
        fmt = str(kwargs["fmt"])
        events.append(f"export:{fmt}:{kwargs.get('overwrite')}")
        directory = Path(kwargs.get("output_dir") or tmp_path / "exports")
        directory.mkdir(parents=True, exist_ok=True)
        paths = []
        if fmt in ("csv", "both"):
            path = directory / "leads.csv"
            path.write_text("demo", encoding="utf-8")
            paths.append(path)
        if fmt in ("xlsx", "both"):
            path = directory / "leads.xlsx"
            workbook = openpyxl.Workbook()
            workbook.save(path)
            workbook.close()
            paths.append(path)
        return ExportSummary(3, 3, tuple(paths))

    monkeypatch.setattr("lead_finder.cli.collect_businesses", collect)
    monkeypatch.setattr("lead_finder.cli.check_business_websites", checks)
    monkeypatch.setattr("lead_finder.cli.score_businesses", scoring)
    monkeypatch.setattr("lead_finder.cli.export_lead_files", exporting)


@pytest.mark.parametrize(
    ("fmt", "csv_exists", "xlsx_exists"),
    [("csv", True, False), ("xlsx", False, True), ("both", True, True)],
)
def test_run_stage_order_and_formats(
    run_config: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fmt: str,
    csv_exists: bool,
    xlsx_exists: bool,
) -> None:
    events: list[str] = []
    _install_successful_stages(monkeypatch, events, tmp_path)
    output = tmp_path / fmt
    result = runner.invoke(
        app,
        [
            "run",
            "--config",
            str(run_config),
            "--format",
            fmt,
            "--output-dir",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert [event.split(":")[0] for event in events] == ["collect", "check", "score", "export"]
    assert (output / "leads.csv").exists() is csv_exists
    assert (output / "leads.xlsx").exists() is xlsx_exists


def test_run_force_refresh_is_propagated(
    run_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    _install_successful_stages(monkeypatch, events, tmp_path)
    result = runner.invoke(app, ["run", "--config", str(run_config), "--force-refresh"])
    assert result.exit_code == 0
    assert events[:3] == ["collect:True", "check:True", "score:True"]
    assert events[-1].endswith(":False")


def test_run_overwrite_is_separate(
    run_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    _install_successful_stages(monkeypatch, events, tmp_path)
    result = runner.invoke(app, ["run", "--config", str(run_config), "--overwrite"])
    assert result.exit_code == 0
    assert events[:3] == ["collect:False", "check:False", "score:False"]
    assert events[-1].endswith(":True")


def test_run_rejects_partial_collection(run_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setattr(
        "lead_finder.cli.collect_businesses",
        lambda *args, **kwargs: CollectionSummary(2, 0, 1, 0, 1),
    )
    result = runner.invoke(app, ["run", "--config", str(run_config)])
    assert result.exit_code == 1
    assert "Collection failed for 1 configured queries" in result.stdout


def test_run_failed_required_stage_is_nonzero(
    run_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

    def fail(*args: object, **kwargs: object) -> CollectionSummary:
        raise RuntimeError("collection unavailable")

    monkeypatch.setattr("lead_finder.cli.collect_businesses", fail)
    result = runner.invoke(app, ["run", "--config", str(run_config)])
    assert result.exit_code == 1
    assert "Pipeline failed" in result.stdout
    assert "collection unavailable" in result.stdout


def test_existing_commands_remain_public() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in (
        "validate-config",
        "collect",
        "check-websites",
        "score-leads",
        "explain-score",
        "export-leads",
        "demo",
        "run",
    ):
        assert command in result.stdout
    assert "not implemented" not in result.stdout.lower()
