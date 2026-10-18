"""Tests for hicpicnunc.google_photos.picker."""

from __future__ import annotations

from typing import Any

import pytest

from hicpicnunc.google_photos import picker


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://lh3.googleusercontent.com/abc=w200", True),
        ("https://video.ggpht.com/x", True),
        ("https://evil.example/abc", False),
        ("http://lh3.googleusercontent.com/abc", False),
        ("https://googleusercontent.com.evil.example/x", False),
        ("not a url", False),
    ],
)
def test_bearer_token_is_only_sent_to_google_hosts(url: str, allowed: bool) -> None:
    assert picker.is_google_media_url(url) is allowed


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://lh3.googleusercontent.com/abc", "https://lh3.googleusercontent.com/abc=d"),
        (
            "https://lh3.googleusercontent.com/abc=w200-h200",
            "https://lh3.googleusercontent.com/abc=d",
        ),
        ("https://lh3.googleusercontent.com/abc=d", "https://lh3.googleusercontent.com/abc=d"),
    ],
)
def test_download_url_requests_original_with_metadata(base_url: str, expected: str) -> None:
    assert picker._download_url(base_url) == expected


def test_videos_are_downloaded_with_dv_not_as_a_still_frame() -> None:
    # =d on a video returns a JPEG frame; =dv returns the video itself.
    assert picker._download_url("https://lh3.googleusercontent.com/v=w400", video=True) == (
        "https://lh3.googleusercontent.com/v=dv"
    )


@pytest.mark.parametrize(
    ("item_type", "mime_type", "expected"),
    [
        ("VIDEO", "video/mp4", True),
        ("PHOTO", "image/jpeg", False),
        ("VIDEO", None, True),
        (None, "video/quicktime", True),
        (None, "image/heic", False),
        (None, None, False),
    ],
)
def test_is_video(item_type, mime_type, expected: bool) -> None:
    assert picker.is_video(item_type, mime_type) is expected


def test_download_video_streams_to_disk(monkeypatch, tmp_path) -> None:
    seen: dict[str, Any] = {}

    class StreamingResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self) -> None:
            pass

        def iter_content(self, chunk_size: int):
            seen["chunk_size"] = chunk_size
            yield from (b"part1-", b"part2")

    def fake_get(url: str, **kwargs: Any):
        seen.update(url=url, **kwargs)
        return StreamingResponse()

    monkeypatch.setattr(picker.requests, "get", fake_get)
    dest = tmp_path / "clip.mp4"

    picker.download_video_to("https://lh3.googleusercontent.com/v=w1", "tok", dest)

    assert dest.read_bytes() == b"part1-part2"
    assert seen["url"].endswith("=dv")
    assert seen["stream"] is True
    assert seen["headers"] == {"Authorization": "Bearer tok"}


def test_download_media_bytes_sends_bearer_token(monkeypatch, fake_response) -> None:
    calls: list[dict[str, Any]] = []

    def fake_get(url: str, **kwargs: Any):
        calls.append({"url": url, **kwargs})
        return fake_response(content=b"jpeg-bytes")

    monkeypatch.setattr(picker.requests, "get", fake_get)

    assert (
        picker.download_media_bytes("https://lh3.googleusercontent.com/a=w1", "tok")
        == b"jpeg-bytes"
    )
    assert calls[0]["url"] == "https://lh3.googleusercontent.com/a=d"
    assert calls[0]["headers"] == {"Authorization": "Bearer tok"}


def test_list_media_items_queries_the_session(monkeypatch, fake_response, credentials) -> None:
    seen: dict[str, Any] = {}

    def fake_get(url: str, **kwargs: Any):
        seen.update(url=url, **kwargs)
        return fake_response(json_body={"mediaItems": []})

    monkeypatch.setattr(picker.requests, "get", fake_get)

    assert picker.list_media_items(credentials, "sess/1") == {"mediaItems": []}
    assert seen["url"] == f"{picker.PICKER_BASE}/mediaItems"
    assert seen["params"]["sessionId"] == "sess/1"
    assert seen["headers"]["Authorization"] == "Bearer access-token"


def test_list_media_items_follows_every_page(monkeypatch, fake_response, credentials) -> None:
    pages = {
        None: {"mediaItems": [{"id": str(i)} for i in range(100)], "nextPageToken": "p2"},
        "p2": {"mediaItems": [{"id": "100"}], "nextPageToken": "p3"},
        "p3": {},  # the last page may omit mediaItems
    }
    tokens: list[str | None] = []

    def fake_get(url: str, **kwargs: Any):
        token = kwargs["params"].get("pageToken")
        tokens.append(token)
        return fake_response(json_body=pages[token])

    monkeypatch.setattr(picker.requests, "get", fake_get)

    items = picker.list_media_items(credentials, "sess")["mediaItems"]

    assert len(items) == 101
    assert tokens == [None, "p2", "p3"]


def test_list_media_items_stops_on_http_errors(monkeypatch, fake_response, credentials) -> None:
    monkeypatch.setattr(picker.requests, "get", lambda url, **kw: fake_response(status_code=500))

    with pytest.raises(picker.requests.HTTPError):
        picker.list_media_items(credentials, "sess")


def test_session_ids_are_url_escaped() -> None:
    assert picker._session_url("a/b?c") == f"{picker.PICKER_BASE}/sessions/a%2Fb%3Fc"


def test_transform_picker_items_shapes_items_for_the_frontend() -> None:
    raw = {
        "mediaItems": [
            {
                "id": "m1",
                "createTime": "2020-01-01T10:00:00Z",
                "mediaFile": {
                    "baseUrl": "https://lh3.googleusercontent.com/m1",
                    "mimeType": "image/jpeg",
                    "filename": "IMG_1.jpg",
                    "mediaFileMetadata": {"width": 4000, "height": 3000, "cameraMake": "Cam"},
                },
            },
            {"id": "m2"},
        ]
    }

    raw["mediaItems"].append(
        {
            "id": "v1",
            "type": "VIDEO",
            "mediaFile": {
                "mimeType": "video/mp4",
                "mediaFileMetadata": {"videoMetadata": {"fps": 30, "processingStatus": "READY"}},
            },
        }
    )
    first, second, video = picker.transform_picker_items(raw)
    assert video["type"] == "VIDEO"
    assert video["videoProcessingStatus"] == "READY"

    assert first["filename"] == "IMG_1.jpg"
    assert first["mediaMetadata"]["width"] == 4000
    assert first["mediaMetadata"]["creationTime"] == "2020-01-01T10:00:00Z"
    assert second == {**second, "id": "m2", "baseUrl": None}
    assert picker.transform_picker_items({}) == []


def test_credentials_round_trip_through_session_json(credentials) -> None:
    creds = picker.credentials_from_session_json(credentials.to_json())

    assert creds.token == "access-token"
    assert not creds.expired
