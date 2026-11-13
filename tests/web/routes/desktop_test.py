"""Tests for hicpicnunc.web.routes.desktop."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from flask import Flask
from flask.testing import FlaskClient

from hicpicnunc.desktop import APP_ID, Lifecycle
from hicpicnunc.web import session as web_session
from hicpicnunc.web.app import create_app


class RecordingLifecycle(Lifecycle):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, str]] = []

    def heartbeat(self, tab_id: str) -> None:
        self.calls.append(("heartbeat", tab_id))

    def goodbye(self, tab_id: str) -> None:
        self.calls.append(("goodbye", tab_id))

    def quit(self) -> None:
        self.calls.append(("quit", ""))


@pytest.fixture
def lifecycle() -> RecordingLifecycle:
    return RecordingLifecycle()


@pytest.fixture
def desktop_app(data_dir, lifecycle: RecordingLifecycle) -> Iterator[Flask]:
    app = create_app(lifecycle)
    app.config["TESTING"] = True
    yield app
    web_session.picker_sessions.clear()


@pytest.fixture
def desktop_client(desktop_app: Flask) -> FlaskClient:
    return desktop_app.test_client()


def test_instance_identifies_the_app(client) -> None:
    assert client.get("/api/instance").get_json() == {"app": APP_ID}


def test_heartbeat_and_goodbye_report_the_tab(desktop_client, lifecycle) -> None:
    assert desktop_client.post("/api/heartbeat", data={"tab": "tab-1"}).status_code == 200
    assert desktop_client.post("/api/goodbye", data={"tab": "tab-1"}).status_code == 200

    assert lifecycle.calls == [("heartbeat", "tab-1"), ("goodbye", "tab-1")]


def test_heartbeat_needs_a_tab_id(desktop_client, lifecycle) -> None:
    assert desktop_client.post("/api/heartbeat").status_code == 400
    assert lifecycle.calls == []


def test_quit_stops_the_app(desktop_client, lifecycle) -> None:
    resp = desktop_client.post("/api/quit")

    assert resp.get_json() == {"ok": True}
    assert lifecycle.calls == [("quit", "")]


@pytest.mark.parametrize("path", ["/api/heartbeat", "/api/goodbye", "/api/quit"])
def test_another_site_cannot_quit_or_keep_the_app_alive(desktop_client, lifecycle, path) -> None:
    resp = desktop_client.post(
        path, data={"tab": "tab-1"}, headers={"Origin": "https://evil.example"}
    )

    assert resp.status_code == 403
    assert lifecycle.calls == []


@pytest.mark.parametrize("path", ["/api/heartbeat", "/api/goodbye", "/api/quit"])
def test_lifecycle_routes_are_off_when_running_from_source(client, path) -> None:
    assert client.post(path, data={"tab": "tab-1"}).status_code == 404


def test_desktop_pages_have_the_quit_button_and_report_in(desktop_client) -> None:
    page = desktop_client.get("/").get_data(as_text=True)

    assert 'id="app-quit"' in page
    assert "js/desktop.js" in page


def test_pages_from_source_have_no_quit_button(client) -> None:
    page = client.get("/").get_data(as_text=True)

    assert 'id="app-quit"' not in page
    assert "js/desktop.js" not in page
