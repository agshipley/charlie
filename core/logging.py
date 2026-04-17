"""
Structured logging foundation for Charlie.

Usage:
    from core.logging import get_logger
    log = get_logger(__name__)
    log.info("ingestion_complete", signal_count=42, run_date="2026-04-17")
    log.error("agent_failed", **error_context(exc))

All log lines are JSON objects written to data/logs/app.log and echoed
to stderr (captured by Railway's log viewer).

Log level defaults to INFO. Override with LOG_LEVEL env var.
"""

import logging
import logging.handlers
import os
import sys
import traceback

import structlog

from .config import config

_configured = False


def configure_logging() -> None:
    """
    Configure structlog once per process. Safe to call multiple times —
    subsequent calls are no-ops.
    """
    global _configured
    if _configured:
        return
    _configured = True

    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    # Ensure log directory exists
    log_dir = config.data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "app.log"

    # stdlib root logger: two handlers — file (JSON) and stderr (JSON)
    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers.clear()

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(log_level)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(log_level)

    for handler in (file_handler, stderr_handler):
        handler.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(handler)

    # Silence noisy third-party loggers
    for noisy in ("werkzeug", "anthropic", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a configured structlog logger bound to the given name."""
    return structlog.get_logger(name)


def error_context(exc: Exception) -> dict:
    """
    Return a dict of exception fields suitable for passing as kwargs to
    a log call.

    Example:
        log.error("agent_failed", **error_context(exc))
    """
    tb_lines = traceback.format_tb(exc.__traceback__)
    # Keep last 20 lines to avoid bloating the log entry
    truncated = "".join(tb_lines[-20:]).strip()
    return {
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
        "traceback": truncated,
    }
