"""File-based diagnostics logger.

The application can write a rolling log file to ``%APPDATA%/TapoViewer/logs``
so the user can grab it when something goes wrong. Logging is opt-in and
controlled from the Settings dialog (and the loaded :class:`Settings`):

* ``logging_enabled=False`` → no file handler is attached; calls to
  :func:`get_logger` still return a usable logger that simply discards
  output (root level WARNING goes to stderr by default).
* ``logging_enabled=True`` → a rotating file handler is attached at the
  configured ``log_level`` (DEBUG / INFO / WARNING / ERROR).

The configuration is global because Python's ``logging`` module is global;
:func:`configure_logging` is idempotent and can be called whenever the
user changes settings.
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


_FILE_HANDLER_NAME = "tapoviewer_file_handler"
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


def log_dir() -> Path:
    """Return the directory the log file lives in (created on demand)."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    path = Path(base) / "TapoViewer" / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_file_path() -> Path:
    return log_dir() / "tapoviewer.log"


def _named_handler(logger: logging.Logger,
                   name: str) -> Optional[logging.Handler]:
    for h in logger.handlers:
        if getattr(h, "name", None) == name:
            return h
    return None


def configure_logging(enabled: bool, level: str = "INFO") -> None:
    """Attach or detach the file handler based on the user's preference."""
    root = logging.getLogger("tapoviewer")
    root.propagate = False
    # Map the human-readable level. Default to INFO if it's something exotic.
    level_value = getattr(logging, level.upper(), logging.INFO)
    root.setLevel(level_value if enabled else logging.WARNING)

    existing = _named_handler(root, _FILE_HANDLER_NAME)
    if not enabled:
        if existing is not None:
            root.removeHandler(existing)
            existing.close()
        return

    if existing is None:
        try:
            handler = RotatingFileHandler(
                log_file_path(),
                maxBytes=512 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
        except OSError:
            # Disk full / permission denied — fall back silently.
            return
        handler.name = _FILE_HANDLER_NAME
        handler.setFormatter(logging.Formatter(_LOG_FORMAT, _LOG_DATEFMT))
        handler.setLevel(level_value)
        root.addHandler(handler)
    else:
        existing.setLevel(level_value)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the application's namespace."""
    if name.startswith("tapoviewer"):
        return logging.getLogger(name)
    return logging.getLogger(f"tapoviewer.{name}")
