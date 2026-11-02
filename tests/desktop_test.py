"""Tests for hicpicnunc.desktop."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from werkzeug.serving import BaseWSGIServer, make_server
from werkzeug.wrappers import Response

from hicpicnunc.desktop import (
    APP_ID,
    GRACE_PERIOD_S,
    SAFETY_TIMEOUT_S,
    ActiveRequestsMiddleware,
    Lifecycle,
    forget_instance,
    record_instance,
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


def _start_response(status, headers, exc_info=None):
    return lambda data: None


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


def test_middleware_counts_a_streamed_response_until_it_is_closed(
    lifecycle: Lifecycle, clock: FakeClock
) -> None:
    def streaming_app(environ, start_response):
        return Response(iter([b"chunk"] * 3))(environ, start_response)

    lifecycle.quit()
    app = ActiveRequestsMiddleware(streaming_app, lifecycle)
    body = app({"REQUEST_METHOD": "GET"}, _start_response)
    assert list(body) == [b"chunk"] * 3
    assert not lifecycle.should_exit()

    body.close()
    assert lifecycle.should_exit()


def test_middleware_counts_a_failed_request_as_finished(lifecycle: Lifecycle) -> None:
    def failing_app(environ, start_response):
        raise RuntimeError("boom")

    lifecycle.quit()
    with pytest.raises(RuntimeError):
        ActiveRequestsMiddleware(failing_app, lifecycle)({}, _start_response)
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
def serve() -> Iterator[Callable[[dict], BaseWSGIServer]]:
    """Start a local server answering every request with a JSON payload."""
    running: list[tuple[BaseWSGIServer, threading.Thread]] = []

    def start(payload: dict) -> BaseWSGIServer:
        def app(environ, start_response):
            body = Response(json.dumps(payload), mimetype="application/json")
            return body(environ, start_response)

        server = make_server("127.0.0.1", 0, app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        running.append((server, thread))
        return server

    yield start
    for server, thread in running:
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_finds_a_running_instance(tmp_path: Path, serve) -> None:
    port = serve({"app": APP_ID}).server_port
    path = tmp_path / "state" / "instance.json"
    record_instance(path, port)

    assert running_instance_url(path) == f"http://127.0.0.1:{port}"


def test_ignores_another_program_on_the_recorded_port(tmp_path: Path, serve) -> None:
    path = tmp_path / "instance.json"
    record_instance(path, serve({"app": "something-else"}).server_port)

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
