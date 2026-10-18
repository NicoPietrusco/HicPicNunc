"""Tests for hicpicnunc.core.jobs."""

from __future__ import annotations

import io
import os
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hicpicnunc.core.jobs import (
    ZIP_CHUNK_SIZE,
    get_job_dir,
    is_image_file,
    is_video_file,
    iter_job_zip,
    list_job_files,
    new_job,
    prune_expired_jobs,
    resolve_job_file,
    set_file_date,
    staged_file,
)


@pytest.mark.parametrize(
    ("name", "expected"), [("a.JPG", True), ("b.heic", True), ("c.gif", False)]
)
def test_is_image_file(name: str, expected: bool) -> None:
    assert is_image_file(Path(name)) is expected


def test_new_job_is_found_again_by_id(data_dir: Path) -> None:
    job_id, job_dir = new_job()

    assert get_job_dir(job_id) == job_dir
    assert job_dir.parent == data_dir / "data" / "outputs"


@pytest.mark.parametrize("job_id", ["..", "not-a-uuid", "00000000-0000-0000-0000-000000000000"])
def test_unknown_or_malformed_job_ids_are_rejected(data_dir: Path, job_id: str) -> None:
    assert get_job_dir(job_id) is None


def test_staged_file_is_outside_the_job_and_deleted_afterwards(data_dir: Path) -> None:
    job_id, job_dir = new_job()

    with staged_file(job_id, 3, "IMG.jpg") as path:
        path.write_bytes(b"x")
        assert path.name == f"{job_id}_3.jpg"  # the output name is chosen separately
        assert job_dir not in path.parents

    assert not path.exists()


def test_staged_file_is_deleted_even_when_processing_fails(data_dir: Path) -> None:
    with pytest.raises(RuntimeError), staged_file("job", 0, "IMG.jpg") as path:
        path.write_bytes(b"x")
        raise RuntimeError("processing failed")

    assert not path.exists()


def _age(path: Path, hours: float) -> None:
    then = time.time() - hours * 3600
    os.utime(path, (then, then))


def test_prune_removes_only_expired_job_entries(data_dir: Path) -> None:
    old_id, old_dir = new_job()
    fresh_id, fresh_dir = new_job()
    uploads = data_dir / "data" / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    leftover = uploads / f"{old_id}_0_IMG.jpg"
    leftover.write_bytes(b"x")
    stranger = data_dir / "data" / "outputs" / "notes"
    stranger.mkdir()
    for path in (old_dir, leftover, stranger):
        _age(path, 48)

    assert prune_expired_jobs(max_age_hours=24) == 2
    assert not old_dir.exists() and not leftover.exists()
    assert fresh_dir.is_dir()
    assert stranger.is_dir()  # not named after a job: never deleted


def test_retention_period_comes_from_the_environment(data_dir: Path, monkeypatch) -> None:
    _, job_dir = new_job()
    _age(job_dir, 3)
    monkeypatch.setenv("JOB_RETENTION_HOURS", "2")

    assert prune_expired_jobs() == 1


@pytest.mark.parametrize(
    "rel", ["../secret.txt", "a/../../b", "a\0b", "", "a:b.jpg", "CON.jpg", ".hidden"]
)
def test_resolve_job_file_rejects_escapes_and_unsafe_names(tmp_path: Path, rel: str) -> None:
    assert resolve_job_file(tmp_path, rel) is None


def test_resolve_job_file_accepts_nested_paths(tmp_path: Path) -> None:
    root = tmp_path.resolve()

    assert resolve_job_file(tmp_path, "trip/day1/IMG.jpg") == root / "trip/day1/IMG.jpg"
    assert (
        resolve_job_file(tmp_path, "Perù 2019/東京タワー.jpg") == root / "Perù 2019/東京タワー.jpg"
    )
    assert resolve_job_file(tmp_path, "/etc/passwd") == root / "etc/passwd"  # stays inside


def test_zip_contains_every_file_with_its_capture_date(tmp_path: Path) -> None:
    (tmp_path / "trip").mkdir()
    for rel, when in [
        ("a.jpg", datetime(2019, 1, 2, 3, 4, 6)),
        ("trip/b.jpg", datetime(1975, 6, 1)),
    ]:
        path = tmp_path / rel
        path.write_bytes(b"x")
        os.utime(path, (when.timestamp(), when.timestamp()))

    archive = zipfile.ZipFile(io.BytesIO(b"".join(iter_job_zip(tmp_path))))

    assert list_job_files(tmp_path) == ["a.jpg", "trip/b.jpg"]
    assert archive.getinfo("a.jpg").date_time == (2019, 1, 2, 3, 4, 6)
    assert archive.getinfo("trip/b.jpg").date_time[0] == 1980  # ZIP's earliest date


def test_zip_stores_files_unchanged(tmp_path: Path) -> None:
    content = os.urandom(3000)  # like a JPEG or video: incompressible
    (tmp_path / "clip.mp4").write_bytes(content)

    archive = zipfile.ZipFile(io.BytesIO(b"".join(iter_job_zip(tmp_path))))

    assert archive.getinfo("clip.mp4").compress_type == zipfile.ZIP_STORED
    assert archive.read("clip.mp4") == content
    assert archive.testzip() is None


def test_zip_streams_large_jobs_in_bounded_chunks(tmp_path: Path) -> None:
    # 99 videos used to be deflated into RAM before a single byte was sent.
    for i in range(3):
        (tmp_path / f"VID_{i}.mp4").write_bytes(os.urandom(ZIP_CHUNK_SIZE * 2 + 123))

    chunks = iter_job_zip(tmp_path)
    first = next(chunks)
    rest = list(chunks)

    assert first  # data flows before the whole archive is built
    assert max(len(c) for c in [first, *rest]) <= ZIP_CHUNK_SIZE + 1024
    archive = zipfile.ZipFile(io.BytesIO(first + b"".join(rest)))
    assert sorted(archive.namelist()) == ["VID_0.mp4", "VID_1.mp4", "VID_2.mp4"]
    assert archive.testzip() is None


def test_zip_with_non_ascii_names_extracts_unchanged(tmp_path: Path) -> None:
    job, out = tmp_path / "job", tmp_path / "out"
    names = ["Perù 2019 – Machu Picchu.jpg", "東京タワー.jpg", "Vacanze 2019/Festa 🎉.jpg"]
    for name in names:
        (job / name).parent.mkdir(parents=True, exist_ok=True)
        (job / name).write_bytes(b"x")

    zipfile.ZipFile(io.BytesIO(b"".join(iter_job_zip(job)))).extractall(out)

    assert sorted(p.relative_to(out).as_posix() for p in out.rglob("*.jpg")) == sorted(names)


def test_empty_job_zip_is_valid(tmp_path: Path) -> None:
    assert zipfile.ZipFile(io.BytesIO(b"".join(iter_job_zip(tmp_path)))).namelist() == []


@pytest.mark.parametrize(
    "value",
    [
        "2022-08-05T14:03:22Z",
        "2022-08-05T14:03:22.123Z",
        "2022-08-05T14:03:22.123456789Z",  # Google may send nanoseconds
        "2022-08-05T16:03:22+02:00",
    ],
)
def test_set_file_date_accepts_google_create_times(tmp_path: Path, value: str) -> None:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"x")

    assert set_file_date(path, value)
    expected = datetime(2022, 8, 5, 14, 3, 22, tzinfo=UTC).timestamp()
    assert abs(os.path.getmtime(path) - expected) < 1


@pytest.mark.parametrize("value", [None, "", "yesterday"])
def test_set_file_date_ignores_missing_or_invalid_values(tmp_path: Path, value) -> None:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"x")
    before = os.path.getmtime(path)

    assert not set_file_date(path, value)
    assert os.path.getmtime(path) == before


@pytest.mark.parametrize(
    ("name", "expected"), [("clip.MOV", True), ("clip.mp4", True), ("a.jpg", False)]
)
def test_is_video_file(name: str, expected: bool) -> None:
    assert is_video_file(Path(name)) is expected
