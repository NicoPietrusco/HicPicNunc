"""
OAuth 2.0 for a local desktop-style app: Installed app client + run_local_server.

End users only sign in with Google; whoever packages the app adds client_secrets.json once.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import requests
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from google_auth_oauthlib.flow import InstalledAppFlow

from ..log import get_logger
from ..settings import settings

if TYPE_CHECKING:
    from google.oauth2.credentials import Credentials

# Ensure oauthlib tolerates granular consent where some requested scopes are not granted.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

logger = get_logger(__name__)

PHOTOS_SCOPE = "https://www.googleapis.com/auth/photospicker.mediaitems.readonly"

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    PHOTOS_SCOPE,
]

# Stop waiting for the Google redirect if the user abandons the sign-in page.
SIGN_IN_TIMEOUT_SECONDS = 300

REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def revoke_token(token: str) -> bool:
    """Revoke an OAuth token at Google. Returns True if successfully revoked."""
    try:
        resp = requests.post(
            REVOKE_URL,
            data={"token": token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=5,
        )
        return resp.status_code < 400
    except Exception as e:
        logger.warning("Could not revoke Google OAuth token: {}", e)
        return False


def revoke_credentials(creds: Credentials) -> bool:
    """Revoke credentials at Google, preferring refresh_token over access token."""
    token = creds.refresh_token or creds.token
    if not token:
        return False
    return revoke_token(token)


def has_photos_scope(creds: Credentials) -> bool:
    """Check whether the user granted the Google Photos scope.

    Google always includes "scope" in the token response; None or empty means no scopes granted.
    """
    granted = creds.granted_scopes
    if not granted:
        return False
    if isinstance(granted, str):
        return PHOTOS_SCOPE in granted.split()
    return PHOTOS_SCOPE in granted


def extract_verified_email(creds: Credentials) -> str | None:
    """Extract and verify user email from credentials ID token or userinfo endpoint."""
    if creds.account:
        return creds.account

    id_token_str = creds.id_token
    if id_token_str:
        try:
            payload = id_token.verify_oauth2_token(id_token_str, Request(), creds.client_id)
            email = payload.get("email")
            if email:
                return email
        except Exception as e:
            logger.warning("Could not verify ID token: {}", e)

    if creds.token:
        try:
            resp = requests.get(
                USERINFO_URL,
                headers={"Authorization": f"Bearer {creds.token}"},
                timeout=5,
            )
            if resp.status_code < 400:
                data = resp.json()
                email = data.get("email")
                if email:
                    return email
        except Exception as e:
            logger.warning("Could not fetch userinfo from Google: {}", e)

    return None


class GooglePhotosOAuth:
    """Desktop OAuth using Google Cloud "Desktop" / Installed client JSON."""

    def __init__(self, client_secret_file: Path | None = None) -> None:
        self.client_secret_file = client_secret_file or settings.google_oauth_client_secrets_path

    def run_local_server(self):
        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.client_secret_file),
            SCOPES,
        )
        return flow.run_local_server(
            port=0,
            open_browser=True,
            prompt="select_account consent",
            timeout_seconds=SIGN_IN_TIMEOUT_SECONDS,
        )
