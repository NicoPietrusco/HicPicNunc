"""
Google Photos Picker API (REST): sessions, selected items and media download.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials

from ..log import get_logger
from .oauth import SCOPES

logger = get_logger(__name__)

PICKER_BASE = "https://photospicker.googleapis.com/v1"


class MediaUrlExpiredError(Exception):
    """Google refused a baseUrl: they stop working 60 minutes after the items are listed."""


class PickerSessionExpiredError(Exception):
    """The picker session is gone, so its items can't be listed again for fresh URLs."""


def _session_url(session_id: str) -> str:
    return f"{PICKER_BASE}/sessions/{quote(session_id, safe='')}"


def credentials_from_session_json(credentials_json: str) -> Credentials:
    info = json.loads(credentials_json)
    return Credentials.from_authorized_user_info(info, SCOPES)


def ensure_fresh(creds: Credentials) -> None:
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())


def create_picker_session(creds: Credentials) -> dict[str, Any]:
    ensure_fresh(creds)
    headers = {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}
    r = requests.post(f"{PICKER_BASE}/sessions", headers=headers, json={}, timeout=60)
    r.raise_for_status()
    return r.json()


def get_picker_session(creds: Credentials, session_id: str) -> dict[str, Any]:
    ensure_fresh(creds)
    headers = {"Authorization": f"Bearer {creds.token}"}
    r = requests.get(_session_url(session_id), headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()


def list_media_items(creds: Credentials, session_id: str) -> dict[str, Any]:
    """Every picked item, following nextPageToken (a selection can span many pages)."""
    items: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        ensure_fresh(creds)
        headers = {"Authorization": f"Bearer {creds.token}"}
        params: dict[str, Any] = {"sessionId": session_id, "pageSize": 100}
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(f"{PICKER_BASE}/mediaItems", headers=headers, params=params, timeout=60)
        r.raise_for_status()
        page = r.json()
        items.extend(page.get("mediaItems") or [])
        page_token = page.get("nextPageToken")
        if not page_token:
            return {"mediaItems": items}


def fresh_base_urls(creds: Credentials, session_id: str) -> dict[str, str]:
    """
    List the selection again for new baseUrls, by media item id.

    Raises PickerSessionExpiredError when Google no longer knows the session.
    """
    try:
        raw = list_media_items(creds, session_id)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        # Logged in full: which status Google uses for an expired session is a guess (#23).
        logger.warning(
            "Listing picker session {} again failed: HTTP {} {}",
            session_id[:8],
            status,
            getattr(e.response, "text", "")[:500],
        )
        if status in (400, 404):
            raise PickerSessionExpiredError(session_id) from e
        raise
    urls: dict[str, str] = {}
    for item in raw["mediaItems"]:
        base_url = (item.get("mediaFile") or {}).get("baseUrl")
        if item.get("id") and base_url:
            urls[item["id"]] = base_url
    return urls


def transform_picker_items(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Shape PickedMediaItem list for the frontend."""
    out = []
    for item in raw.get("mediaItems") or []:
        mf = item.get("mediaFile") or {}
        meta = mf.get("mediaFileMetadata") or {}
        photo_meta = meta.get("photoMetadata") or {}
        video_meta = meta.get("videoMetadata") or {}
        out.append(
            {
                "id": item.get("id"),
                "type": item.get("type"),  # PHOTO | VIDEO
                "baseUrl": mf.get("baseUrl"),
                "mimeType": mf.get("mimeType"),
                "filename": mf.get("filename"),
                "videoProcessingStatus": video_meta.get("processingStatus"),
                "mediaMetadata": {
                    "creationTime": item.get("createTime"),
                    "width": meta.get("width"),
                    "height": meta.get("height"),
                    "photo": photo_meta,
                    "cameraMake": meta.get("cameraMake"),
                    "cameraModel": meta.get("cameraModel"),
                },
            }
        )
    return out


def is_google_media_host(hostname: str) -> bool:
    """SSRF guard: only Google CDNs that serve Picker media."""
    hn = hostname.lower()
    return hn.endswith((".googleusercontent.com", ".ggpht.com", ".gstatic.com"))


def is_google_media_url(raw_url: str) -> bool:
    """Only send the OAuth bearer token to https Google media hosts."""
    parsed = urlparse(raw_url)
    return parsed.scheme == "https" and is_google_media_host(parsed.hostname or "")


def is_video(item_type: str | None, mime_type: str | None) -> bool:
    """Picker items are videos when typed VIDEO (or, without a type, by MIME type)."""
    if item_type:
        return item_type.upper() == "VIDEO"
    return bool(mime_type and mime_type.lower().startswith("video/"))


def _download_url(base_url: str, video: bool = False) -> str:
    """
    Append the download parameter: =d for photos (all EXIF except location) or =dv for
    videos (Google's high-quality transcode). =d on a video only returns a still frame.
    """
    param = "=dv" if video else "=d"
    u = base_url.strip()
    if "=" in u:
        u = u.rsplit("=", 1)[0]
    return u + param


def _raise_for_media_status(r: requests.Response) -> None:
    if r.status_code in (401, 403):
        raise MediaUrlExpiredError(f"HTTP {r.status_code}")
    r.raise_for_status()


def download_media_bytes(base_url: str, access_token: str) -> bytes:
    """Download a picked photo with its metadata. Raises MediaUrlExpiredError on 401/403."""
    r = requests.get(
        _download_url(base_url),
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=120,
    )
    _raise_for_media_status(r)
    return r.content


def download_video_to(base_url: str, access_token: str, dest: Path) -> None:
    """Stream a picked video to dest without holding it in memory. See download_media_bytes."""
    with requests.get(
        _download_url(base_url, video=True),
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=120,
        stream=True,
    ) as r:
        _raise_for_media_status(r)
        with dest.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
