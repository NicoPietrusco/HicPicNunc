"""Logging setup (loguru)."""

import sys

from loguru import logger

from .settings import settings

LOG_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | "
    "<level>{level:<8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - {message}"
)


def setup_logger(level: str = "INFO") -> None:
    """
    Log to stderr when there is one, and to a file in the app data folder for desktop builds.

    Windowed desktop builds (PyInstaller console=False on Windows) have sys.stderr set to
    None, and the log file is then the only place errors end up.
    """
    logger.remove()
    if sys.stderr is not None:
        logger.add(sys.stderr, format=LOG_FORMAT, level=level, colorize=True)
    if sys.stderr is None or getattr(sys, "frozen", False):
        logger.add(
            settings.log_path,
            format=LOG_FORMAT,
            level=level,
            colorize=False,
            rotation="5 MB",
            retention=3,
            encoding="utf-8",
        )


def get_logger(name: str = "hicpicnunc"):
    """Get a logger instance for a specific module."""
    return logger.bind(name=name)
