"""
File names for exported files: keep the original name, changing only what a file system forbids.

The rules are Windows' (the strictest), so the names also work on macOS and Linux, and in
a ZIP extracted on any of them.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

# Characters Windows forbids in a file name, plus control characters (incl. NUL).
_INVALID_RE = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]')

# Reserved device names on Windows, with or without an extension ("CON.jpg" too).
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"{p}{n}" for p in ("COM", "LPT") for n in range(1, 10)}
)

# Most file systems allow 255 bytes per name. Leave room for " (9999)" and ".json".
MAX_NAME_BYTES = 255 - len(" (9999)") - len(".json")


def _truncate(name: str) -> str:
    """Shorten name to MAX_NAME_BYTES of UTF-8, keeping its extension when possible."""
    if len(name.encode()) <= MAX_NAME_BYTES:
        return name
    suffix = Path(name).suffix
    if len(suffix.encode()) >= MAX_NAME_BYTES // 2:
        suffix = ""
    budget = MAX_NAME_BYTES - len(suffix.encode())
    stem = name[: len(name) - len(suffix)] if suffix else name
    stem = stem.encode()[:budget].decode(errors="ignore").rstrip(". ")
    return f"{stem}{suffix}"


def safe_filename(name: str, fallback: str = "") -> str:
    """
    One path component made valid everywhere, changed as little as possible.

    Spaces, accents, emoji and non-Latin scripts are kept. Forbidden characters are
    removed; leading dots (hidden files), leading spaces and trailing dots or spaces are
    stripped; reserved Windows names get a "_". Returns fallback when nothing is left,
    so "..", "." and "/" can never come back as a name.
    """
    name = unicodedata.normalize("NFC", name)
    name = _INVALID_RE.sub("", name).lstrip(". ").rstrip(". ")
    if not name:
        return fallback
    stem, dot, rest = name.partition(".")
    if stem.upper() in _WINDOWS_RESERVED:
        name = f"{stem}_{dot}{rest}"
    return _truncate(name)


def is_safe_filename(name: str) -> bool:
    """True when name is a non-empty component that safe_filename leaves unchanged."""
    return bool(name) and safe_filename(name) == name


def unique_name(directory: Path, name: str) -> str:
    """
    name, or "stem (2).ext", "stem (3).ext"... when directory already has a file by that name.

    The comparison ignores case: macOS and Windows treat "IMG.jpg" and "img.JPG" as the same
    file, so extracting both from one ZIP would overwrite one of them.
    """
    taken = {p.name.casefold() for p in directory.iterdir()} if directory.is_dir() else set()
    if name.casefold() not in taken:
        return name
    path = Path(name)
    n = 2
    while (candidate := f"{path.stem} ({n}){path.suffix}").casefold() in taken:
        n += 1
    return candidate
