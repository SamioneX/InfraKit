"""Structured logger for InfraKit.

In TTY environments, emits human-readable Rich output via the console.
In non-TTY environments (CI, piped), emits JSON lines to stderr.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from rich.console import Console
from rich.logging import RichHandler

# Shared Rich console — imported by output helpers too
console = Console(stderr=True)


def _is_tty() -> bool:
    return sys.stderr.isatty()


def get_logger(name: str = "infrakit") -> logging.Logger:
    """Return a configured logger for *name*.

    Call once per module:  ``logger = get_logger(__name__)``
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(logging.DEBUG)

    if _is_tty():
        handler: logging.Handler = RichHandler(
            console=console,
            show_time=False,
            show_path=False,
            markup=True,
            rich_tracebacks=True,
        )
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)
    else:
        handler = _JsonHandler()
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)

    logger.propagate = False
    return logger


class _JsonHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Emits one JSON object per log record to stderr."""

    def __init__(self) -> None:
        super().__init__(stream=sys.stderr)

    def emit(self, record: logging.LogRecord) -> None:
        payload: dict[str, Any] = {
            "ts": datetime.now(tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        try:
            self.stream.write(json.dumps(payload) + "\n")
            self.stream.flush()
        except Exception:  # noqa: BLE001
            self.handleError(record)
