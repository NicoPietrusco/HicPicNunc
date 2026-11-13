"""Tests for hicpicnunc.web.guards."""

from __future__ import annotations

import pytest
from flask import Flask

from hicpicnunc.web.guards import is_cross_site_request


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({}, False),
        ({"Origin": "http://127.0.0.1:5001"}, False),
        ({"Sec-Fetch-Site": "same-origin"}, False),
        ({"Origin": "https://evil.example"}, True),
        ({"Origin": "http://127.0.0.1:6000"}, True),
        ({"Sec-Fetch-Site": "cross-site"}, True),
    ],
)
def test_is_cross_site_request(headers: dict[str, str], expected: bool) -> None:
    app = Flask(__name__)
    with app.test_request_context("/", base_url="http://127.0.0.1:5001", headers=headers):
        assert is_cross_site_request() is expected
