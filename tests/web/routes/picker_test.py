"""Tests for hicpicnunc.web.routes.picker."""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import piexif
import pytest

from hicpicnunc.core.jobs import get_job_dir, list_job_files
from hicpicnunc.web import session as web_session
from hicpicnunc.web.routes import picker

GOOGLE_URL = "https://lh3.googleusercontent.com/item"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/create-session"),
        ("get", "/api/session-status"),
        ("get", "/api/list-selected"),
        ("post", "/api/process-google-batch"),
        ("get", f"/api/picker-image?url={GOOGLE_URL}"),
    ],
)
def test_endpoints_require_sign_in(client, method: str, path: str) -> None:
    assert getattr(client, method)(path).status_code == 401


@pytest.mark.parametrize(
    ("url", "status"),
    [("", 400), ("ftp://lh3.googleusercontent.com/x", 400), ("https://evil.example/x", 403)],
)
def test_picker_image_only_proxies_google_hosts(signed_in_client, url: str, status: int) -> None:
    assert signed_in_client.get(f"/api/picker-image?url={url}").status_code == status


def test_picker_image_proxies_the_bytes(signed_in_client, monkeypatch, fake_response) -> None:
    monkeypatch.setattr(
        picker.requests,
        "get",
        lambda url, **kw: fake_response(content=b"img", headers={"Content-Type": "image/webp"}),
    )

    resp = signed_in_client.get(f"/api/picker-image?url={GOOGLE_URL}")

    assert resp.data == b"img"
    assert resp.mimetype == "image/webp"


def test_create_session_stores_the_picker_session(signed_in_client, monkeypatch) -> None:
    monkeypatch.setattr(
        picker,
        "create_picker_session",
        lambda creds: {
            "id": "new",
            "pickerUri": "https://photos.google.com/x",
            "pollingConfig": {"pollInterval": "3s"},
        },
    )

    body = signed_in_client.post("/api/create-session").get_json()

    assert body == {
        "sessionId": "new",
        "pickerUri": "https://photos.google.com/x",
        "pollInterval": "3",
    }
    assert web_session.picker_sessions["test-sid"].picker_session_id == "new"


@pytest.mark.parametrize(("media_set", "status"), [(True, "ready"), (False, "pending")])
def test_session_status(signed_in_client, monkeypatch, media_set: bool, status: str) -> None:
    monkeypatch.setattr(
        picker, "get_picker_session", lambda creds, sid: {"mediaItemsSet": media_set}
    )

    assert signed_in_client.get("/api/session-status").get_json()["status"] == status


def test_list_selected_returns_the_picked_items(signed_in_client, monkeypatch) -> None:
    monkeypatch.setattr(picker, "get_picker_session", lambda creds, sid: {"mediaItemsSet": True})
    monkeypatch.setattr(
        picker,
        "list_media_items",
        lambda creds, sid: {"mediaItems": [{"id": "m1", "mediaFile": {"filename": "a.jpg"}}]},
    )

    body = signed_in_client.get("/api/list-selected").get_json()

    assert body["count"] == 1
    assert body["items"][0]["filename"] == "a.jpg"


def test_batch_never_sends_the_token_to_other_hosts(signed_in_client, monkeypatch) -> None:
    def fail_download(*args: Any) -> bytes:
        raise AssertionError("must not download from a non-Google host")

    monkeypatch.setattr(picker, "download_media_bytes", fail_download)

    resp = signed_in_client.post(
        "/api/process-google-batch",
        json={"items": [{"base_url": "https://evil.example/x", "filename": "a.jpg"}]},
    )

    assert resp.status_code == 500
    assert resp.get_json()["errors"] == [
        {"index": 0, "filename": "a.jpg", "error": "invalid base_url"}
    ]


def test_batch_exports_every_item_into_one_job(
    signed_in_client, monkeypatch, make_jpeg, data_dir
) -> None:
    photo = make_jpeg().read_bytes()
    monkeypatch.setattr(picker, "download_media_bytes", lambda url, token: photo)

    body = signed_in_client.post(
        "/api/process-google-batch",
        json={
            "items": [
                {"base_url": GOOGLE_URL, "filename": "a.jpg"},
                {"base_url": GOOGLE_URL, "filename": "b.jpg"},
                "not-a-dict",
            ],
            "include_json": False,
        },
    ).get_json()

    assert body["ok"] and body["processed"] == 2
    assert body["errors"] == [{"index": 2, "error": "invalid item"}]
    page = signed_in_client.get(body["job_url"]).get_data(as_text=True)
    assert ">a.jpg<" in page and ">b.jpg<" in page
    assert list((data_dir / "data" / "uploads").iterdir()) == []  # staged downloads removed


def test_batch_requires_items(signed_in_client) -> None:
    assert signed_in_client.post("/api/process-google-batch", json={"items": []}).status_code == 400


def _google_items(n: int) -> list[dict[str, str]]:
    return [{"base_url": GOOGLE_URL, "filename": f"IMG_{i}.jpg"} for i in range(n)]


def test_chunks_are_added_to_the_same_job(signed_in_client, monkeypatch, make_jpeg) -> None:
    photo = make_jpeg().read_bytes()
    monkeypatch.setattr(picker, "download_media_bytes", lambda url, token: photo)

    def post(body: dict) -> dict:
        return signed_in_client.post("/api/process-google-batch", json=body).get_json()

    first = post({"items": _google_items(2), "include_json": False})
    second = post(
        {"items": _google_items(2), "offset": 2, "job_id": first["job_id"], "include_json": False}
    )

    assert second["job_id"] == first["job_id"]
    # Same filenames in both chunks: duplicates are numbered, nothing is overwritten.
    assert list_job_files(get_job_dir(first["job_id"])) == [
        "IMG_0 (2).jpg",
        "IMG_0.jpg",
        "IMG_1 (2).jpg",
        "IMG_1.jpg",
    ]


def test_exports_keep_the_google_photos_names(signed_in_client, monkeypatch, make_jpeg) -> None:
    photo = make_jpeg().read_bytes()
    monkeypatch.setattr(picker, "download_media_bytes", lambda url, token: photo)
    names = [
        "IMG_20220802_165718137.jpg",
        "Compleanno di Carlotta.jpg",
        "Perù 2019 – Machu Picchu.jpg",
        "東京タワー.jpg",
        "../etc/passwd.jpg",
        "CON.jpg",
        "img_20220802_165718137.JPG",  # same name as the first one, ignoring case
    ]
    items = [{"base_url": GOOGLE_URL, "filename": n} for n in names]

    body = signed_in_client.post(
        "/api/process-google-batch", json={"items": items, "include_json": True}
    ).get_json()
    download = signed_in_client.get(f"/job/{body['job_id']}/download-all")
    archive = zipfile.ZipFile(io.BytesIO(download.data))

    images = [n for n in archive.namelist() if not n.endswith(".json")]
    assert sorted(images) == sorted(
        [
            "IMG_20220802_165718137.jpg",
            "Compleanno di Carlotta.jpg",
            "Perù 2019 – Machu Picchu.jpg",
            "東京タワー.jpg",
            "etcpasswd.jpg",  # separators removed, never a path
            "CON_.jpg",
            "img_20220802_165718137 (2).JPG",
        ]
    )
    # Sidecars follow their image's final name.
    assert {f"{n}.json" for n in images} == {n for n in archive.namelist() if n.endswith(".json")}
    # Non-ASCII entries carry the UTF-8 flag, so Windows and macOS extract them correctly.
    assert archive.getinfo("東京タワー.jpg").flag_bits & 0x800


def test_error_indexes_are_relative_to_the_whole_selection(signed_in_client) -> None:
    body = signed_in_client.post(
        "/api/process-google-batch", json={"items": ["bad"], "offset": 7}
    ).get_json()

    assert body["errors"] == [{"index": 7, "error": "invalid item"}]
    assert body["job_id"]  # a fully failed chunk still names its job


def test_unknown_job_is_rejected(signed_in_client) -> None:
    resp = signed_in_client.post(
        "/api/process-google-batch",
        json={"items": _google_items(1), "job_id": "00000000-0000-0000-0000-000000000000"},
    )

    assert resp.status_code == 404


@pytest.mark.parametrize("offset", [-1, "3", 1.5, True])
def test_offset_must_be_a_non_negative_integer(signed_in_client, offset) -> None:
    resp = signed_in_client.post(
        "/api/process-google-batch", json={"items": _google_items(1), "offset": offset}
    )

    assert resp.status_code == 400


CREATE_TIME = "2022-08-05T14:03:22.123456789Z"
CREATE_TS = datetime(2022, 8, 5, 14, 3, 22, tzinfo=UTC).timestamp()


def _post_batch(client, *items: dict) -> dict:
    resp = client.post(
        "/api/process-google-batch", json={"items": list(items), "include_json": False}
    )
    return resp.get_json()


def _job_file(job_id: str, suffix: str) -> Path:
    job_dir = get_job_dir(job_id)
    return next(job_dir / n for n in list_job_files(job_dir) if n.endswith(suffix))


def _fake_video_download(monkeypatch, content: bytes = b"\x00\x00\x00\x18ftypmp42video-bytes"):
    calls: list[str] = []

    def download(url: str, token: str, dest: Path) -> None:
        calls.append(url)
        dest.write_bytes(content)

    monkeypatch.setattr(picker, "download_video_to", download)
    monkeypatch.setattr(
        picker, "download_media_bytes", lambda *a: pytest.fail("videos must not use =d")
    )
    return calls


def test_videos_are_exported_unchanged_and_dated(signed_in_client, monkeypatch) -> None:
    _fake_video_download(monkeypatch)

    body = _post_batch(
        signed_in_client,
        {
            "base_url": GOOGLE_URL,
            "filename": "VID_20220805_160322.mp4",
            "type": "VIDEO",
            "mime_type": "video/mp4",
            "create_time": CREATE_TIME,
            "processing_status": "READY",
        },
    )

    video = _job_file(body["job_id"], "VID_20220805_160322.mp4")
    assert body["processed"] == 1
    assert video.read_bytes() == b"\x00\x00\x00\x18ftypmp42video-bytes"
    assert abs(video.stat().st_mtime - CREATE_TS) < 1


def test_video_extension_comes_from_the_mime_type_when_missing(
    signed_in_client, monkeypatch
) -> None:
    _fake_video_download(monkeypatch)

    body = _post_batch(
        signed_in_client,
        {
            "base_url": GOOGLE_URL,
            "filename": "clip",
            "type": "VIDEO",
            "mime_type": "video/quicktime",
        },
    )

    assert _job_file(body["job_id"], "clip.mov").is_file()


@pytest.mark.parametrize(
    ("status", "message"), [("PROCESSING", "still processing"), ("FAILED", "could not")]
)
def test_unready_videos_are_reported(
    signed_in_client, monkeypatch, status: str, message: str
) -> None:
    calls = _fake_video_download(monkeypatch)

    body = _post_batch(
        signed_in_client,
        {"base_url": GOOGLE_URL, "filename": "v.mp4", "type": "VIDEO", "processing_status": status},
    )

    assert message in body["errors"][0]["error"]
    assert calls == []


def test_interrupted_video_download_leaves_no_partial_file(signed_in_client, monkeypatch) -> None:
    def broken(url: str, token: str, dest: Path) -> None:
        dest.write_bytes(b"half")
        raise ConnectionError("connection reset")

    monkeypatch.setattr(picker, "download_video_to", broken)

    body = _post_batch(
        signed_in_client, {"base_url": GOOGLE_URL, "filename": "v.mp4", "type": "VIDEO"}
    )

    assert body["errors"][0]["error"] == "connection reset"
    assert list_job_files(get_job_dir(body["job_id"])) == []


def test_photo_without_exif_date_uses_google_create_time(
    signed_in_client, monkeypatch, make_jpeg
) -> None:
    monkeypatch.setattr(picker, "download_media_bytes", lambda url, token: make_jpeg().read_bytes())

    body = _post_batch(
        signed_in_client,
        {
            "base_url": GOOGLE_URL,
            "filename": "Screenshot.jpg",
            "type": "PHOTO",
            "create_time": CREATE_TIME,
        },
    )

    assert abs(_job_file(body["job_id"], ".jpg").stat().st_mtime - CREATE_TS) < 1


def test_exif_capture_date_wins_over_google_create_time(
    signed_in_client, monkeypatch, make_jpeg
) -> None:
    photo = make_jpeg(exif={"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2019:01:02 03:04:05"}})
    monkeypatch.setattr(picker, "download_media_bytes", lambda url, token: photo.read_bytes())

    body = _post_batch(
        signed_in_client,
        {
            "base_url": GOOGLE_URL,
            "filename": "IMG.jpg",
            "type": "PHOTO",
            "create_time": CREATE_TIME,
        },
    )

    mtime = _job_file(body["job_id"], ".jpg").stat().st_mtime
    assert mtime == datetime(2019, 1, 2, 3, 4, 5).timestamp()
