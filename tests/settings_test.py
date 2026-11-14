"""Tests for hicpicnunc.settings."""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

from hicpicnunc.settings import settings


@pytest.fixture
def frozen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Simulate a PyInstaller bundle with a temp home directory."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("HICPICNUNC_DATA_DIR", raising=False)
    monkeypatch.delenv("GPHOTOMETASYNC_DATA_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def test_data_dir_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HICPICNUNC_DATA_DIR", str(tmp_path))

    assert settings.data_dir == tmp_path / "data"
    assert settings.web_output_dir == tmp_path / "data" / "outputs"
    assert settings.google_token_path == tmp_path / "credentials" / "google_token.json"


def test_source_checkout_writes_next_to_the_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HICPICNUNC_DATA_DIR", raising=False)

    assert settings.app_data_dir == settings.resource_dir
    assert (settings.resource_dir / "pyproject.toml").is_file()


# (platform, data folder, folder before the rename), relative to the fake home
PLATFORM_DATA_DIRS = [
    pytest.param(
        (
            "darwin",
            "Library/Application Support/HicPicNunc",
            "Library/Application Support/GPhotoMetaSync",
        ),
        id="macos",
    ),
    pytest.param(("win32", "Local/HicPicNunc", "Local/GPhotoMetaSync"), id="windows"),
    pytest.param(("linux", "xdg/hicpicnunc", "xdg/gphotometasync"), id="linux"),
]


@pytest.fixture(params=PLATFORM_DATA_DIRS)
def platform_dirs(
    request: pytest.FixtureRequest, frozen: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    """Simulate each desktop platform; returns its (new, pre-rename) data folders."""
    platform, current, legacy = request.param
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setenv("LOCALAPPDATA", str(frozen / "Local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(frozen / "xdg"))
    return frozen / current, frozen / legacy


def test_a_fresh_install_uses_the_new_folder(platform_dirs: tuple[Path, Path]) -> None:
    current, legacy = platform_dirs

    assert settings.migrate_legacy_data_dir() is None
    assert settings.app_data_dir == current
    assert not legacy.exists()


def test_the_pre_rename_folder_is_moved_with_its_contents(
    platform_dirs: tuple[Path, Path],
) -> None:
    current, legacy = platform_dirs
    token = legacy / "credentials" / "google_token.json"
    token.parent.mkdir(parents=True)
    token.write_text('{"token": "kept"}')

    assert settings.app_data_dir == legacy  # until it is moved
    assert settings.migrate_legacy_data_dir() == current

    assert settings.app_data_dir == current
    assert settings.google_token_path.read_text() == '{"token": "kept"}'
    assert not legacy.exists()
    assert settings.migrate_legacy_data_dir() is None  # only once


def test_a_failed_rename_keeps_using_the_old_folder(
    platform_dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    current, legacy = platform_dirs
    legacy.mkdir(parents=True)

    def locked(self: Path, target: Path) -> Path:
        raise PermissionError("in use by another process")

    monkeypatch.setattr(Path, "rename", locked)

    with pytest.raises(PermissionError):
        settings.migrate_legacy_data_dir()
    assert settings.app_data_dir == legacy
    assert not current.exists()


def test_with_both_folders_the_old_one_is_left_alone(platform_dirs: tuple[Path, Path]) -> None:
    current, legacy = platform_dirs
    current.mkdir(parents=True)
    (legacy / "logs").mkdir(parents=True)

    assert settings.migrate_legacy_data_dir() is None
    assert settings.app_data_dir == current
    assert (legacy / "logs").is_dir()
    assert not (current / "logs").exists()


def test_an_override_is_never_migrated(
    platform_dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, legacy = platform_dirs
    legacy.mkdir(parents=True)
    monkeypatch.setenv("HICPICNUNC_DATA_DIR", str(tmp_path / "custom"))

    assert settings.migrate_legacy_data_dir() is None
    assert legacy.is_dir()


def test_running_from_source_is_never_migrated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HICPICNUNC_DATA_DIR", raising=False)
    monkeypatch.delenv("GPHOTOMETASYNC_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    assert settings.migrate_legacy_data_dir() is None


def test_secret_key_from_environment_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "from-env")

    assert settings.secret_key == "from-env"


def test_frozen_secret_key_is_generated_once_and_private(
    frozen: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("HICPICNUNC_DATA_DIR", str(frozen))

    first = settings.secret_key
    key_file = frozen / "state" / "flask_secret_key"

    assert len(first) >= 32
    assert settings.secret_key == first
    if sys.platform != "win32":  # Windows has no POSIX permission bits
        assert stat.S_IMODE(key_file.stat().st_mode) == 0o600


def test_job_retention_defaults_to_one_day(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JOB_RETENTION_HOURS", raising=False)

    assert settings.job_retention_hours == 24


def test_pre_rename_data_dir_variable_still_works(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("HICPICNUNC_DATA_DIR", raising=False)
    monkeypatch.setenv("GPHOTOMETASYNC_DATA_DIR", str(tmp_path))

    assert settings.app_data_dir == tmp_path


def test_only_desktop_builds_stop_on_their_own(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HICPICNUNC_KEEP_RUNNING", raising=False)

    assert settings.auto_exit is False
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert settings.auto_exit is True


def test_keep_running_turns_off_auto_exit(frozen: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HICPICNUNC_KEEP_RUNNING", "1")

    assert settings.auto_exit is False
