"""Logging setup for console and file output."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler

from lead_finder.config import AppConfig

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Patterns that may indicate secrets in log messages.
_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[=:]\s*\S+"),
    re.compile(r"AIza[0-9A-Za-z\-_]{20,}"),
)


class SecretRedactingFilter(logging.Filter):
    """Redact likely secrets from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = message
        for pattern in _SECRET_PATTERNS:
            redacted = pattern.sub("[REDACTED]", redacted)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def _resolve_log_level(level_name: str) -> int:
    return getattr(logging, level_name.upper(), logging.INFO)


def setup_logging(
    config: AppConfig,
    *,
    run_id: str | None = None,
) -> logging.Logger:
    """Configure root logging based on application config."""
    log_dir = config.logs_directory()
    log_dir.mkdir(parents=True, exist_ok=True)

    level = _resolve_log_level(config.logging.level)
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    secret_filter = SecretRedactingFilter()

    if config.logging.console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.addFilter(secret_filter)
        root_logger.addHandler(console_handler)

    if config.logging.file:
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
        suffix = f"_{run_id}" if run_id else ""
        log_file = log_dir / f"run_{timestamp}{suffix}.log"
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(secret_filter)
        root_logger.addHandler(file_handler)

    logger = logging.getLogger("lead_finder")
    logger.debug("Logging configured at level %s", config.logging.level)
    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger."""
    return logging.getLogger(f"lead_finder.{name}")
