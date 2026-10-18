"""
Flask application factory: local desktop use (localhost). Google Photos via Desktop OAuth + Picker API.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, request

from ..core.jobs import prune_expired_jobs
from ..core.metadata_fields import load_metadata_preferences
from ..log import setup_logger
from ..settings import settings
from .i18n import current_language, js_catalog, t, tn
from .routes import auth, home, jobs, picker

_LOCAL_HOSTNAMES = {"127.0.0.1", "localhost", "[::1]"}


def is_local_host_header(host: str) -> bool:
    """DNS-rebinding guard: the app only answers requests addressed to loopback."""
    hostname = host.lower()
    if not hostname.endswith("]"):  # strip the port, but not from a bare IPv6 literal
        hostname = hostname.rsplit(":", 1)[0]
    return hostname in _LOCAL_HOSTNAMES


def create_app() -> Flask:
    setup_logger()
    load_dotenv(settings.resource_dir / ".env")

    root = Path(__file__).resolve().parent
    app = Flask(
        __name__,
        template_folder=str(root / "templates"),
        static_folder=str(root / "static"),
    )
    app.secret_key = settings.secret_key
    app.config["MAX_CONTENT_LENGTH"] = settings.max_upload_mb * 1024 * 1024

    for d in (settings.data_dir, settings.upload_dir, settings.web_output_dir):
        d.mkdir(parents=True, exist_ok=True)
    prune_expired_jobs()

    @app.before_request
    def reject_non_local_hosts():
        if not is_local_host_header(request.host):
            return "Forbidden", 403
        return None

    @app.context_processor
    def inject_globals() -> dict:
        return {
            "settings": settings,
            "google_oauth_ready": settings.google_oauth_client_secrets_path.is_file(),
            "metadata_preferences": load_metadata_preferences(settings.metadata_preferences_path),
            "lang": current_language(),
            "t": t,
            "tn": tn,
            "js_i18n": js_catalog(),
        }

    for blueprint in (home.bp, auth.bp, jobs.bp, picker.bp):
        app.register_blueprint(blueprint)

    return app
