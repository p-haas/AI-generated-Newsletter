"""Logging utilities configured for structured logging across the project."""

from __future__ import annotations

import logging
from typing import Optional

import structlog


def setup_logging(level: int = logging.INFO, timestamper: Optional[str] = "iso") -> None:
    """Configure structlog and standard logging for the application.

    This function is idempotent – calling it multiple times is safe. The
    configuration ensures that both the standard logging module and structlog
    share the same formatting.
    """

    if getattr(setup_logging, "_configured", False):  # type: ignore[attr-defined]
        return

    processors = [
        structlog.processors.TimeStamper(fmt="ISO", utc=True)
        if timestamper == "iso"
        else structlog.processors.TimeStamper(fmt="unix", utc=True),
        structlog.stdlib.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ]

    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(level=level)

    setup_logging._configured = True  # type: ignore[attr-defined]
