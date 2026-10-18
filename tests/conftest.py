"""Shared fixtures for the test suite."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import piexif
import pytest
import requests
from flask import Flask
from flask.testing import FlaskClient
from google.oauth2.credentials import Credentials
from PIL import Image

from hicpicnunc.google_photos.oauth import SCOPES
from hicpicnunc.web import session as web_session
from hicpicnunc.web.app import create_app


@pytest.fixture
def make_jpeg(tmp_path: Path) -> Callable[..., Path]:
    """Create a small JPEG in tmp_path, optionally with a piexif-style EXIF dict."""

    def _make(name: str = "photo.jpg", exif: dict | None = None) -> Path:
        path = tmp_path / name
        kwargs = {"exif": piexif.dump(exif)} if exif else {}
        Image.new("RGB", (8, 8)).save(path, **kwargs)
        return path

    return _make


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every writable app path (data, settings, token) at a temp folder."""
    path = tmp_path / "appdata"
    monkeypatch.setenv("HICPICNUNC_DATA_DIR", str(path))
    return path


@pytest.fixture
def app(data_dir: Path) -> Iterator[Flask]:
    app = create_app()
    app.config["TESTING"] = True
    yield app
    web_session.picker_sessions.clear()


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


def fake_credentials() -> Credentials:
    """Unexpired credentials, so nothing tries to refresh them over the network."""
    return Credentials(
        token="access-token",
        refresh_token="refresh-token",
        client_id="client-id",
        client_secret="client-secret",
        token_uri="https://oauth2.googleapis.com/token",
        scopes=list(SCOPES),
        granted_scopes=list(SCOPES),
        # google-auth compares against naive UTC
        expiry=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
    )


@pytest.fixture
def signed_in_client(client: FlaskClient) -> FlaskClient:
    """A client whose session_id cookie maps to a Google session."""
    web_session.picker_sessions["test-sid"] = web_session.PickerSessionData(
        credentials_json=fake_credentials().to_json(), picker_session_id="picker-1"
    )
    client.set_cookie(web_session.COOKIE_NAME, "test-sid")
    return client


@pytest.fixture
def credentials() -> Credentials:
    return fake_credentials()


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(
        self,
        content: bytes = b"",
        json_body: object = None,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.content = content
        self._json = json_body
        self.status_code = status_code
        self.headers = headers or {}

    def json(self) -> object:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


@pytest.fixture
def fake_response() -> type[FakeResponse]:
    return FakeResponse
