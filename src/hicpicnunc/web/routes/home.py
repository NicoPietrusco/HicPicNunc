"""Home page and saved metadata preferences."""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from ...core.metadata_fields import save_metadata_preferences
from ...log import get_logger
from ...settings import settings

logger = get_logger(__name__)

bp = Blueprint("home", __name__)


@bp.get("/")
def index():
    return render_template("index.html")


@bp.post("/api/metadata-preferences")
def save_preferences():
    body = request.get_json(silent=True) or {}
    preferences = body.get("preferences")
    if not isinstance(preferences, dict):
        return jsonify({"ok": False, "detail": "preferences must be an object"}), 400
    try:
        saved = save_metadata_preferences(preferences, settings.metadata_preferences_path)
    except OSError as e:
        logger.exception("Could not save metadata preferences")
        return jsonify({"ok": False, "detail": str(e)}), 500
    return jsonify({"ok": True, "preferences": saved})
