#!/usr/bin/env python3
"""Check that OAuth client JSON exists and the Flask app factory loads."""

from hicpicnunc.settings import settings
from hicpicnunc.web.app import create_app


def main() -> None:
    p = settings.google_oauth_client_secrets_path
    if not p.is_file():
        raise SystemExit(
            f"Missing OAuth client JSON: {p}\n"
            "Save Google's Desktop client JSON as credentials/client_secrets.json "
            "(see docs/google-oauth-setup.md)."
        )
    create_app()
    print("OK: credentials found and app factory loads.")


if __name__ == "__main__":
    main()
