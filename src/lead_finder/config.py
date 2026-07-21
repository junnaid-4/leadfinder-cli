"""Application configuration loaded from YAML and environment variables."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProjectConfig(BaseModel):
    """Top-level project metadata."""

    name: str = Field(min_length=1)


class SearchConfig(BaseModel):
    """Google Places search settings."""

    location: str = Field(min_length=1)
    queries: list[str] = Field(min_length=1)
    max_results_per_query: int = Field(default=50, ge=1, le=500)
    max_total_results: int = Field(default=150, ge=1, le=5000)
    max_api_requests: int = Field(default=100, ge=1, le=10000)

    @field_validator("queries")
    @classmethod
    def validate_queries(cls, value: list[str]) -> list[str]:
        cleaned = [query.strip() for query in value if query.strip()]
        if not cleaned:
            msg = "At least one non-empty search query is required."
            raise ValueError(msg)
        return cleaned

    @model_validator(mode="after")
    def validate_result_limits(self) -> SearchConfig:
        if self.max_total_results < self.max_results_per_query:
            msg = (
                "max_total_results must be greater than or equal to "
                "max_results_per_query."
            )
            raise ValueError(msg)
        return self


class FiltersConfig(BaseModel):
    """Business filtering rules."""

    operational_only: bool = True
    minimum_rating: float = Field(default=0.0, ge=0.0, le=5.0)
    minimum_review_count: int = Field(default=0, ge=0)


class WebsiteCheckConfig(BaseModel):
    """Website HTTP check settings."""

    enabled: bool = True
    concurrency: int = Field(default=10, ge=1, le=50)
    connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    read_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    retries: int = Field(default=1, ge=0, le=5)
    follow_redirects: bool = True
    max_redirects: int = Field(default=10, ge=0, le=20)
    max_response_size_mb: float = Field(default=5.0, gt=0, le=50)
    important_pages_enabled: bool = False
    max_important_pages: int = Field(default=5, ge=1, le=5)

    @property
    def max_response_size_bytes(self) -> int:
        return int(self.max_response_size_mb * 1024 * 1024)


class CacheConfig(BaseModel):
    """Cache TTL settings."""

    places_ttl_days: int = Field(default=30, ge=1, le=365)
    website_check_ttl_days: int = Field(default=7, ge=1, le=90)


class OutputConfig(BaseModel):
    """CSV and output directory settings."""

    directory: str = "output"
    include_working_websites: bool = True


class DatabaseConfig(BaseModel):
    """SQLite database settings."""

    path: str = "data/lead_finder.db"


class LoggingConfigSection(BaseModel):
    """Logging settings from YAML."""

    level: str = "INFO"
    directory: str = "logs"
    console: bool = True
    file: bool = True

    @field_validator("level")
    @classmethod
    def validate_level(cls, value: str) -> str:
        normalized = value.upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if normalized not in allowed:
            msg = f"Invalid log level: {value}. Must be one of {sorted(allowed)}."
            raise ValueError(msg)
        return normalized


class AppConfig(BaseModel):
    """Full application configuration from YAML."""

    project: ProjectConfig
    search: SearchConfig
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    website_check: WebsiteCheckConfig = Field(default_factory=WebsiteCheckConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    logging: LoggingConfigSection = Field(default_factory=LoggingConfigSection)

    def output_directory(self) -> Path:
        return Path(self.output.directory)

    def database_path(self) -> Path:
        return Path(self.database.path)

    def logs_directory(self) -> Path:
        return Path(self.logging.directory)


class EnvSettings(BaseSettings):
    """Environment-backed settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    google_maps_api_key: str | None = Field(default=None, alias="GOOGLE_MAPS_API_KEY")

    def require_api_key(self) -> str:
        if not self.google_maps_api_key or self.google_maps_api_key.strip() == "":
            msg = (
                "GOOGLE_MAPS_API_KEY is not set. "
                "Copy .env.example to .env and add your API key."
            )
            raise ValueError(msg)
        if self.google_maps_api_key == "your_api_key_here":
            msg = "GOOGLE_MAPS_API_KEY is still set to the placeholder value."
            raise ValueError(msg)
        return self.google_maps_api_key


def load_yaml_config(path: Path) -> dict[str, Any]:
    """Load and parse a YAML configuration file."""
    if not path.exists():
        msg = f"Configuration file not found: {path}"
        raise FileNotFoundError(msg)
    if not path.is_file():
        msg = f"Configuration path is not a file: {path}"
        raise ValueError(msg)

    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    if raw is None:
        msg = f"Configuration file is empty: {path}"
        raise ValueError(msg)
    if not isinstance(raw, dict):
        msg = f"Configuration root must be a mapping: {path}"
        raise ValueError(msg)
    return raw


def load_config(path: Path) -> AppConfig:
    """Load and validate application configuration from a YAML file."""
    raw = load_yaml_config(path)
    return AppConfig.model_validate(raw)
