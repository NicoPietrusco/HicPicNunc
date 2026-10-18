"""Tests for hicpicnunc.google_photos.oauth."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hicpicnunc.google_photos import oauth


def test_sign_in_requests_only_read_access_to_picked_items(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}

    class FakeFlow:
        @classmethod
        def from_client_secrets_file(cls, path: str, scopes: list[str]) -> FakeFlow:
            seen.update(path=path, scopes=scopes)
            return cls()

        def run_local_server(self, **kwargs: Any) -> str:
            seen.update(kwargs)
            return "credentials"

    monkeypatch.setattr(oauth, "InstalledAppFlow", FakeFlow)
    secrets = tmp_path / "client_secrets.json"

    assert oauth.GooglePhotosOAuth(secrets).run_local_server() == "credentials"
    assert seen["path"] == str(secrets)
    assert seen["scopes"] == oauth.SCOPES
    assert "openid" in seen["scopes"]
    assert "https://www.googleapis.com/auth/userinfo.email" in seen["scopes"]
    assert "https://www.googleapis.com/auth/photospicker.mediaitems.readonly" in seen["scopes"]
    assert seen["prompt"] == "select_account consent"
    assert seen["port"] == 0  # any free port, so it never collides with the app
    assert seen["timeout_seconds"] == oauth.SIGN_IN_TIMEOUT_SECONDS  # never waits forever


def test_revoke_token_success(monkeypatch: pytest.MonkeyPatch, fake_response) -> None:
    posted: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any):
        posted.update(url=url, **kwargs)
        return fake_response(status_code=200)

    monkeypatch.setattr(oauth.requests, "post", fake_post)
    assert oauth.revoke_token("tok-123") is True
    assert posted["url"] == oauth.REVOKE_URL
    assert posted["data"] == {"token": "tok-123"}


def test_revoke_token_network_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url: str, **kwargs: Any):
        import requests

        raise requests.ConnectionError("Offline")

    monkeypatch.setattr(oauth.requests, "post", fake_post)
    assert oauth.revoke_token("tok-123") is False


def test_revoke_credentials_prefers_refresh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    revoked: list[str] = []
    monkeypatch.setattr(oauth, "revoke_token", lambda tok: revoked.append(tok) or True)

    class DummyCreds:
        token = "access-tok"
        refresh_token = "refresh-tok"

    assert oauth.revoke_credentials(DummyCreds()) is True
    assert revoked == ["refresh-tok"]


def test_extract_verified_email_from_account(credentials) -> None:
    credentials = credentials.with_account("saved@gmail.com")
    assert oauth.extract_verified_email(credentials) == "saved@gmail.com"


def test_extract_verified_email_from_id_token(credentials, monkeypatch: pytest.MonkeyPatch) -> None:
    credentials._id_token = "fake-jwt"
    monkeypatch.setattr(
        oauth.id_token,
        "verify_oauth2_token",
        lambda token, request, aud: {"email": "verified@gmail.com"},
    )
    assert oauth.extract_verified_email(credentials) == "verified@gmail.com"


def test_extract_verified_email_fallback_userinfo(
    credentials, monkeypatch: pytest.MonkeyPatch, fake_response
) -> None:
    credentials._id_token = "broken-jwt"

    def fail_verify(*args, **kwargs):
        raise ValueError("Invalid signature")

    monkeypatch.setattr(oauth.id_token, "verify_oauth2_token", fail_verify)

    def fake_get(url: str, **kwargs):
        return fake_response(json_body={"email": "userinfo@gmail.com"}, status_code=200)

    monkeypatch.setattr(oauth.requests, "get", fake_get)
    assert oauth.extract_verified_email(credentials) == "userinfo@gmail.com"


def test_photos_scope_in_scopes() -> None:
    assert oauth.PHOTOS_SCOPE == "https://www.googleapis.com/auth/photospicker.mediaitems.readonly"
    assert oauth.PHOTOS_SCOPE in oauth.SCOPES


def test_has_photos_scope(credentials) -> None:
    # Full scopes granted
    credentials._granted_scopes = list(oauth.SCOPES)
    assert oauth.has_photos_scope(credentials) is True

    # Partial grant (missing Photos scope)
    credentials._granted_scopes = ["openid", "https://www.googleapis.com/auth/userinfo.email"]
    assert oauth.has_photos_scope(credentials) is False

    # None or empty granted_scopes
    credentials._granted_scopes = None
    assert oauth.has_photos_scope(credentials) is False

    credentials._granted_scopes = []
    assert oauth.has_photos_scope(credentials) is False

    # Space-separated string (as sometimes parsed in raw token payloads)
    credentials._granted_scopes = f"openid {oauth.PHOTOS_SCOPE}"
    assert oauth.has_photos_scope(credentials) is True

    credentials._granted_scopes = "openid https://www.googleapis.com/auth/userinfo.email"
    assert oauth.has_photos_scope(credentials) is False


def test_oauthlib_relax_token_scope_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    from oauthlib.oauth2.rfc6749.parameters import validate_token_parameters
    from oauthlib.oauth2.rfc6749.tokens import OAuth2Token

    token = OAuth2Token(
        {"access_token": "token", "token_type": "Bearer", "scope": "openid"},
        old_scope="openid photos",
    )

    # With OAUTHLIB_RELAX_TOKEN_SCOPE active, scope reduction does not raise
    validate_token_parameters(token)

    # Without OAUTHLIB_RELAX_TOKEN_SCOPE, oauthlib raises Scope has changed
    monkeypatch.delenv("OAUTHLIB_RELAX_TOKEN_SCOPE", raising=False)
    with pytest.raises(Exception, match="Scope has changed"):
        validate_token_parameters(token)
