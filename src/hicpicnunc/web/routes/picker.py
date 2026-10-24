"""Google Photos Picker: sessions, selected items, thumbnails and batch export."""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import partial
from pathlib import Path
from urllib.parse import urlparse

import requests
from flask import Blueprint, Response, jsonify, request, session, url_for

from ...core.exif import process_image_extract_and_embed
from ...core.filenames import safe_filename, unique_name
from ...core.jobs import (
    get_job_dir,
    is_image_file,
    is_video_file,
    new_job,
    set_file_date,
    staged_file,
)
from ...core.metadata_fields import ExifFieldConfig, load_user_exif_field_config
from ...google_photos.picker import (
    MediaUrlExpiredError,
    PickerSessionExpiredError,
    create_picker_session,
    download_media_bytes,
    download_video_to,
    ensure_fresh,
    fresh_base_urls,
    get_picker_session,
    is_google_media_host,
    is_google_media_url,
    is_video,
    list_media_items,
    transform_picker_items,
)
from ...log import get_logger
from ...settings import settings
from ..forms import parse_bool
from ..session import PickerSessionData, creds_for_request

logger = get_logger(__name__)

bp = Blueprint("picker", __name__)

_NOT_AUTHENTICATED = ({"detail": "Not authenticated"}, 401)


@bp.get("/api/picker-image")
def image():
    """
    Fetch a Picker media baseUrl with OAuth. <img> cannot send Authorization headers,
    so we proxy the bytes through the same session cookie.
    """
    raw_url = request.args.get("url", "").strip()
    if not raw_url or len(raw_url) > 8192:
        return "Bad request", 400
    parsed = urlparse(raw_url)
    if parsed.scheme not in ("http", "https"):
        return "Invalid URL", 400
    if not is_google_media_host(parsed.hostname or ""):
        return "Forbidden", 403
    pair = creds_for_request()
    if not pair:
        return _NOT_AUTHENTICATED
    creds, _ = pair
    try:
        r = requests.get(raw_url, headers={"Authorization": f"Bearer {creds.token}"}, timeout=60)
        if r.status_code in (401, 403):
            r = requests.get(raw_url, timeout=60)
        r.raise_for_status()
        raw_ct = (r.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
        ct = raw_ct if raw_ct.startswith("image/") else "image/jpeg"
        return Response(r.content, mimetype=ct)
    except Exception as e:
        logger.warning("picker-image: {}", e)
        return jsonify({"detail": str(e)}), 502


@bp.post("/api/create-session")
def create_session():
    pair = creds_for_request()
    if not pair:
        return _NOT_AUTHENTICATED
    creds, pdata = pair
    try:
        result = create_picker_session(creds)
    except Exception as e:
        logger.exception("create-session")
        return jsonify({"detail": str(e)}), 502
    pdata.picker_session_id = result.get("id")
    pdata.fresh_urls, pdata.fresh_urls_at, pdata.fresh_urls_failed_at = {}, 0.0, 0.0
    logger.info(
        "Picker session {} created; Google expires it at {}",
        str(result.get("id"))[:8],
        result.get("expireTime") or "an unstated time",
    )
    pdata.credentials_json = creds.to_json()
    poll = (result.get("pollingConfig") or {}).get("pollInterval", "5s")
    return jsonify(
        {
            "sessionId": result.get("id"),
            "pickerUri": result.get("pickerUri"),
            "pollInterval": poll.rstrip("s") if isinstance(poll, str) else "5",
        }
    )


@bp.get("/api/session-status")
def session_status():
    pair = creds_for_request()
    if not pair:
        return _NOT_AUTHENTICATED
    creds, pdata = pair
    if not pdata.picker_session_id:
        return jsonify({"mediaItemsSet": False, "status": "no_session"})
    try:
        result = get_picker_session(creds, pdata.picker_session_id)
    except Exception as e:
        logger.warning("session-status: {}", e)
        return jsonify({"mediaItemsSet": False, "status": "error", "error": str(e)})
    pdata.credentials_json = creds.to_json()
    media_set = bool(result.get("mediaItemsSet"))
    return jsonify({"mediaItemsSet": media_set, "status": "ready" if media_set else "pending"})


@bp.get("/api/list-selected")
def list_selected():
    pair = creds_for_request()
    if not pair:
        return _NOT_AUTHENTICATED
    creds, pdata = pair
    if not pdata.picker_session_id:
        return jsonify({"items": [], "count": 0})
    try:
        if not get_picker_session(creds, pdata.picker_session_id).get("mediaItemsSet"):
            return jsonify({"items": [], "count": 0})
        raw = list_media_items(creds, pdata.picker_session_id)
    except Exception as e:
        logger.exception("list-selected")
        return jsonify({"detail": str(e)}), 502
    pdata.credentials_json = creds.to_json()
    items = transform_picker_items(raw)
    return jsonify({"items": items, "count": len(items)})


_VIDEO_EXTENSIONS = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/x-m4v": ".m4v",
    "video/3gpp": ".3gp",
    "video/webm": ".webm",
    "video/x-matroska": ".mkv",
    "video/x-msvideo": ".avi",
}


def _export_photo(
    index: int,
    filename: str,
    base_url: str,
    access_token: str,
    job_id: str,
    job_out: Path,
    field_config: ExifFieldConfig,
    include_json: bool,
    create_time: str | None,
) -> str | None:
    """Download a photo and write the filtered-EXIF copy. Returns an error message or None."""
    try:
        raw = download_media_bytes(base_url, access_token)
    except MediaUrlExpiredError:
        raise
    except Exception as e:
        return str(e)
    name = safe_filename(filename, "photo.jpg")
    if not is_image_file(Path(name)):
        name = "photo.jpg"
    name = unique_name(job_out, name)
    with staged_file(job_id, index, name) as dest:
        dest.write_bytes(raw)
        result = process_image_extract_and_embed(
            dest,
            job_out,
            field_config,
            stem_suffix="",
            output_stem=Path(name).stem,
            write_json=include_json,
        )
    if result.get("error"):
        return result["error"]
    if not result.get("filesystem_date_set"):
        # No EXIF capture date (screenshots, messaging apps): fall back to Google's date.
        set_file_date(Path(result["output_image"]), create_time)
    return None


def _export_video(
    item: dict,
    filename: str,
    base_url: str,
    access_token: str,
    job_out: Path,
    create_time: str | None,
) -> str | None:
    """Download a video unchanged, dated with Google's createTime. Returns an error or None."""
    status = item.get("processing_status")
    if status == "PROCESSING":
        return "Google is still processing this video; try again later"
    if status == "FAILED":
        return "Google could not process this video"

    name = safe_filename(filename, "video")
    if not is_video_file(Path(name)):
        mime_type = str(item.get("mime_type") or "").lower()
        name = f"{Path(name).stem or 'video'}{_VIDEO_EXTENSIONS.get(mime_type, '.mp4')}"
    output = job_out / unique_name(job_out, name)
    partial = output.with_name(output.name + ".part")  # never list a half-downloaded video
    try:
        download_video_to(base_url, access_token, partial)
        partial.replace(output)
    except Exception as e:
        partial.unlink(missing_ok=True)
        if isinstance(e, MediaUrlExpiredError):
            raise
        return str(e)
    set_file_date(output, create_time)
    return None


def _export_item(
    base_url: str,
    *,
    item: dict,
    index: int,
    filename: str,
    access_token: str,
    job_id: str,
    job_out: Path,
    field_config: ExifFieldConfig,
    include_json: bool,
    create_time: str | None,
) -> str | None:
    """Export one picked photo or video from base_url. Returns an error message or None."""
    if is_video(item.get("type"), item.get("mime_type")):
        return _export_video(item, filename, base_url, access_token, job_out, create_time)
    return _export_photo(
        index,
        filename,
        base_url,
        access_token,
        job_id,
        job_out,
        field_config,
        include_json,
        create_time,
    )


# Listing the selection again costs a request per 100 items, so new URLs are kept for later
# chunks. A URL refreshed this recently that still fails isn't expired: listing won't help.
URL_REFRESH_INTERVAL = 5 * 60
# After a failed listing (network, Google), the next items fail at once for this long
# instead of each trying again.
URL_REFRESH_RETRY_DELAY = 30

_LINK_REFUSED = "Google refused the download link"
_NO_NEW_LINK = "Could not get a new download link"


def _short(item_id: str | None) -> str:
    """Item ids run to ~90 characters and share a prefix: their end is enough in logs."""
    return f"…{item_id[-8:]}" if item_id else "without id"


def _fresh_url(creds, pdata: PickerSessionData, item_id: str) -> str | None:
    """New baseUrl for item_id, listing the selection again unless done recently."""
    if time.time() - pdata.fresh_urls_at > URL_REFRESH_INTERVAL and pdata.picker_session_id:
        started = time.time()
        pdata.fresh_urls = fresh_base_urls(creds, pdata.picker_session_id)
        pdata.fresh_urls_at = time.time()
        logger.info(
            "Listed the selection again: {} new download links in {:.1f}s",
            len(pdata.fresh_urls),
            pdata.fresh_urls_at - started,
        )
    url = pdata.fresh_urls.get(item_id)
    if url is None:
        logger.warning("Item {} is no longer in the selection", _short(item_id))
    return url


def _export_with_fresh_url(
    export: Callable[[str], str | None],
    base_url: str,
    item_id: str | None,
    creds,
    pdata: PickerSessionData,
) -> str | None:
    """
    Export from base_url; if Google refuses it as expired, retry once with a new URL.

    Returns an error message or None. Raises PickerSessionExpiredError when the selection
    can't be listed again.
    """
    try:
        return export(base_url)
    except MediaUrlExpiredError as e:
        logger.info("Download link of item {} refused ({}); getting a new one", _short(item_id), e)
    if not item_id:
        return _LINK_REFUSED
    if time.time() - pdata.fresh_urls_failed_at < URL_REFRESH_RETRY_DELAY:
        return _NO_NEW_LINK
    try:
        fresh = _fresh_url(creds, pdata, item_id)
    except requests.RequestException as e:  # Google or network trouble: these items only
        pdata.fresh_urls_failed_at = time.time()
        logger.warning(
            "Could not list the selection again ({}); retrying in {}s",
            e,
            URL_REFRESH_RETRY_DELAY,
        )
        return _NO_NEW_LINK
    if not fresh or fresh == base_url or not is_google_media_url(fresh):
        return _LINK_REFUSED
    try:
        return export(fresh)
    except MediaUrlExpiredError:
        return _LINK_REFUSED


@bp.post("/api/process-google-batch")
def process_batch():
    """
    Download and process Google Picker items into one output job folder.

    The browser sends the selection in chunks to show progress: the first request creates
    the job, later ones pass its job_id plus the offset of their first item in the whole
    selection, so error indexes refer to the whole selection. Files keep their Google
    Photos name; a name already in the job gets " (2)", " (3)"...

    Download URLs expire an hour after the selection is listed: items that carry their
    media item id are then downloaded again with a new URL. If the picker session itself
    has expired, the export stops with code "selection_expired".
    """
    pair = creds_for_request()
    if not pair:
        return _NOT_AUTHENTICATED
    creds, pdata = pair
    body = request.get_json(silent=True) or {}
    include_json = parse_bool(body.get("include_json"))
    items = body.get("items")
    if not isinstance(items, list) or not items:
        return jsonify({"detail": "items must be a non-empty list"}), 400

    offset = body.get("offset", 0)
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        return jsonify({"detail": "offset must be a non-negative integer"}), 400
    requested_job = body.get("job_id")
    if requested_job is None:
        job_id, job_out = new_job()
    else:
        existing = get_job_dir(str(requested_job))
        if existing is None:
            return jsonify({"detail": "Unknown job"}), 404
        job_id, job_out = str(requested_job), existing

    field_config = load_user_exif_field_config(settings.metadata_preferences_path)
    processed = 0
    errors: list[dict[str, str | int]] = []

    for i, it in enumerate(items, start=offset):
        # Refresh per item: a long batch can outlive the access token.
        ensure_fresh(creds)
        pdata.credentials_json = creds.to_json()
        access_token = creds.token
        if not isinstance(access_token, str):
            return jsonify({"detail": "Google access token unavailable"}), 401
        if not isinstance(it, dict):
            errors.append({"index": i, "error": "invalid item"})
            continue
        base_url = (it.get("base_url") or "").strip()
        filename = (it.get("filename") or "photo.jpg").strip() or "photo.jpg"
        if not base_url:
            errors.append({"index": i, "error": "missing base_url"})
            continue
        if not is_google_media_url(base_url):
            errors.append({"index": i, "filename": filename, "error": "invalid base_url"})
            continue

        raw_time = it.get("create_time")
        create_time = raw_time if isinstance(raw_time, str) else None
        raw_id = it.get("id")
        item_id = raw_id if isinstance(raw_id, str) and raw_id else None
        if item_id in pdata.fresh_urls:  # an earlier chunk already got a new URL
            base_url = pdata.fresh_urls[item_id]

        export = partial(
            _export_item,
            item=it,
            index=i,
            filename=filename,
            access_token=access_token,
            job_id=job_id,
            job_out=job_out,
            field_config=field_config,
            include_json=include_json,
            create_time=create_time,
        )
        try:
            error = _export_with_fresh_url(export, base_url, item_id, creds, pdata)
        except PickerSessionExpiredError:
            logger.warning("Picker session expired; export stopped after {} item(s)", processed)
            return jsonify(
                {
                    "ok": False,
                    "code": "selection_expired",
                    "detail": "The Google Photos selection expired",
                    "processed": processed,
                }
            ), 410
        if error:
            errors.append({"index": i, "filename": filename, "error": error})
        else:
            processed += 1

    if processed == 0:
        return jsonify(
            {
                "ok": False,
                "detail": "No images processed",
                "job_id": job_id,
                "processed": 0,
                "errors": errors,
            }
        ), 500

    session["last_job"] = job_id
    return jsonify(
        {
            "ok": True,
            "job_id": job_id,
            "job_url": url_for("jobs.result", job_id=job_id),
            "processed": processed,
            "errors": errors,
        }
    )
