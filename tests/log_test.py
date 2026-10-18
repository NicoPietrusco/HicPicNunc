"""Tests for hicpicnunc.log."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from loguru import logger

from hicpicnunc.log import get_logger, setup_logger


@pytest.fixture(autouse=True)
def restore_loguru():
    yield
    logger.remove()
    setup_logger()


def _log_file(data_dir: Path) -> Path:
    return data_dir / "logs" / "hicpicnunc.log"


def test_windowed_builds_without_stderr_log_to_a_file(data_dir, monkeypatch) -> None:
    # PyInstaller console=False on Windows: sys.stderr is None.
    monkeypatch.setattr(sys, "stderr", None)

    setup_logger()
    get_logger("test").info("started without a console")
    logger.complete()

    assert "started without a console" in _log_file(data_dir).read_text(encoding="utf-8")


def test_frozen_builds_also_log_to_a_file(data_dir, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    setup_logger()
    get_logger("test").warning("visible in both")
    logger.complete()

    assert "visible in both" in _log_file(data_dir).read_text(encoding="utf-8")
    assert "visible in both" in capsys.readouterr().err


def test_source_runs_log_only_to_the_terminal(data_dir, capsys) -> None:
    setup_logger()
    get_logger("test").info("terminal only")

    assert "terminal only" in capsys.readouterr().err
    assert not _log_file(data_dir).exists()
