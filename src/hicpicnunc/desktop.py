"""
Desktop app lifecycle: stop when the last browser tab closes, and run one instance at a time.

A desktop build has no window of its own, only the browser tab. Each open page sends a
heartbeat with its tab id and says goodbye when it goes away. The server stops once no
tab is left and no request is in flight, after a grace period that covers a reload or a
navigation. A tab that stops sending heartbeats (browser killed, laptop asleep) is
dropped after a safety timeout, longer than the once-a-minute timers of background tabs.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from werkzeug.wsgi import ClosingIterator

if TYPE_CHECKING:
    from _typeshed.wsgi import StartResponse, WSGIApplication, WSGIEnvironment

# Sent by /api/instance, so a running copy isn't mistaken for another program on its port
APP_ID = "hicpicnunc"

HEARTBEAT_INTERVAL_S = 10
GRACE_PERIOD_S = 15
SAFETY_TIMEOUT_S = 180


class Lifecycle:
    """Decides when the server may stop; the clock is injectable for tests."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        grace_period: float = GRACE_PERIOD_S,
        safety_timeout: float = SAFETY_TIMEOUT_S,
    ) -> None:
        self._clock = clock
        self._grace_period = grace_period
        self._safety_timeout = safety_timeout
        self._lock = threading.Lock()
        self._tabs: dict[str, float] = {}  # tab id -> last heartbeat
        self._active_requests = 0
        # Until the first page reports in, wait as long as for a silent tab.
        self._quiet_until = clock() + safety_timeout
        self._first_page_seen = False
        self._quit_requested = False

    def heartbeat(self, tab_id: str) -> None:
        with self._lock:
            now = self._clock()
            self._tabs[tab_id] = now
            if not self._first_page_seen:
                self._first_page_seen = True
                self._quiet_until = now + self._grace_period

    def goodbye(self, tab_id: str) -> None:
        with self._lock:
            self._tabs.pop(tab_id, None)
            self._extend_quiet(self._grace_period)

    def quit(self) -> None:
        with self._lock:
            self._quit_requested = True

    def request_started(self) -> None:
        with self._lock:
            self._active_requests += 1

    def request_finished(self) -> None:
        with self._lock:
            self._active_requests -= 1
            self._extend_quiet(self._grace_period)

    def should_exit(self) -> bool:
        with self._lock:
            if self._active_requests:
                return False
            if self._quit_requested:
                return True
            now = self._clock()
            self._tabs = {
                tab: seen for tab, seen in self._tabs.items() if now - seen < self._safety_timeout
            }
            return not self._tabs and now >= self._quiet_until

    def _extend_quiet(self, seconds: float) -> None:
        self._quiet_until = max(self._quiet_until, self._clock() + seconds)


class ActiveRequestsMiddleware:
    """
    WSGI middleware that counts a request as active until its response is closed.

    Flask's after_request runs before a streamed response (the ZIP download) is sent,
    so the count must end in the response iterable's close().
    """

    def __init__(self, app: WSGIApplication, lifecycle: Lifecycle) -> None:
        self.app = app
        self.lifecycle = lifecycle

    def __call__(self, environ: WSGIEnvironment, start_response: StartResponse) -> ClosingIterator:
        self.lifecycle.request_started()
        try:
            body = self.app(environ, start_response)
        except BaseException:
            self.lifecycle.request_finished()
            raise
        return ClosingIterator(body, self.lifecycle.request_finished)


def watch(server: Any, lifecycle: Lifecycle, interval: float = 1.0) -> threading.Thread:
    """Shut the server down, from a background thread, once the lifecycle allows it."""

    def run() -> None:
        while not lifecycle.should_exit():
            time.sleep(interval)
        server.shutdown()

    thread = threading.Thread(target=run, name="lifecycle-watch", daemon=True)
    thread.start()
    return thread


def running_instance_url(instance_path: Path, timeout: float = 2.0) -> str | None:
    """URL of a copy of the app already running, as recorded in instance_path."""
    try:
        port = int(json.loads(instance_path.read_text(encoding="utf-8"))["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    url = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(f"{url}/api/instance", timeout=timeout) as resp:
            if json.load(resp).get("app") == APP_ID:
                return url
    except (OSError, ValueError, AttributeError):
        pass
    return None


def record_instance(instance_path: Path, port: int) -> None:
    instance_path.parent.mkdir(parents=True, exist_ok=True)
    instance_path.write_text(json.dumps({"port": port}), encoding="utf-8")


def forget_instance(instance_path: Path, port: int) -> None:
    """Remove the record, unless another copy has replaced it with its own port."""
    try:
        if json.loads(instance_path.read_text(encoding="utf-8")).get("port") == port:
            instance_path.unlink()
    except (OSError, ValueError, AttributeError):
        pass
