"""
Signed-in Google sessions, kept in memory and keyed by the session_id cookie.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from flask import request
from google.oauth2.credentials import Credentials
from werkzeug.wrappers import Response

from ..google_photos.picker import credentials_from_session_json, ensure_fresh
from ..log import get_logger
from ..settings import settings

logger = get_logger(__name__)

COOKIE_NAME = "session_id"


@dataclass
class PickerSessionData:
    credentials_json: str
    picker_session_id: str | None = None
    email: str | None = None


picker_sessions: dict[str, PickerSessionData] = {}


def current_session() -> PickerSessionData | None:
    sid = request.cookies.get(COOKIE_NAME)
    return picker_sessions.get(sid) if sid else None


def start_session(creds: Credentials, response: Response, email: str | None = None) -> None:
    """Remember creds for this browser and set its session cookie on response."""
    sid = secrets.token_urlsafe(16)
    user_email = email or getattr(creds, "account", None) or None
    picker_sessions[sid] = PickerSessionData(
        credentials_json=creds.to_json(),
        email=user_email,
    )
    response.set_cookie(COOKIE_NAME, sid, httponly=True, samesite="Lax")


def clear_session(response: Response) -> None:
    """Drop in-memory session and clear the session cookie on response."""
    sid = request.cookies.get(COOKIE_NAME)
    if sid:
        picker_sessions.pop(sid, None)
    response.delete_cookie(COOKIE_NAME, httponly=True, samesite="Lax")


def save_token(creds: Credentials) -> None:
    """Persist the OAuth token so the next launch skips sign-in."""
    settings.google_token_path.parent.mkdir(parents=True, exist_ok=True)
    settings.google_token_path.write_text(creds.to_json())


def creds_for_request() -> tuple[Credentials, PickerSessionData] | None:
    """Fresh credentials for the current session, persisting any refreshed token."""
    data = current_session()
    if not data:
        return None
    creds = credentials_from_session_json(data.credentials_json)
    prev = data.credentials_json
    ensure_fresh(creds)
    data.credentials_json = creds.to_json()
    if data.credentials_json != prev:
        try:
            save_token(creds)
        except OSError as e:
            logger.warning("Could not persist google_token.json: {}", e)
    return creds, data
