"""
Centralized logging setup for Eco-Loop using loguru.
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

_configured = False


def setup_logging(level: str = "INFO", log_file: str | None = None) -> None:
    """Configure loguru logger for the application."""
    global _configured
    if _configured:
        return

    # Remove default handler
    logger.remove()

    # Ensure stderr can handle UTF-8 on Windows
    import io

    _stderr = (
        io.TextIOWrapper(
            sys.stderr.buffer if hasattr(sys.stderr, "buffer") else sys.stderr,
            encoding="utf-8",
            errors="replace",
            line_buffering=True,
        )
        if hasattr(sys.stderr, "buffer")
        else sys.stderr
    )

    logger.add(
        _stderr,
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # File handler
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            str(log_path),
            level=level,
            rotation="10 MB",
            retention="30 days",
            compression="zip",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
        )

    _configured = True


def get_logger(name: str):
    """Return a contextual loguru logger bound to a module name."""
    return logger.bind(name=name)
