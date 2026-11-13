"""
EXIF field selection for extract and embed, defined in metadata_fields.yaml.
"""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from ..log import get_logger
from ..settings import settings

logger = get_logger(__name__)

_DEFAULT_YAML = Path(__file__).resolve().with_suffix(".yaml")


@dataclass
class ExifFieldConfig:
    """Controls which EXIF tags are extracted and re-embedded."""

    mode: str = "allowlist"  # "allowlist" | "all"
    tags: list[str] = field(default_factory=list)
    exclude_tags: list[str] = field(default_factory=list)
    skip_makernote_embed: bool = True


@dataclass(frozen=True)
class MetadataFieldCatalog:
    """Tags from the YAML config: always kept, plus user-toggleable groups."""

    always_kept: tuple[str, ...]
    groups: dict[str, tuple[str, ...]]
    skip_makernote_embed: bool = True


def _tag_list(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(t, str) for t in value):
        raise ValueError(f"{where} must be a list of 'IFD:TagName' strings")
    return tuple(value)


@cache
def _load_catalog(path: Path) -> MetadataFieldCatalog:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: root must be a mapping")
    groups = data.get("groups") or {}
    if not isinstance(groups, dict):
        raise ValueError(f"{path}: groups must be a mapping")
    return MetadataFieldCatalog(
        always_kept=_tag_list(data.get("always_kept", []), f"{path}: always_kept"),
        groups={str(k): _tag_list(v, f"{path}: groups.{k}") for k, v in groups.items()},
        skip_makernote_embed=bool(data.get("skip_makernote_embed", True)),
    )


def load_field_catalog() -> MetadataFieldCatalog:
    """Load the bundled YAML, or the file named by EXIF_FIELDS_CONFIG."""
    return _load_catalog(Path(os.environ.get("EXIF_FIELDS_CONFIG") or _DEFAULT_YAML))


def default_metadata_preferences() -> dict[str, bool]:
    """Every group from the catalog is on by default; the JSON sidecar is off."""
    return {**dict.fromkeys(load_field_catalog().groups, True), "include_json": False}


def load_metadata_preferences(path: Path | None = None) -> dict[str, bool]:
    """Load saved user choices, falling back to the shipped defaults."""
    preferences = default_metadata_preferences()
    preferences_path = path or settings.metadata_preferences_path
    try:
        data = json.loads(preferences_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key in preferences:
                if isinstance(data.get(key), bool):
                    preferences[key] = data[key]
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Could not read metadata preferences: {}", e)
    return preferences


def save_metadata_preferences(
    preferences: dict[str, Any], path: Path | None = None
) -> dict[str, bool]:
    """Validate and persist the user's metadata choices atomically."""
    normalized = default_metadata_preferences()
    for key in normalized:
        value = preferences.get(key)
        if isinstance(value, bool):
            normalized[key] = value

    preferences_path = path or settings.metadata_preferences_path
    preferences_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = preferences_path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(normalized, indent=2) + "\n", encoding="utf-8")
    with contextlib.suppress(OSError):
        temporary_path.chmod(0o600)
    temporary_path.replace(preferences_path)
    return normalized


def build_exif_field_config(preferences: dict[str, bool]) -> ExifFieldConfig:
    """Turn user choices into an EXIF allowlist using the YAML catalog."""
    catalog = load_field_catalog()
    tags = list(catalog.always_kept)
    for group, group_tags in catalog.groups.items():
        if preferences.get(group, True):
            tags.extend(group_tags)
    return ExifFieldConfig(tags=tags, skip_makernote_embed=catalog.skip_makernote_embed)


def load_user_exif_field_config(path: Path | None = None) -> ExifFieldConfig:
    """Build the EXIF allowlist from locally saved user preferences."""
    return build_exif_field_config(load_metadata_preferences(path))


def load_exif_field_config() -> ExifFieldConfig:
    """EXIF allowlist with every group enabled (default for programmatic use)."""
    return build_exif_field_config(default_metadata_preferences())
