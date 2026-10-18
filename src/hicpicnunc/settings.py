"""
Application settings: paths, limits and environment overrides.
"""

import contextlib
import os
import secrets
import sys
from pathlib import Path


class Settings:
    """Application-wide settings and constants."""

    # Shown in the web UI
    APP_NAME = "Hic Pic Nunc"

    # Accepted image extensions
    SUPPORTED_FORMATS = frozenset(
        {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp", ".heic", ".heif"}
    )

    # Videos are exported as downloaded from Google (never re-encoded here)
    VIDEO_FORMATS = frozenset({".mp4", ".mov", ".m4v", ".3gp", ".avi", ".mkv", ".webm"})

    # Web / Flask (override via environment)
    @property
    def secret_key(self) -> str:
        configured = os.environ.get("SECRET_KEY")
        if configured:
            return configured
        if not getattr(sys, "frozen", False):
            return "dev-only-change-SECRET_KEY"

        key_path = self.app_data_dir / "state" / "flask_secret_key"
        try:
            if key_path.is_file():
                return key_path.read_text(encoding="utf-8").strip()
            key_path.parent.mkdir(parents=True, exist_ok=True)
            key = secrets.token_urlsafe(32)
            key_path.write_text(key, encoding="utf-8")
            with contextlib.suppress(OSError):
                key_path.chmod(0o600)
            return key
        except OSError:
            return secrets.token_urlsafe(32)

    @property
    def max_upload_mb(self) -> int:
        return int(os.environ.get("MAX_UPLOAD_MB", "50"))

    @property
    def job_retention_hours(self) -> float:
        """How long exported photos stay on disk for download before being deleted."""
        return float(os.environ.get("JOB_RETENTION_HOURS", "24"))

    @property
    def web_output_image_suffix(self) -> str:
        """
        Suffix appended to image/JSON basenames when "add suffix" is enabled locally.
        Set to empty in .env to default the UI to overwrite-style names (same basename).
        """
        return os.environ.get("WEB_OUTPUT_IMAGE_SUFFIX", "_exif")

    @property
    def google_oauth_client_secrets_path(self) -> Path:
        """Desktop OAuth client JSON from Google Cloud (Installed app)."""
        env = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRETS")
        if env:
            return Path(env)
        return self.resource_dir / "credentials" / "client_secrets.json"

    @property
    def google_token_path(self) -> Path:
        """Saved OAuth token after first sign-in (local only, gitignored)."""
        return self.app_data_dir / "credentials" / "google_token.json"

    @property
    def metadata_preferences_path(self) -> Path:
        """Per-user metadata choices shared by local and Google Photos workflows."""
        return self.app_data_dir / "settings" / "metadata_preferences.json"

    @property
    def log_path(self) -> Path:
        """Log file for desktop builds, which have no terminal."""
        return self.app_data_dir / "logs" / "hicpicnunc.log"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def web_output_dir(self) -> Path:
        return self.data_dir / "outputs"

    @property
    def resource_dir(self) -> Path:
        """Directory containing read-only application resources."""
        bundle_dir = getattr(sys, "_MEIPASS", None)
        if getattr(sys, "frozen", False) and isinstance(bundle_dir, str):
            return Path(bundle_dir)
        return Path(__file__).parent.parent.parent

    @property
    def app_data_dir(self) -> Path:
        """Writable data directory; separate from a frozen app bundle."""
        # Folder names below predate the rename: kept so existing users keep their data.
        override = os.environ.get("HICPICNUNC_DATA_DIR") or os.environ.get(
            "GPHOTOMETASYNC_DATA_DIR"
        )
        if override:
            return Path(override).expanduser()
        if not getattr(sys, "frozen", False):
            return self.resource_dir
        home = Path.home()
        if sys.platform == "darwin":
            return home / "Library" / "Application Support" / "GPhotoMetaSync"
        if sys.platform == "win32":
            return (
                Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")) / "GPhotoMetaSync"
            )
        return Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share")) / "gphotometasync"

    @property
    def data_dir(self) -> Path:
        """Get the data directory."""
        return self.app_data_dir / "data"


# Global settings instance
settings = Settings()
