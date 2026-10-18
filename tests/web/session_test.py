"""Tests for hicpicnunc.web.session."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from flask import Response

from hicpicnunc.web import session as web_session


def test_no_cookie_means_no_session(app) -> None:
    with app.test_request_context("/"):
        assert web_session.current_session() is None
        assert web_session.creds_for_request() is None


def test_start_session_sets_an_httponly_cookie(app, credentials) -> None:
    resp = Response()
    with app.test_request_context("/"):
        web_session.start_session(credentials, resp)

    cookie = resp.headers["Set-Cookie"]
    sid = cookie.split(";")[0].split("=", 1)[1]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert web_session.picker_sessions[sid].credentials_json == credentials.to_json()


def test_refreshed_token_is_persisted(app, credentials, monkeypatch, data_dir) -> None:
    credentials.expiry = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
    web_session.picker_sessions["sid"] = web_session.PickerSessionData(credentials.to_json())

    def fake_refresh(self, request) -> None:
        self.token = "new-token"
        self.expiry = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)

    monkeypatch.setattr(type(credentials), "refresh", fake_refresh)

    with app.test_request_context("/", headers={"Cookie": f"{web_session.COOKIE_NAME}=sid"}):
        creds, data = web_session.creds_for_request()

    assert creds.token == "new-token"
    assert "new-token" in data.credentials_json
    assert "new-token" in (data_dir / "credentials" / "google_token.json").read_text()


def test_start_session_saves_email(app, credentials) -> None:
    resp = Response()
    with app.test_request_context("/"):
        web_session.start_session(credentials, resp, email="user@gmail.com")

    cookie = resp.headers["Set-Cookie"]
    sid = cookie.split(";")[0].split("=", 1)[1]
    assert web_session.picker_sessions[sid].email == "user@gmail.com"


def test_clear_session(app, credentials) -> None:
    web_session.picker_sessions["test-sid"] = web_session.PickerSessionData(
        credentials_json=credentials.to_json()
    )
    resp = Response()
    with app.test_request_context("/", headers={"Cookie": f"{web_session.COOKIE_NAME}=test-sid"}):
        web_session.clear_session(resp)

    assert "test-sid" not in web_session.picker_sessions
    cookie = resp.headers.get("Set-Cookie", "")
    assert web_session.COOKIE_NAME in cookie
    assert (
        "Expires=Thu, 01 Jan 1970" in cookie
        or "Max-Age=0" in cookie
        or f'{web_session.COOKIE_NAME}=""' in cookie
        or f"{web_session.COOKIE_NAME}=;" in cookie
    )
