"""
Export jobs: each job is a folder of processed photos under data/outputs/<uuid>.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import time
import uuid
import zipfile
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from ..log import get_logger
from ..settings import settings
from .filenames import is_safe_filename

logger = get_logger(__name__)


def is_image_file(path: Path) -> bool:
    """True when the extension is one of the supported image formats."""
    return path.suffix.lower() in settings.SUPPORTED_FORMATS


def is_video_file(path: Path) -> bool:
    """True when the extension is one of the exported video formats."""
    return path.suffix.lower() in settings.VIDEO_FORMATS


_FRACTION_RE = re.compile(r"(\.\d{6})\d+")


def set_file_date(path: Path, rfc3339: str | None) -> bool:
    """
    Set path's modification time from an RFC 3339 timestamp such as Google's createTime
    ("2022-08-05T14:03:22.123456789Z"). Returns False when the value is missing or invalid.
    """
    if not rfc3339:
        return False
    # Google may send up to 9 fractional digits; datetime accepts at most 6.
    text = _FRACTION_RE.sub(r"\1", rfc3339.strip()).replace("Z", "+00:00")
    try:
        timestamp = datetime.fromisoformat(text).timestamp()
        os.utime(path, (timestamp, timestamp))
    except (ValueError, OSError) as e:
        logger.warning("Could not set file date of {} from {!r}: {}", path.name, rfc3339, e)
        return False
    return True


def new_job() -> tuple[str, Path]:
    """Create an empty output folder for a new job (and drop expired ones)."""
    prune_expired_jobs()
    job_id = str(uuid.uuid4())
    job_dir = settings.web_output_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_id, job_dir


def get_job_dir(job_id: str) -> Path | None:
    """Output folder of an existing job, or None for unknown or malformed ids."""
    try:
        uuid.UUID(job_id)
    except ValueError:
        return None
    job_dir = settings.web_output_dir / job_id
    return job_dir if job_dir.is_dir() else None


@contextmanager
def staged_file(job_id: str, index: int, filename: str) -> Generator[Path, None, None]:
    """
    Path for an incoming file while it is processed; the file is deleted afterwards.

    Only filename's extension is kept: the output name is chosen separately.
    """
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    path = settings.upload_dir / f"{job_id}_{index}{Path(filename).suffix}"
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def _is_job_id(name: str) -> bool:
    try:
        uuid.UUID(name[:36])
    except ValueError:
        return False
    return True


def prune_expired_jobs(max_age_hours: float | None = None) -> int:
    """
    Delete job outputs (and leftover staged uploads) older than the retention period.

    Only entries named after a job id are touched. Returns how many were removed.
    """
    hours = settings.job_retention_hours if max_age_hours is None else max_age_hours
    cutoff = time.time() - hours * 3600
    removed = 0
    for folder in (settings.web_output_dir, settings.upload_dir):
        if not folder.is_dir():
            continue
        for entry in folder.iterdir():
            try:
                if not _is_job_id(entry.name) or entry.stat().st_mtime >= cutoff:
                    continue
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
                removed += 1
            except OSError as e:
                logger.warning("Could not remove expired {}: {}", entry.name, e)
    if removed:
        logger.info("Removed {} expired job file(s)", removed)
    return removed


def list_job_files(job_dir: Path) -> list[str]:
    """Relative POSIX paths of every file in the job, sorted."""
    return sorted(p.relative_to(job_dir).as_posix() for p in job_dir.rglob("*") if p.is_file())


def resolve_job_file(job_dir: Path, rel: str) -> Path | None:
    """Resolve rel to a path under job_dir, or None if invalid or it escapes."""
    rel = rel.replace("\\", "/").strip().lstrip("/")
    if not rel or "\0" in rel:
        return None
    parts = rel.split("/")
    if any(p in (".", "..") or not is_safe_filename(p) for p in parts):
        return None
    try:
        root = job_dir.resolve()
        candidate = root.joinpath(*parts).resolve()
        candidate.relative_to(root)
    except (ValueError, OSError):
        return None
    return candidate


class _ChunkSink(io.RawIOBase):
    """Write-only, unseekable buffer that zipfile streams into; drained after each write."""

    def __init__(self) -> None:
        self._chunks: list[bytes] = []

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:  # type: ignore[override]
        self._chunks.append(bytes(data))
        return len(data)

    def drain(self) -> bytes:
        data = b"".join(self._chunks)
        self._chunks.clear()
        return data


ZIP_CHUNK_SIZE = 1 << 20


def iter_job_zip(job_dir: Path) -> Iterator[bytes]:
    """
    Stream a ZIP of every job file, a chunk at a time, keeping each file's mtime.

    Entries are stored, not deflated: photos and videos are already compressed, and
    deflating gigabytes of video made users wait minutes before the download started.
    Memory stays around ZIP_CHUNK_SIZE whatever the job size.
    """
    sink = _ChunkSink()
    # Capture dates before 1980 are clamped instead of failing the whole download.
    with zipfile.ZipFile(sink, "w", zipfile.ZIP_STORED, strict_timestamps=False) as zf:
        for rel in list_job_files(job_dir):
            path = job_dir / rel
            info = zipfile.ZipInfo.from_file(path, arcname=rel, strict_timestamps=False)
            with path.open("rb") as src, zf.open(info, "w") as dest:
                while block := src.read(ZIP_CHUNK_SIZE):
                    dest.write(block)
                    yield sink.drain()
            yield sink.drain()
    yield sink.drain()  # central directory
