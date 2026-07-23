"""Tests for the CLI collect command."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from lead_finder.cli import app
from lead_finder.database import init_database
from lead_finder.places_client import FIELD_MASK, PLACES_API_URL, build_places_cache_key

runner = CliRunner()


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test_key")


@pytest.fixture
def temp_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "test.db"

    # We must format path correctly for yaml (forward slashes)
    db_path_str = str(db_path).replace("\\", "/")
    tmp_path_str = str(tmp_path).replace("\\", "/")

    config_path.write_text(
        f"""
project:
  name: "Test Project"
  data_directory: "{tmp_path_str}"

search:
  location: "Manchester, UK"
  queries:
    - "plumbers"
    - "electricians"
  max_results_per_query: 2
  max_total_results: 3
  max_api_requests: 3

database:
  path: "{db_path_str}"

logging:
  level: "DEBUG"
  console: true
  file: false

cache:
  places_ttl_days: 7
  website_ttl_days: 7
        """
    )
    return config_path


def test_validate_config_no_api_key_required(
    temp_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """25. API key not required for validate-config."""
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    result = runner.invoke(app, ["validate-config", "-c", str(temp_config)])
    assert result.exit_code == 0
    assert "Configuration is valid" in result.stdout


def test_collect_missing_api_key(temp_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """24. Missing API key for collect."""
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    result = runner.invoke(app, ["collect", "-c", str(temp_config)])
    assert result.exit_code == 1
    assert "API key is missing" in result.stdout


def test_collect_dry_run(temp_config: Path, mock_env: None) -> None:
    """27. Dry run makes zero HTTP requests. 28. Dry run makes zero database writes."""
    with respx.mock:
        route = respx.post(PLACES_API_URL).mock(return_value=httpx.Response(200, json={}))

        result = runner.invoke(app, ["collect", "-c", str(temp_config), "--dry-run"])

        assert result.exit_code == 0
        assert "DRY RUN MODE ENABLED" in result.stdout
        assert route.call_count == 0

        # Verify db was NOT created, or if created, no businesses inserted
        db_path = temp_config.parent / "test.db"

        if db_path.exists():
            db = init_database(db_path)
            count = db.execute("SELECT COUNT(*) FROM search_runs").fetchone()[0]
            assert count == 0


def test_collect_respects_limits(temp_config: Path, mock_env: None) -> None:
    """3. Multiple queries. 7. max_res. 8. max_tot. 9. max_api. 10. checked."""
    with respx.mock:
        # Plumbers API request 1: returns 2 places
        route1 = respx.post(PLACES_API_URL, json__textQuery="plumbers in Manchester, UK").mock(
            return_value=httpx.Response(
                200, json={"places": [{"id": "P1"}, {"id": "P2"}], "nextPageToken": "t1"}
            )
        )

        # Electricians API request 1
        route2 = respx.post(PLACES_API_URL, json__textQuery="electricians in Manchester, UK").mock(
            return_value=httpx.Response(200, json={"places": [{"id": "E1"}, {"id": "E2"}]})
        )

        result = runner.invoke(app, ["collect", "-c", str(temp_config)])
        assert result.exit_code == 0

        # Plumbers returns 2 places and reaches max_results_per_query.
        # It must stop before requesting the next page token.
        # Electricians query got 1 place (hits max_total_results of 3).
        assert "Unique businesses saved: 3" in result.stdout
        assert "Live API requests used: 2" in result.stdout

        assert route1.call_count == 1
        assert route2.call_count == 1

        # Check database isolation
        expected_db_path = (temp_config.parent / "test.db").resolve()
        assert "Database path:" in result.stdout
        assert str(expected_db_path) in result.stdout

        # Verify it exists under tmp_path and data/lead_finder.db is untouched
        assert expected_db_path.exists()


def test_collect_caching(temp_config: Path, mock_env: None) -> None:
    """11. Cache hit. 12. Cache expiration. 13. --force-refresh. 14. Cached not counted as live."""
    db_path = temp_config.parent / "test.db"
    db = init_database(db_path)

    cache_key_plumbers = build_places_cache_key(
        query="plumbers in Manchester, UK",
        location="Manchester, UK",
        field_mask=FIELD_MASK,
        page_token=None,
    )
    expires = (datetime.now(tz=UTC) + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    db.save_cached_api_response(
        cache_key_plumbers, "searchText", json.dumps({"places": [{"id": "P1"}]}), expires
    )

    cache_key_elec = build_places_cache_key(
        query="electricians in Manchester, UK",
        location="Manchester, UK",
        field_mask=FIELD_MASK,
        page_token=None,
    )
    expired_date = (datetime.now(tz=UTC) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    db.save_cached_api_response(
        cache_key_elec, "searchText", json.dumps({"places": [{"id": "E_OLD"}]}), expired_date
    )

    with respx.mock:
        route_elec = respx.post(
            PLACES_API_URL, json__textQuery="electricians in Manchester, UK"
        ).mock(return_value=httpx.Response(200, json={"places": [{"id": "E1"}]}))

        result = runner.invoke(app, ["collect", "-c", str(temp_config)])
        assert result.exit_code == 0

        assert "Live API requests used: 1" in result.stdout
        assert "Cached responses used: 1" in result.stdout
        assert route_elec.call_count == 1

        route_plumbers = respx.post(
            PLACES_API_URL, json__textQuery="plumbers in Manchester, UK"
        ).mock(return_value=httpx.Response(200, json={"places": [{"id": "P1_NEW"}]}))

        result_force = runner.invoke(app, ["collect", "-c", str(temp_config), "--force-refresh"])
        assert result_force.exit_code == 0
        assert "Live API requests used: 2" in result_force.stdout
        assert route_plumbers.call_count == 1


def test_collect_duplicate_business_across_queries(temp_config: Path, mock_env: None) -> None:
    """32. Same business discovered by multiple queries."""
    with respx.mock:
        respx.post(PLACES_API_URL, json__textQuery="plumbers in Manchester, UK").mock(
            return_value=httpx.Response(200, json={"places": [{"id": "P1"}]})
        )

        respx.post(PLACES_API_URL, json__textQuery="electricians in Manchester, UK").mock(
            return_value=httpx.Response(200, json={"places": [{"id": "P1"}]})
        )

        result = runner.invoke(app, ["collect", "-c", str(temp_config)])
        assert result.exit_code == 0

        assert "Unique businesses saved: 1" in result.stdout
        assert "Duplicates merged: 1" in result.stdout


def test_logging_handlers_not_closed(temp_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that Typer's stream handling doesn't leave closed loggers."""
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)

    # Run a CLI command that sets up logging
    result = runner.invoke(app, ["validate-config", "-c", str(temp_config)])
    assert result.exit_code == 0

    # Try logging afterwards - if handlers were improperly tied to Typer's transient streams,
    # this will raise ValueError: I/O operation on closed file
    logger = logging.getLogger("lead_finder")
    logger.info("This should not crash")
