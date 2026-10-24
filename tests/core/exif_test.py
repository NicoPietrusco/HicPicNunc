"""Tests for hicpicnunc.core.exif."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import piexif
import pytest
from PIL import Image, ImageCms

from hicpicnunc.core.exif import (
    convert_to_degrees,
    exif_capture_timestamp,
    process_image_extract_and_embed,
)
from hicpicnunc.core.metadata_fields import ExifFieldConfig, build_exif_field_config


def _export(src: Path, config: ExifFieldConfig) -> dict:
    return process_image_extract_and_embed(src, src.parent / "out", config, write_json=False)


def test_image_without_exif_is_still_exported(make_jpeg) -> None:
    result = _export(make_jpeg("plain.jpg"), build_exif_field_config({}))

    assert "error" not in result
    assert Path(result["output_image"]).is_file()


def test_png_without_exif_is_still_exported(tmp_path: Path) -> None:
    src = tmp_path / "screenshot.png"
    Image.new("RGB", (8, 8)).save(src)

    assert Path(_export(src, build_exif_field_config({}))["output_image"]).is_file()


def test_excluded_gps_is_not_carried_over_when_nothing_else_survives(make_jpeg) -> None:
    src = make_jpeg(
        "gps_only.jpg",
        {
            "GPS": {
                piexif.GPSIFD.GPSLatitudeRef: b"N",
                piexif.GPSIFD.GPSLatitude: ((45, 1), (0, 1), (0, 1)),
            }
        },
    )
    result = _export(src, build_exif_field_config({"gps_location": False}))

    assert not piexif.load(result["output_image"])["GPS"]


def test_only_allowlisted_tags_are_embedded(make_jpeg) -> None:
    src = make_jpeg(
        "portrait.jpg",
        {"0th": {piexif.ImageIFD.Orientation: 6, piexif.ImageIFD.Make: b"Cam"}},
    )
    exif = piexif.load(_export(src, ExifFieldConfig(tags=["0th:Orientation"]))["output_image"])

    assert exif["0th"] == {piexif.ImageIFD.Orientation: 6}


def test_file_date_matches_capture_date(make_jpeg) -> None:
    src = make_jpeg(
        "dated.jpg", {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2019:01:02 03:04:05"}}
    )
    result = _export(src, build_exif_field_config({}))

    assert result["filesystem_date_set"]
    assert os.path.getmtime(result["output_image"]) == datetime(2019, 1, 2, 3, 4, 5).timestamp()


def test_json_sidecar_has_readable_values_and_decimal_gps(make_jpeg) -> None:
    src = make_jpeg(
        "trip.jpg",
        {
            "0th": {piexif.ImageIFD.Make: b"Cam"},
            "GPS": {
                piexif.GPSIFD.GPSLatitudeRef: b"S",
                piexif.GPSIFD.GPSLatitude: ((33, 1), (30, 1), (0, 1)),
                piexif.GPSIFD.GPSLongitudeRef: b"E",
                piexif.GPSIFD.GPSLongitude: ((151, 1), (15, 1), (0, 1)),
            },
        },
    )
    result = process_image_extract_and_embed(
        src, src.parent / "out", build_exif_field_config({}), write_json=True
    )
    sidecar = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))

    assert sidecar["0th"]["Make"] == "Cam"
    assert sidecar["GPS"]["LatitudeDecimal"] == -33.5
    assert sidecar["GPS"]["LongitudeDecimal"] == 151.25


def test_output_stem_and_suffix_control_the_output_name(make_jpeg) -> None:
    result = process_image_extract_and_embed(
        make_jpeg("upload_0_IMG.jpg"),
        make_jpeg().parent / "out",
        build_exif_field_config({}),
        stem_suffix="",
        output_stem="IMG_1234",
        write_json=False,
    )

    assert Path(result["output_image"]).name == "IMG_1234.jpg"


def test_unreadable_image_reports_an_error(tmp_path: Path) -> None:
    src = tmp_path / "broken.jpg"
    src.write_bytes(b"not an image")

    result = _export(src, build_exif_field_config({}))

    assert result["error_code"] == "unreadable"
    assert str(tmp_path) not in result["error"]  # no temporary path in what users see


def test_convert_to_degrees_handles_rationals_and_bad_input() -> None:
    assert convert_to_degrees(((10, 1), (30, 1), (36, 1))) == pytest.approx(10.51)  # piexif
    assert convert_to_degrees((10, 30, 36)) == pytest.approx(10.51)
    assert convert_to_degrees(None) is None
    assert convert_to_degrees("garbage") is None


@pytest.fixture(scope="module")
def srgb_profile() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


@pytest.mark.parametrize("ext", ["png", "webp", "tiff"])
@pytest.mark.parametrize("with_exif", [False, True], ids=["no-exif", "exif"])
def test_reencoded_copies_keep_their_color_profile(
    tmp_path: Path, srgb_profile: bytes, ext: str, with_exif: bool
) -> None:
    src = tmp_path / f"wide-gamut.{ext}"
    save_kw: dict = {"icc_profile": srgb_profile}
    if with_exif:
        save_kw["exif"] = piexif.dump(
            {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2021:07:08 09:10:11"}}
        )
    Image.new("RGB", (16, 16), "red").save(src, **save_kw)

    out = Path(_export(src, build_exif_field_config({}))["output_image"])

    with Image.open(out) as img:
        assert img.info.get("icc_profile") == srgb_profile


def test_images_without_a_color_profile_stay_without_one(tmp_path: Path) -> None:
    src = tmp_path / "plain.webp"
    Image.new("RGB", (16, 16), "red").save(src)

    out = Path(_export(src, build_exif_field_config({}))["output_image"])

    with Image.open(out) as img:
        assert not img.info.get("icc_profile")


def _utc(*args: int) -> float:
    return datetime(*args, tzinfo=UTC).timestamp()


@pytest.mark.parametrize(
    ("exif", "expected"),
    [
        # Taken at 16:03 in New York: the same instant wherever it's exported.
        (
            {"Exif": {"DateTimeOriginal": b"2022:08:05 16:03:22", "OffsetTimeOriginal": b"-04:00"}},
            _utc(2022, 8, 5, 20, 3, 22),
        ),
        (
            {"Exif": {"DateTimeOriginal": b"2022:08:05 16:03:22", "OffsetTimeOriginal": b"+05:30"}},
            _utc(2022, 8, 5, 10, 33, 22),
        ),
        # Each date tag uses its own offset tag.
        (
            {
                "Exif": {
                    "DateTimeDigitized": b"2022:08:05 16:03:22",
                    "OffsetTimeDigitized": b"+02:00",
                }
            },
            _utc(2022, 8, 5, 14, 3, 22),
        ),
        (
            {"0th": {"DateTime": b"2022:08:05 16:03:22"}, "Exif": {"OffsetTime": b"+00:00"}},
            _utc(2022, 8, 5, 16, 3, 22),
        ),
        # An unreadable original date falls through to the next date tag.
        (
            {
                "Exif": {
                    "DateTimeOriginal": b"0000:00:00 00:00:00",
                    "DateTimeDigitized": b"2022:08:05 16:03:22",
                    "OffsetTimeDigitized": b"-04:00",
                }
            },
            _utc(2022, 8, 5, 20, 3, 22),
        ),
        # Padding some cameras leave in EXIF strings is ignored.
        (
            {
                "Exif": {
                    "DateTimeOriginal": b"2022:08:05 16:03:22\x00",
                    "OffsetTimeOriginal": b"-04:00\x00",
                }
            },
            _utc(2022, 8, 5, 20, 3, 22),
        ),
    ],
)
def test_capture_timestamp_uses_the_photo_time_zone(exif: dict, expected: float) -> None:
    assert exif_capture_timestamp(exif) == expected


@pytest.mark.parametrize("offset", [None, b"", b"garbage", b"+2:00"])
def test_capture_timestamp_without_a_usable_offset_uses_local_time(offset) -> None:
    exif = {"Exif": {"DateTimeOriginal": b"2022:08:05 16:03:22"}}
    if offset is not None:
        exif["Exif"]["OffsetTimeOriginal"] = offset

    assert exif_capture_timestamp(exif) == datetime(2022, 8, 5, 16, 3, 22).timestamp()


def test_capture_timestamp_is_none_without_a_readable_date() -> None:
    assert exif_capture_timestamp({}) is None
    assert exif_capture_timestamp({"Exif": {"DateTimeOriginal": b"0000:00:00 00:00:00"}}) is None


def test_exported_file_date_follows_the_photo_time_zone(make_jpeg) -> None:
    src = make_jpeg(
        "nyc.jpg",
        {
            "Exif": {
                piexif.ExifIFD.DateTimeOriginal: b"2022:08:05 16:03:22",
                piexif.ExifIFD.OffsetTimeOriginal: b"-04:00",
            }
        },
    )

    result = _export(src, build_exif_field_config({}))

    assert os.path.getmtime(result["output_image"]) == _utc(2022, 8, 5, 20, 3, 22)
