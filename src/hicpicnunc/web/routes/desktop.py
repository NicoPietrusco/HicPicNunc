"""Desktop app lifecycle: open pages report in, and the app can be quit from the UI."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from ...desktop import APP_ID, Lifecycle
from ..guards import is_cross_site_request

bp = Blueprint("desktop", __name__)


def _lifecycle() -> Lifecycle | None:
    return current_app.extensions.get("lifecycle")


@bp.get("/api/instance")
def instance():
    """Lets a second launch recognise this copy of the app on its recorded port."""
    return jsonify({"app": APP_ID})


@bp.post("/api/heartbeat")
def heartbeat():
    lifecycle = _lifecycle()
    if lifecycle is None:
        return jsonify({"ok": False}), 404
    if is_cross_site_request():
        return jsonify({"ok": False, "error": "forbidden"}), 403
    tab_id = request.form.get("tab", "")
    if not tab_id:
        return jsonify({"ok": False, "detail": "tab is required"}), 400
    lifecycle.heartbeat(tab_id)
    return jsonify({"ok": True})


@bp.post("/api/goodbye")
def goodbye():
    """Sent with navigator.sendBeacon when a page goes away."""
    lifecycle = _lifecycle()
    if lifecycle is None:
        return jsonify({"ok": False}), 404
    if is_cross_site_request():
        return jsonify({"ok": False, "error": "forbidden"}), 403
    lifecycle.goodbye(request.form.get("tab", ""))
    return jsonify({"ok": True})


@bp.post("/api/quit")
def quit_app():
    """Stop the app once the requests in flight (a download, a sign-in) have finished."""
    lifecycle = _lifecycle()
    if lifecycle is None:
        return jsonify({"ok": False}), 404
    if is_cross_site_request():
        return jsonify({"ok": False, "error": "forbidden"}), 403
    lifecycle.quit()
    return jsonify({"ok": True})
