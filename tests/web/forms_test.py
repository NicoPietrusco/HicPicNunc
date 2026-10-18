"""Tests for hicpicnunc.web.forms."""

from __future__ import annotations

import pytest

from hicpicnunc.web.forms import parse_bool, parse_stem_suffix, sanitize_relative_path


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, True),
        ("false", False),
        ("0", False),
        (" OFF ", False),
        ("no", False),
        ("on", True),
        (False, False),
    ],
)
def test_parse_bool(raw: object, expected: bool) -> None:
    assert parse_bool(raw) is expected


def test_parse_bool_default_applies_only_when_missing() -> None:
    assert parse_bool(None, default=False) is False
    assert parse_bool("yes", default=False) is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, ""),
        ("  ", ""),
        ("_exif", "_exif"),
        ("-v2", "-v2"),
        ("../x", ""),
        ("a b", ""),
        ("_" * 65, ""),
    ],
)
def test_parse_stem_suffix(raw: str | None, expected: str) -> None:
    assert parse_stem_suffix(raw) == expected


@pytest.mark.parametrize(
    ("rel", "expected"),
    [
        ("trip/IMG.jpg", "trip/IMG.jpg"),
        ("trip\\day1\\IMG.jpg", "trip/day1/IMG.jpg"),
        ("/trip/IMG.jpg/", "trip/IMG.jpg"),
        ("../IMG.jpg", None),
        ("trip/../IMG.jpg", None),
        ("trip//IMG.jpg", None),
        ("my trip/Perù.jpg", "my trip/Perù.jpg"),
        ("trip:1/a?.jpg", "trip1/a.jpg"),
        ("trip/.../IMG.jpg", None),
        ("a\0b.jpg", None),
        ("", None),
    ],
)
def test_sanitize_relative_path(rel: str, expected: str | None) -> None:
    assert sanitize_relative_path(rel) == expected
