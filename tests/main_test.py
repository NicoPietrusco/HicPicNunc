"""Tests for hicpicnunc.__main__."""

from __future__ import annotations

import threading
import urllib.request

import pytest

import hicpicnunc.__main__ as entry
from hicpicnunc.web.routes import auth


@pytest.fixture
def running_server(data_dir, monkeypatch, tmp_path):
    """Run main() on a free port in a thread; yields the base URL."""
    started = threading.Event()
    servers = []
    real_make_server = entry.make_server

    def make_server(*args, **kwargs):
        server = real_make_server(*args, **kwargs)
        servers.append(server)
        started.set()
        return server

    monkeypatch.setattr(entry, "make_server", make_server)
    monkeypatch.setattr(entry.webbrowser, "open", lambda url: None)
    monkeypatch.setenv("PORT", "0")
    thread = threading.Thread(target=entry.main, daemon=True)
    thread.start()
    # Generous: binding calls socket.getfqdn(), which can take seconds on CI runners.
    assert started.wait(60)
    yield f"http://127.0.0.1:{servers[0].server_port}"
    servers[0].shutdown()
    thread.join(5)


def test_a_pending_sign_in_does_not_block_other_requests(
    running_server, monkeypatch, tmp_path
) -> None:
    secrets = tmp_path / "client_secrets.json"
    secrets.write_text("{}")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRETS", str(secrets))
    in_sign_in, release = threading.Event(), threading.Event()

    def wait_for_user(self):
        in_sign_in.set()
        release.wait(10)
        raise RuntimeError("user closed the Google page")

    monkeypatch.setattr(auth.GooglePhotosOAuth, "run_local_server", wait_for_user)
    sign_in = threading.Thread(target=urllib.request.urlopen, args=(f"{running_server}/auth",))
    sign_in.start()
    assert in_sign_in.wait(5)

    try:
        with urllib.request.urlopen(f"{running_server}/", timeout=5) as resp:
            assert resp.status == 200
    finally:
        release.set()
        sign_in.join(5)
