"""Request checks shared by the routes."""

from __future__ import annotations

from urllib.parse import urlsplit

from flask import request


def is_cross_site_request() -> bool:
    """CSRF guard for state-changing POSTs: true for a request sent by another site."""
    origin = request.headers.get("Origin")
    if origin and urlsplit(origin).netloc != request.host:
        return True
    return request.headers.get("Sec-Fetch-Site") == "cross-site"
