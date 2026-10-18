"""Google sign-in (desktop OAuth) and session restore from the saved token."""

from __future__ import annotations

from urllib.parse import urlsplit

from flask import Blueprint, flash, jsonify, redirect, request, url_for
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import WSGITimeoutError

from ...google_photos.oauth import (
    SCOPES,
    GooglePhotosOAuth,
    extract_verified_email,
    has_photos_scope,
    revoke_credentials,
    revoke_token,
)
from ...google_photos.picker import credentials_from_session_json, ensure_fresh
from ...log import get_logger
from ...settings import settings
from ..i18n import t
from ..session import clear_session, current_session, save_token, start_session

logger = get_logger(__name__)

bp = Blueprint("auth", __name__)


@bp.get("/auth")
def sign_in():
    if not settings.google_oauth_client_secrets_path.is_file():
        flash(t("flash.google_not_configured"), "error")
        return redirect(url_for("home.index"))
    try:
        creds = GooglePhotosOAuth().run_local_server()
    except WSGITimeoutError:
        flash(t("flash.sign_in_timed_out"), "error")
        return redirect(url_for("home.index"))
    except Exception as e:
        logger.exception("OAuth failed")
        flash(t("flash.sign_in_failed", error=e), "error")
        return redirect(url_for("home.index"))

    if not has_photos_scope(creds):
        try:
            revoke_credentials(creds)
        except Exception as e:
            logger.warning("Could not revoke partial credentials: {}", e)
        flash(t("flash.photos_permission_missing"), "error")
        return redirect(url_for("home.index"))

    email = extract_verified_email(creds)
    if email:
        creds = creds.with_account(email)
    save_token(creds)
    resp = redirect(url_for("home.index"))
    start_session(creds, resp, email=email)
    flash(t("flash.signed_in"), "success")
    return resp


@bp.get("/api/check-auth")
def check_auth():
    session_data = current_session()
    if session_data:
        email = session_data.email
        if not email and session_data.credentials_json:
            try:
                creds = credentials_from_session_json(session_data.credentials_json)
                email = getattr(creds, "account", None) or None
                session_data.email = email
            except Exception:
                pass
        return jsonify({"ok": True, "email": email})

    token_path = settings.google_token_path
    if not token_path.is_file():
        return jsonify({"ok": False}), 401
    try:
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        ensure_fresh(creds)
        email = getattr(creds, "account", None) or None
        if not email:
            email = extract_verified_email(creds)
            if email:
                creds = creds.with_account(email)
        save_token(creds)
    except Exception as e:
        logger.warning("check-auth token restore: {}", e)
        token_path.unlink(missing_ok=True)
        return jsonify({"ok": False, "reason": "expired"}), 401
    resp = jsonify({"ok": True, "email": email})
    start_session(creds, resp, email=email)
    return resp


@bp.post("/auth/logout")
def logout():
    origin = request.headers.get("Origin")
    if origin and urlsplit(origin).netloc != request.host:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    if request.headers.get("Sec-Fetch-Site") == "cross-site":
        return jsonify({"ok": False, "error": "forbidden"}), 403

    # Attempt to find token to revoke from in-memory session or token file
    token_to_revoke = None
    data = current_session()
    if data:
        try:
            creds = credentials_from_session_json(data.credentials_json)
            token_to_revoke = creds.refresh_token or creds.token
        except Exception:
            pass

    token_path = settings.google_token_path
    if not token_to_revoke and token_path.is_file():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
            token_to_revoke = creds.refresh_token or creds.token
        except Exception:
            pass

    # Revoke at Google (ignores failure/offline/already expired)
    if token_to_revoke:
        try:
            revoke_token(token_to_revoke)
        except Exception as e:
            logger.warning("Revoke token error: {}", e)

    # Delete local token file
    try:
        token_path.unlink(missing_ok=True)
    except OSError as e:
        logger.warning("Could not delete google_token.json: {}", e)

    # Clear in-memory session and cookie
    if request.accept_mimetypes.accept_html and not request.accept_mimetypes.accept_json:
        resp = redirect(url_for("home.index"))
    else:
        resp = jsonify({"ok": True})
    clear_session(resp)
    return resp
