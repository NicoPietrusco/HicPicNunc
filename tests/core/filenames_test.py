"""Tests for hicpicnunc.core.filenames."""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest

from hicpicnunc.core.filenames import (
    MAX_NAME_BYTES,
    is_safe_filename,
    safe_filename,
    unique_name,
)


@pytest.mark.parametrize(
    "name",
    [
        "IMG_20220802_165718137.jpg",
        "Compleanno di Carlotta.jpg",
        "Perù 2019 – Machu Picchu.jpg",
        "東京タワー.jpg",
        "Festa 🎉 (finale).HEIC",
        "a.b.c.jpg",
        "COM10.jpg",  # only COM1-COM9 are reserved
        "CONSOLE.jpg",
    ],
)
def test_valid_names_are_kept_unchanged(name: str) -> None:
    assert safe_filename(name) == name
    assert is_safe_filename(name)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ('a/b\\c:d*e?f"g<h>i|j.jpg', "abcdefghij.jpg"),
        ("tab\there\n.jpg", "tabhere.jpg"),
        ("photo.jpg. . ", "photo.jpg"),
        ("  photo.jpg", "photo.jpg"),
        (".hidden.jpg", "hidden.jpg"),
        ("CON.jpg", "CON_.jpg"),
        ("con", "con_"),
        ("LPT9.tar.gz", "LPT9_.tar.gz"),
    ],
)
def test_invalid_names_are_made_valid(name: str, expected: str) -> None:
    assert safe_filename(name) == expected
    assert not is_safe_filename(name)


@pytest.mark.parametrize("name", ["", ".", "..", "...", "/", "../", "\0", "  "])
def test_nothing_left_returns_the_fallback(name: str) -> None:
    assert safe_filename(name, "photo.jpg") == "photo.jpg"
    assert safe_filename(name) == ""
    assert not is_safe_filename(name)


def test_decomposed_unicode_from_macos_is_normalized() -> None:
    decomposed = unicodedata.normalize("NFD", "Perù.jpg")

    assert safe_filename(decomposed) == "Perù.jpg"
    assert not is_safe_filename(decomposed)


def test_long_names_are_shortened_keeping_the_extension() -> None:
    name = "è" * 200 + ".jpeg"

    safe = safe_filename(name)

    assert safe.endswith("è.jpeg")
    assert len(safe.encode()) <= MAX_NAME_BYTES
    # Room is left for a duplicate counter and a JSON sidecar.
    assert len(f"{Path(safe).stem} (9999).jpeg.json".encode()) <= 255


def test_unique_name_keeps_a_free_name(tmp_path: Path) -> None:
    assert unique_name(tmp_path, "IMG_0001.jpg") == "IMG_0001.jpg"
    assert unique_name(tmp_path / "missing", "IMG_0001.jpg") == "IMG_0001.jpg"


def test_unique_name_numbers_duplicates(tmp_path: Path) -> None:
    (tmp_path / "IMG_0001.jpg").touch()
    assert unique_name(tmp_path, "IMG_0001.jpg") == "IMG_0001 (2).jpg"

    (tmp_path / "IMG_0001 (2).jpg").touch()
    assert unique_name(tmp_path, "IMG_0001.jpg") == "IMG_0001 (3).jpg"


def test_unique_name_ignores_case(tmp_path: Path) -> None:
    (tmp_path / "IMG.jpg").touch()

    assert unique_name(tmp_path, "img.JPG") == "img (2).JPG"


@pytest.mark.parametrize(
    "name",
    [
        "Perù 2019 – Machu Picchu.jpg",
        "東京タワー.jpg",
        "Festa 🎉.jpg",
        'a:b*c?"d<e>f|g.jpg',
        "CON.jpg",
        "nul",
        "photo.jpg. . ",
        "è" * 200 + ".jpeg",
    ],
)
def test_safe_names_can_be_created_on_this_file_system(tmp_path: Path, name: str) -> None:
    # Run on every CI runner: on Windows this checks the rules against NTFS itself.
    safe = safe_filename(name)
    (tmp_path / safe).write_bytes(b"x")

    assert [p.name for p in tmp_path.iterdir()] == [safe]
