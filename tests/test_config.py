"""Tests for configuration loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from lead_finder.config import AppConfig, EnvSettings, load_config


def _write_config(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


@pytest.fixture
def valid_config_data() -> dict:
    return {
        "project": {"name": "Test Project"},
        "search": {
            "location": "Manchester, UK",
            "queries": ["electricians"],
            "max_results_per_query": 20,
            "max_total_results": 50,
            "max_api_requests": 30,
        },
        "filters": {
            "operational_only": True,
            "minimum_rating": 0,
            "minimum_review_count": 0,
        },
        "website_check": {
            "enabled": True,
            "concurrency": 5,
            "connect_timeout_seconds": 5,
            "read_timeout_seconds": 10,
            "retries": 1,
            "follow_redirects": True,
            "max_redirects": 10,
            "max_response_size_mb": 5,
            "important_pages_enabled": False,
            "max_important_pages": 5,
        },
        "cache": {"places_ttl_days": 30, "website_check_ttl_days": 7},
        "output": {"directory": "output", "include_working_websites": True},
        "database": {"path": "data/test.db"},
        "logging": {
            "level": "INFO",
            "directory": "logs",
            "console": True,
            "file": False,
        },
    }


def test_load_valid_config(tmp_path: Path, valid_config_data: dict) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, valid_config_data)

    config = load_config(config_path)

    assert config.project.name == "Test Project"
    assert config.search.location == "Manchester, UK"
    assert config.search.queries == ["electricians"]
    assert config.database.path == "data/test.db"
    assert config.website_check.max_response_size_bytes == 5 * 1024 * 1024


def test_rejects_empty_queries(tmp_path: Path, valid_config_data: dict) -> None:
    valid_config_data["search"]["queries"] = ["  ", ""]
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, valid_config_data)

    with pytest.raises(ValidationError, match="non-empty search query"):
        load_config(config_path)


def test_rejects_total_results_below_per_query(
    tmp_path: Path,
    valid_config_data: dict,
) -> None:
    valid_config_data["search"]["max_results_per_query"] = 100
    valid_config_data["search"]["max_total_results"] = 50
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, valid_config_data)

    with pytest.raises(ValidationError, match="max_total_results"):
        load_config(config_path)


def test_rejects_invalid_log_level(tmp_path: Path, valid_config_data: dict) -> None:
    valid_config_data["logging"]["level"] = "VERBOSE"
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, valid_config_data)

    with pytest.raises(ValidationError, match="Invalid log level"):
        load_config(config_path)


def test_rejects_missing_config_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.yaml")


def test_rejects_empty_config_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        load_config(config_path)


def test_env_settings_require_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    settings = EnvSettings(_env_file=None)

    with pytest.raises(ValueError, match="GOOGLE_MAPS_API_KEY is not set"):
        settings.require_api_key()


def test_env_settings_reject_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "your_api_key_here")
    settings = EnvSettings(_env_file=None)

    with pytest.raises(ValueError, match="placeholder"):
        settings.require_api_key()


def test_env_settings_accept_valid_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key-value")
    settings = EnvSettings(_env_file=None)

    assert settings.require_api_key() == "test-key-value"


def test_app_config_path_helpers(valid_config_data: dict) -> None:
    config = AppConfig.model_validate(valid_config_data)

    assert config.output_directory() == Path("output")
    assert config.database_path() == Path("data/test.db").resolve()
    assert config.logs_directory() == Path("logs")
