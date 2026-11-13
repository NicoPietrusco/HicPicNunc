"""Parsing and validation of client-supplied form/JSON values."""

from __future__ import annotations

import re

from ..core.filenames import safe_filename

_STEM_SUFFIX_RE = re.compile(r"^(_?[a-zA-Z0-9_-]{0,63})$")


def parse_stem_suffix(raw: str | None) -> str:
    """Allow empty (overwrite-style names) or a short safe suffix such as _exif."""
    if raw is None or not str(raw).strip():
        return ""
    s = str(raw).strip()
    return s if _STEM_SUFFIX_RE.fullmatch(s) else ""


def parse_bool(raw: object, default: bool = True) -> bool:
    """Parse a form or JSON boolean while preserving backward-compatible defaults."""
    if raw is None:
        return default
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def sanitize_relative_path(rel: str) -> str | None:
    """
    Normalize a client-provided relative path (folder uploads) with the export file-name
    rules; reject path traversal and empty segments.
    """
    if not rel or "\0" in rel:
        return None
    r = rel.replace("\\", "/").strip().strip("/")
    if not r:
        return None
    parts = [safe_filename(p) if p not in (".", "..") else "" for p in r.split("/")]
    if not all(parts):
        return None
    return "/".join(parts)
