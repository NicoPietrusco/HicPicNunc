"""Tests for hicpicnunc.desktop."""

from __future__ import annotations

import json
import socket
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from werkzeug.serving import BaseWSGIServer, WSGIRequestHandler, make_server
from werkzeug.wrappers import Response

from hicpicnunc.desktop import (
    APP_ID,
    GRACE_PERIOD_S,
    SAFETY_TIMEOUT_S,
    Lifecycle,
    forget_instance,
    record_instance,
    request_handler,
    running_instance_url,
    watch,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def lifecycle(clock: FakeClock) -> Lifecycle:
    return Lifecycle(clock=clock)


def _open_page(lifecycle: Lifecycle, tab: str) -> None:
    """A page load and its first heartbeat, each a request of its own."""
    for _ in range(2):
        lifecycle.request_started()
        lifecycle.request_finished()
    lifecycle.heartbeat(tab)


def test_waits_for_the_first_page_as_long_as_the_safety_timeout(
    lifecycle: Lifecycle, clock: FakeClock
) -> None:
    clock.advance(SAFETY_TIMEOUT_S - 1)
    assert not lifecycle.should_exit()

    clock.advance(1)
    assert lifecycle.should_exit()


def test_an_open_tab_keeps_the_app_running(lifecycle: Lifecycle, clock: FakeClock) -> None:
    _open_page(lifecycle, "tab-1")
    for _ in range(30):
        clock.advance(60)  # a background tab's throttled heartbeat
        lifecycle.heartbeat("tab-1")
        assert not lifecycle.should_exit()


def test_closing_the_last_tab_stops_the_app_after_the_grace_period(
    lifecycle: Lifecycle, clock: FakeClock
) -> None:
    _open_page(lifecycle, "tab-1")
    clock.advance(30)
    lifecycle.goodbye("tab-1")

    clock.advance(GRACE_PERIOD_S - 1)
    assert not lifecycle.should_exit()
    clock.advance(1)
    assert lifecycle.should_exit()


def test_a_reload_does_not_stop_the_app(lifecycle: Lifecycle, clock: FakeClock) -> None:
    _open_page(lifecycle, "tab-1")
    lifecycle.goodbye("tab-1")
    clock.advance(2)
    _open_page(lifecycle, "tab-2")

    clock.advance(GRACE_PERIOD_S * 4)
    assert not lifecycle.should_exit()


def test_closing_one_of_two_tabs_keeps_the_app_running(
    lifecycle: Lifecycle, clock: FakeClock
) -> None:
    _open_page(lifecycle, "tab-1")
    _open_page(lifecycle, "tab-2")
    lifecycle.goodbye("tab-1")

    clock.advance(GRACE_PERIOD_S * 3)  # tab-2 is in the background, between heartbeats
    assert not lifecycle.should_exit()


def test_a_silent_tab_is_dropped_after_the_safety_timeout(
    lifecycle: Lifecycle, clock: FakeClock
) -> None:
    _open_page(lifecycle, "tab-1")

    clock.advance(SAFETY_TIMEOUT_S - 1)
    assert not lifecycle.should_exit()
    clock.advance(1)
    assert lifecycle.should_exit()


def test_a_request_in_flight_keeps_the_app_running(lifecycle: Lifecycle, clock: FakeClock) -> None:
    _open_page(lifecycle, "tab-1")
    lifecycle.request_started()  # a ZIP download
    lifecycle.goodbye("tab-1")

    clock.advance(SAFETY_TIMEOUT_S * 10)
    assert not lifecycle.should_exit()

    lifecycle.request_finished()
    assert not lifecycle.should_exit()
    clock.advance(GRACE_PERIOD_S)
    assert lifecycle.should_exit()


def test_quit_stops_the_app_once_requests_finish(lifecycle: Lifecycle) -> None:
    _open_page(lifecycle, "tab-1")
    lifecycle.request_started()
    lifecycle.quit()
    assert not lifecycle.should_exit()

    lifecycle.request_finished()
    assert lifecycle.should_exit()


def test_watch_shuts_the_server_down_when_allowed(lifecycle: Lifecycle) -> None:
    stopped = threading.Event()

    class Server:
        def shutdown(self) -> None:
            stopped.set()

    lifecycle.quit()
    watch(Server(), lifecycle, interval=0.01)
    assert stopped.wait(5)


@pytest.fixture
def serve() -> Iterator[Callable[..., BaseWSGIServer]]:
    """Start a local threaded server for a WSGI app."""
    running: list[tuple[BaseWSGIServer, threading.Thread]] = []

    def start(app, handler: type[WSGIRequestHandler] | None = None) -> BaseWSGIServer:
        server = make_server("127.0.0.1", 0, app, threaded=True, request_handler=handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        running.append((server, thread))
        return server

    yield start
    for server, thread in running:
        server.shutdown()
        server.server_close()
        thread.join(5)


def _json_app(payload: dict):
    return Response(json.dumps(payload), mimetype="application/json")


def _download_app(release: threading.Event):
    """A streamed download that pauses after its first chunk until release is set."""

    def chunks() -> Iterator[bytes]:
        yield b"first"
        release.wait(5)
        yield from [b"x" * 65536] * 200  # more than any socket buffer holds

    def app(environ, start_response):
        return Response(chunks())(environ, start_response)

    return app


def _wait_for(condition: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_a_streamed_download_counts_until_it_is_sent(lifecycle: Lifecycle, serve) -> None:
    release = threading.Event()
    lifecycle.quit()
    server = serve(_download_app(release), request_handler(lifecycle))

    with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/", timeout=5) as resp:
        assert resp.read(5) == b"first"
        assert not lifecycle.should_exit()
        release.set()
        resp.read()

    assert _wait_for(lifecycle.should_exit)


def test_a_reset_connection_counts_as_finished(lifecycle: Lifecycle, serve) -> None:
    # Werkzeug drains an unread request body after the response, and a reset during that
    # skips the response's close(): counting there would leave this request active.
    lifecycle.quit()
    server = serve(Response("ok"), request_handler(lifecycle))
    sock = socket.create_connection(("127.0.0.1", server.server_port), timeout=5)
    sock.sendall(b"POST / HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 5\r\n\r\nhello")
    response = b""
    while not response.endswith(b"\r\n\r\nok"):  # the whole response, headers and body
        chunk = sock.recv(4096)
        assert chunk, f"connection closed after {response!r}"
        response += chunk
    linger = struct.pack("HH" if sys.platform == "win32" else "ii", 1, 0)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)
    sock.close()

    assert _wait_for(lifecycle.should_exit)


def test_a_failed_request_counts_as_finished(lifecycle: Lifecycle, serve) -> None:
    def failing_app(environ, start_response):
        raise RuntimeError("boom")

    lifecycle.quit()
    server = serve(failing_app, request_handler(lifecycle))
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/", timeout=5)
    error.value.close()

    assert error.value.code == 500
    assert _wait_for(lifecycle.should_exit)


def test_finds_a_running_instance(tmp_path: Path, serve) -> None:
    port = serve(_json_app({"app": APP_ID})).server_port
    path = tmp_path / "state" / "instance.json"
    record_instance(path, port)

    assert running_instance_url(path) == f"http://127.0.0.1:{port}"


def test_ignores_another_program_on_the_recorded_port(tmp_path: Path, serve) -> None:
    path = tmp_path / "instance.json"
    record_instance(path, serve(_json_app({"app": "something-else"})).server_port)

    assert running_instance_url(path) is None


def test_ignores_a_record_left_by_a_stopped_instance(tmp_path: Path) -> None:
    server = make_server("127.0.0.1", 0, Response())
    port = server.server_port
    server.server_close()
    path = tmp_path / "instance.json"
    record_instance(path, port)

    assert running_instance_url(path, timeout=0.5) is None


@pytest.mark.parametrize("content", [None, "", "not json", "[]", '{"port": "x"}'])
def test_ignores_a_missing_or_broken_record(tmp_path: Path, content: str | None) -> None:
    path = tmp_path / "instance.json"
    if content is not None:
        path.write_text(content)

    assert running_instance_url(path) is None


def test_forget_instance_keeps_a_record_replaced_by_another_copy(tmp_path: Path) -> None:
    path = tmp_path / "instance.json"
    record_instance(path, 5100)
    forget_instance(path, 5200)
    assert path.is_file()

    forget_instance(path, 5100)
    assert not path.exists()
