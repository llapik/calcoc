"""Logging setup for AI PC Repair & Optimizer."""

import logging
import sys
from pathlib import Path


_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging(log_dir: str | Path | None = None, level: int = logging.INFO) -> None:
    """Configure root logger with console and optional file output."""
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger()
    root.setLevel(level)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
    root.addHandler(console)

    # File handler (if log_dir provided)
    if log_dir:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_path / "calcoc.log", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
        root.addHandler(fh)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger with the given *name*."""
    return logging.getLogger(f"calcoc.{name}")
