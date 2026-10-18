#!/usr/bin/env python3
"""
Start a PyInstaller desktop bundle and check it serves the UI and exports a photo.

Usage: python scripts/smoke_test_bundle.py dist

Runs the real executable (windowed, so on Windows it has no console), uploads a JPEG with
an EXIF capture date and checks the ZIP entry carries that date. On failure, prints the
app's log file, since a windowed app has nowhere else to report errors.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path

import piexif
from PIL import Image

PORT = 5099
BASE = f"http://127.0.0.1:{PORT}"
STARTUP_TIMEOUT_S = 90


def find_executable(dist: Path) -> Path:
    for candidate in (
        dist / "Hic Pic Nunc.app" / "Contents" / "MacOS" / "Hic Pic Nunc",
        dist / "Hic Pic Nunc" / "Hic Pic Nunc.exe",
        dist / "Hic Pic Nunc" / "Hic Pic Nunc",
    ):
        if candidate.is_file():
            return candidate
    raise SystemExit(f"No desktop bundle found in {dist}")


def wait_until_up(proc: subprocess.Popen) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"App exited during startup with code {proc.returncode}")
        try:
            with urllib.request.urlopen(f"{BASE}/", timeout=2) as resp:
                if resp.status == 200:
                    return
        except OSError:
            time.sleep(1)
    raise RuntimeError(f"App did not answer on {BASE} within {STARTUP_TIMEOUT_S}s")


def upload_photo() -> str:
    buf = io.BytesIO()
    exif = piexif.dump({"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2019:05:04 12:00:00"}})
    Image.new("RGB", (32, 24), "teal").save(buf, "JPEG", exif=exif)
    boundary = uuid.uuid4().hex
    body = b"".join(
        [
            f'--{boundary}\r\nContent-Disposition: form-data; name="include_json"\r\n\r\nfalse\r\n'.encode(),
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="smoke.jpg"\r\n'.encode(),
            b"Content-Type: image/jpeg\r\n\r\n" + buf.getvalue() + b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    req = urllib.request.Request(
        f"{BASE}/upload",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.load(resp)
    if not result.get("ok"):
        raise RuntimeError(f"Upload failed: {result}")
    return result["job_id"]


def check_zip(job_id: str) -> None:
    with urllib.request.urlopen(f"{BASE}/job/{job_id}/download-all", timeout=30) as resp:
        archive = zipfile.ZipFile(io.BytesIO(resp.read()))
    info = archive.getinfo("smoke.jpg")
    if info.date_time[:3] != (2019, 5, 4):
        raise RuntimeError(f"ZIP entry is dated {info.date_time}, expected the EXIF date")


def main() -> None:
    executable = find_executable(Path(sys.argv[1] if len(sys.argv) > 1 else "dist"))
    data_dir = Path(tempfile.mkdtemp(prefix="pms-smoke-"))
    env = {**os.environ, "PORT": str(PORT), "HICPICNUNC_DATA_DIR": str(data_dir)}
    if os.name != "nt":
        env["BROWSER"] = "true"  # don't open a browser on CI
    print(f"Starting {executable}")
    proc = subprocess.Popen([str(executable)], env=env)
    try:
        wait_until_up(proc)
        for path in ("/static/css/app.css", "/static/js/picker.js"):
            urllib.request.urlopen(f"{BASE}{path}", timeout=10).close()
        check_zip(upload_photo())
        print("Smoke test passed: UI served, photo exported with its capture date.")
    except Exception as e:
        log = data_dir / "logs" / "hicpicnunc.log"
        print(f"Smoke test FAILED: {e}", file=sys.stderr)
        print(
            log.read_text(encoding="utf-8") if log.is_file() else "(no log file)", file=sys.stderr
        )
        raise SystemExit(1) from e
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
