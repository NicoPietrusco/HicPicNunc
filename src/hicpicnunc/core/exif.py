"""
EXIF data extraction and embedding utilities (piexif-first for full IFD coverage).
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import piexif
from PIL import Image
from pillow_heif import register_heif_opener

from ..log import get_logger
from .metadata_fields import ExifFieldConfig, load_exif_field_config

logger = get_logger(__name__)

EXIF_DATE_FORMAT = "%Y:%m:%d %H:%M:%S"

# Lets Pillow open HEIC/HEIF, the default format of iPhone photos.
register_heif_opener()

IFD_CLASS_MAP: dict[str, type] = {
    "0th": piexif.ImageIFD,
    "Exif": piexif.ExifIFD,
    "GPS": piexif.GPSIFD,
    "Interop": piexif.InteropIFD,
    # Thumbnail IFD uses same tag namespace as ImageIFD in piexif
    "1st": piexif.ImageIFD,
}


def _tag_id_to_name(ifd_cls: type, tag_id: int) -> str:
    for attr in dir(ifd_cls):
        if attr.startswith("_"):
            continue
        try:
            if getattr(ifd_cls, attr, None) == tag_id:
                return attr
        except Exception:
            continue
    return f"Unknown_{tag_id}"


def _tag_name_to_id(ifd_cls: type, name: str) -> int | None:
    if not hasattr(ifd_cls, name):
        return None
    val = getattr(ifd_cls, name)
    return val if isinstance(val, int) else None


def _serialize_tag_value(val: Any) -> Any:
    """Make EXIF values JSON-safe, keeping human-readable byte values as text."""
    if isinstance(val, bytes):
        try:
            text = val.decode("utf-8").rstrip("\0")
            if text.isprintable():
                return text
        except UnicodeDecodeError:
            pass
        return {"__bytes_b64__": base64.standard_b64encode(val).decode("ascii")}
    if isinstance(val, (tuple, list)):
        return [_serialize_tag_value(v) for v in val]
    if hasattr(val, "numerator") and hasattr(val, "denominator"):  # PIL IFDRational
        try:
            return float(val)
        except ZeroDivisionError:
            return str(val)
    if isinstance(val, dict):
        return {k: _serialize_tag_value(v) for k, v in val.items()}
    try:
        json.dumps(val)
        return val
    except TypeError:
        return str(val)


def _deserialize_tag_value(val: Any) -> Any:
    if isinstance(val, dict) and "__bytes_b64__" in val:
        return base64.standard_b64decode(val["__bytes_b64__"])
    if isinstance(val, list):
        return tuple(_deserialize_tag_value(v) for v in val)
    return val


def convert_to_degrees(value: Any) -> float | None:
    """Convert GPS coordinates from DMS to decimal degrees."""
    try:
        if not value:
            return None
        if isinstance(value, (tuple, list)) and len(value) == 3:

            def get_fraction(frac: Any) -> float:
                if hasattr(frac, "numerator") and hasattr(frac, "denominator"):
                    return frac.numerator / frac.denominator
                if isinstance(frac, (tuple, list)) and len(frac) == 2:  # piexif (num, den)
                    num, den = frac
                    return num / den if den else 0.0
                if isinstance(frac, (int, float)):
                    return float(frac)
                return 0.0

            d, m, s = (get_fraction(v) for v in value)
            return d + (m / 60) + (s / 3600)
        return None
    except Exception:
        return None


def extract_gps_data_from_named_gps(gps_named: dict[str, Any]) -> dict[str, Any]:
    """Add decimal lat/lon to a GPS IFD dict keyed by piexif GPS tag names."""
    gps_dict = dict(gps_named)
    lat = lon = None
    if "GPSLatitude" in gps_dict and "GPSLatitudeRef" in gps_dict:
        raw_lat = _deserialize_tag_value(gps_dict["GPSLatitude"])
        lat = convert_to_degrees(raw_lat)
        ref = gps_dict["GPSLatitudeRef"]
        if isinstance(ref, bytes):
            ref = ref.decode("ascii", errors="ignore")
        if lat is not None and ref != "N":
            lat = -lat
    if "GPSLongitude" in gps_dict and "GPSLongitudeRef" in gps_dict:
        raw_lon = _deserialize_tag_value(gps_dict["GPSLongitude"])
        lon = convert_to_degrees(raw_lon)
        ref = gps_dict["GPSLongitudeRef"]
        if isinstance(ref, bytes):
            ref = ref.decode("ascii", errors="ignore")
        if lon is not None and ref != "E":
            lon = -lon
    gps_dict["LatitudeDecimal"] = lat
    gps_dict["LongitudeDecimal"] = lon
    return gps_dict


def piexif_raw_to_nested_named(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Convert piexif.load() output to {IFD: {TagName: value}}."""
    nested: dict[str, dict[str, Any]] = {}
    for ifd_key, ifd_data in raw.items():
        if ifd_key == "thumbnail" or ifd_data is None:
            continue
        if not isinstance(ifd_data, dict):
            continue
        cls = IFD_CLASS_MAP.get(ifd_key)
        if cls is None:
            continue
        named: dict[str, Any] = {}
        for tag_id, val in ifd_data.items():
            tname = _tag_id_to_name(cls, int(tag_id))
            named[tname] = val
        nested[ifd_key] = named
    return nested


def _parse_spec(tag_spec: str) -> tuple[str | None, str]:
    """Return (ifd_key or None, tag_name)."""
    s = tag_spec.strip()
    if ":" in s:
        ifd, name = s.split(":", 1)
        return ifd.strip(), name.strip()
    return None, s


def _spec_key(ifd_key: str, tag_name: str) -> str:
    return f"{ifd_key}:{tag_name}"


def filter_nested_exif(
    nested: dict[str, dict[str, Any]],
    config: ExifFieldConfig,
) -> dict[str, dict[str, Any]]:
    """Apply allowlist / exclude to nested EXIF dict."""
    # Build lookup: spec -> (ifd, name)
    specs_flat: list[tuple[str | None, str]] = [_parse_spec(t) for t in config.tags]
    exclude_set: set[str] = set()
    for x in config.exclude_tags:
        ik, tn = _parse_spec(x)
        if ik:
            exclude_set.add(_spec_key(ik, tn))
    exclude_pairs = []
    for x in config.exclude_tags:
        ik, tn = _parse_spec(x)
        if ik:
            exclude_pairs.append((ik, tn))
        else:
            exclude_pairs.append((None, tn))

    def excluded(ifd_key: str, tag_name: str) -> bool:
        if _spec_key(ifd_key, tag_name) in exclude_set:
            return True
        for ik, tn in exclude_pairs:
            if tn != tag_name:
                continue
            if ik is None or ik == ifd_key:
                return True
        return False

    if config.mode == "all":
        out: dict[str, dict[str, Any]] = {}
        for ifd_key, tags in nested.items():
            filt = {
                k: v
                for k, v in tags.items()
                if not excluded(ifd_key, k)
                and not (config.skip_makernote_embed and ifd_key == "Exif" and k == "MakerNote")
            }
            if filt:
                out[ifd_key] = filt
        return out

    # allowlist
    out = {k: {} for k in IFD_CLASS_MAP}
    for ifd_hint, tag_name in specs_flat:
        if ifd_hint:
            if (
                ifd_hint in nested
                and tag_name in nested[ifd_hint]
                and not excluded(ifd_hint, tag_name)
            ):
                out.setdefault(ifd_hint, {})[tag_name] = nested[ifd_hint][tag_name]
            continue
        for ifd_key, tags in nested.items():
            if tag_name in tags and not excluded(ifd_key, tag_name):
                out.setdefault(ifd_key, {})[tag_name] = tags[tag_name]
                break
    return {k: v for k, v in out.items() if v}


def nested_named_to_piexif_raw(nested: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Convert filtered nested dict back to piexif integer keys."""
    raw: dict[str, Any] = {}
    for ifd_key, tags in nested.items():
        cls = IFD_CLASS_MAP.get(ifd_key)
        if cls is None:
            continue
        ifd_out: dict[int, Any] = {}
        for tag_name, val in tags.items():
            if val is None:
                continue
            tid = _tag_name_to_id(cls, tag_name)
            if tid is None:
                logger.debug(f"Unknown tag name {ifd_key}:{tag_name}, skip embed")
                continue
            if isinstance(val, dict) and "__bytes_b64__" in val:
                val = _deserialize_tag_value(val)
            ifd_out[tid] = val
        if ifd_out:
            raw[ifd_key] = ifd_out
    return raw


def load_exif_nested(
    image_path: Path,
) -> tuple[dict[str, dict[str, Any]], bool, dict[str, Any]]:
    """
    Load EXIF as nested IFD dict. Returns (nested, used_piexif, file_info).

    piexif reads JPEG, TIFF and WebP files directly; for other formats (PNG, HEIC, ...)
    Pillow extracts the raw EXIF block and piexif parses it, so the Exif and GPS
    sub-IFDs (capture date, location) are kept.
    """
    with Image.open(image_path) as img:
        file_info = {
            "filename": image_path.name,
            "size_bytes": image_path.stat().st_size,
            "format": img.format,
            "mode": img.mode,
            "size": img.size,
        }
        exif_block = img.info.get("exif") or img.getexif().tobytes()

    for source in (str(image_path), exif_block):
        try:
            nested = piexif_raw_to_nested_named(piexif.load(source))
        except Exception as e:
            logger.debug("piexif could not read EXIF of {}: {}", image_path.name, e)
            continue
        if any(nested.values()):
            return nested, True, file_info
    return {}, False, file_info


def extract_exif_data(
    image_path: Path,
    output_dir: Path,
    field_config: ExifFieldConfig | None = None,
    write_json: bool = True,
    json_stem_name: str | None = None,
) -> dict[str, Any]:
    """
    Extract EXIF using piexif-first pipeline, filter by config, save JSON.

    If json_stem_name is set, the JSON file is named {json_stem_name}.json (used when
    aligning names with output images from a chosen original basename). Otherwise the
    stem of image_path is used (legacy behaviour for Google / temp uploads).
    """
    if field_config is None:
        field_config = load_exif_field_config()

    if not image_path.exists():
        return {"error": f"File not found: {image_path}"}

    try:
        nested, used_piexif, file_info = load_exif_nested(image_path)
        filtered = filter_nested_exif(nested, field_config)

        display: dict[str, Any] = {}
        for ifd_key, tags in filtered.items():
            if ifd_key == "GPS" and tags:
                enriched = extract_gps_data_from_named_gps(tags)
                display["GPS"] = {k: _serialize_tag_value(v) for k, v in enriched.items()}
            else:
                display[ifd_key] = {k: _serialize_tag_value(v) for k, v in tags.items()}

        display["_file_info"] = file_info
        display["_meta"] = {"used_piexif": used_piexif}

        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / f"{json_stem_name or image_path.stem}.json" if write_json else None

        if json_path:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(display, f, indent=2, ensure_ascii=False)

        total_fields = sum(len(v) for k, v in filtered.items() if k != "_meta")
        return {
            "success": True,
            "image_path": str(image_path),
            "json_path": str(json_path) if json_path else None,
            "exif_fields_count": total_fields,
            "nested_filtered": filtered,
        }
    except Exception as e:
        return {"error": f"Failed: {e}"}


def _save_with_pillow(image_path: Path, output_path: Path, exif_bytes: bytes | None) -> None:
    """Re-save a non-JPEG image with the given EXIF (or none)."""
    with Image.open(image_path) as img:
        save_kw: dict[str, Any] = {}
        if exif_bytes is not None:
            save_kw["exif"] = exif_bytes
        # Pillow only carries the color profile over for some formats (not WebP).
        if icc_profile := img.info.get("icc_profile"):
            save_kw["icc_profile"] = icc_profile
        if image_path.suffix.lower() in {".webp", ".heic", ".heif"}:
            save_kw["quality"] = 95  # lossy formats: libheif's default (50) visibly degrades
        img.save(output_path, format=img.format or "JPEG", **save_kw)


def embed_exif_subset(
    image_path: Path,
    output_path: Path,
    field_config: ExifFieldConfig | None = None,
) -> bool:
    """
    Write a new image with EXIF limited to filtered tags (JPEG via piexif.insert).

    Returns True when output_path was written, even if no tags survived the filter.
    """
    if field_config is None:
        field_config = load_exif_field_config()

    try:
        nested, _, _ = load_exif_nested(image_path)
        filtered = filter_nested_exif(nested, field_config)
        if (
            field_config.skip_makernote_embed
            and "Exif" in filtered
            and "MakerNote" in filtered["Exif"]
        ):
            del filtered["Exif"]["MakerNote"]
            if not filtered["Exif"]:
                del filtered["Exif"]

        raw = nested_named_to_piexif_raw(filtered)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        suffix = image_path.suffix.lower()
        if not raw:
            # Still write the photo, but never carry over tags the user excluded.
            logger.info("No EXIF to embed for {}; saving without EXIF", image_path.name)
            if not nested:
                shutil.copyfile(image_path, output_path)
            elif suffix in {".jpg", ".jpeg"}:
                shutil.copyfile(image_path, output_path)
                piexif.remove(str(output_path))
            else:
                _save_with_pillow(image_path, output_path, exif_bytes=None)
            return True

        exif_bytes = piexif.dump(raw)
        if suffix in {".jpg", ".jpeg"}:
            piexif.insert(exif_bytes, str(image_path), str(output_path))
            return True
        try:
            _save_with_pillow(image_path, output_path, exif_bytes)
            return True
        except Exception as e2:
            logger.warning(f"Pillow EXIF save not supported for {suffix}: {e2}")
            return False
    except Exception as e:
        logger.error(f"embed_exif_subset failed for {image_path.name}: {e}")
        return False


_OFFSET_RE = re.compile(r"^([+-])(\d{2}):(\d{2})$")

# Each capture-date tag and the tag holding its UTC offset (EXIF 2.31).
_DATE_TAGS = (
    (("Exif", "DateTimeOriginal"), ("Exif", "OffsetTimeOriginal")),
    (("Exif", "DateTimeDigitized"), ("Exif", "OffsetTimeDigitized")),
    (("0th", "DateTime"), ("Exif", "OffsetTime")),
)


def _exif_text(value: Any) -> str:
    text = value.decode("ascii", errors="ignore") if isinstance(value, bytes) else str(value)
    return text.strip().rstrip("\x00").strip()


def _utc_offset(value: Any) -> timezone | None:
    """Parse an EXIF offset such as "+02:00"; None when missing or malformed."""
    match = _OFFSET_RE.match(_exif_text(value)) if value else None
    if not match:
        return None
    sign, hours, minutes = match.groups()
    delta = timedelta(hours=int(hours), minutes=int(minutes))
    return timezone(-delta if sign == "-" else delta)


def exif_capture_timestamp(nested_exif: dict[str, dict[str, Any]]) -> float | None:
    """
    POSIX timestamp of the best available capture date, or None.

    EXIF dates are local wall-clock times. With their offset tag they map to an exact
    instant; without one they are read in the exporting computer's time zone, which is
    right for photos taken where they are exported.
    """
    for (ifd_key, tag_name), (offset_ifd, offset_tag) in _DATE_TAGS:
        raw = nested_exif.get(ifd_key, {}).get(tag_name)
        if not raw:
            continue
        try:
            taken = datetime.strptime(_exif_text(raw), EXIF_DATE_FORMAT)
        except ValueError:
            continue  # e.g. "0000:00:00 00:00:00": try the next date tag
        offset = _utc_offset(nested_exif.get(offset_ifd, {}).get(offset_tag))
        return (taken.replace(tzinfo=offset) if offset else taken).timestamp()
    return None


def apply_exif_timestamp(output_path: Path, nested_exif: dict[str, dict[str, Any]]) -> bool:
    """Set an output file's modification time from its best available EXIF capture date."""
    timestamp = exif_capture_timestamp(nested_exif)
    if timestamp is None:
        return False
    try:
        os.utime(output_path, (timestamp, timestamp))
    except OSError as e:
        logger.warning("Could not set filesystem date for {}: {}", output_path.name, e)
        return False
    return True


def process_image_extract_and_embed(
    image_path: Path,
    output_dir: Path,
    field_config: ExifFieldConfig | None = None,
    stem_suffix: str = "_exif",
    output_stem: str | None = None,
    write_json: bool = True,
) -> dict[str, Any]:
    """
    Extract filtered EXIF, optionally save JSON, and save a new image with embedded subset.

    The image is saved as output_stem (default: image_path's stem) plus stem_suffix plus
    image_path's extension; the JSON sidecar, if any, as that name plus ".json".

    Returns paths and status for Flask / API use.
    """
    if field_config is None:
        field_config = load_exif_field_config()

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stem_base = output_stem if output_stem is not None else image_path.stem
    out_name = f"{stem_base}{stem_suffix}{image_path.suffix}"
    # The sidecar keeps the image's full name ("IMG.jpg.json"), so IMG.jpg and IMG.heic
    # never share one.
    ext_result = extract_exif_data(
        image_path, output_dir, field_config, write_json=write_json, json_stem_name=out_name
    )
    if "error" in ext_result:
        return ext_result

    output_image = output_dir / out_name

    ok = embed_exif_subset(image_path, output_image, field_config)
    if not ok or not output_image.is_file():
        return {"error": f"Could not save {image_path.suffix.lstrip('.').upper()} image"}
    filesystem_date_set = apply_exif_timestamp(output_image, ext_result["nested_filtered"])
    return {
        "success": True,
        "image_path": str(image_path),
        "json_path": ext_result.get("json_path"),
        "output_image": str(output_image),
        "embed_ok": ok,
        "filesystem_date_set": filesystem_date_set,
        "exif_fields_count": ext_result.get("exif_fields_count", 0),
    }
