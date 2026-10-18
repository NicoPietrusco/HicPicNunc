"""Tests for hicpicnunc.web.routes.home."""

from __future__ import annotations

import json


def test_index_renders_saved_preferences(client) -> None:
    client.post("/api/metadata-preferences", json={"preferences": {"gps_location": False}})

    page = client.get("/").get_data(as_text=True)

    assert 'id="metadata-gps-location" checked' not in page
    assert 'id="metadata-camera-details" checked' in page


def test_preferences_are_saved_to_disk(client, data_dir) -> None:
    resp = client.post(
        "/api/metadata-preferences", json={"preferences": {"camera_details": False, "x": 1}}
    )

    assert resp.get_json() == {
        "ok": True,
        "preferences": {"camera_details": False, "gps_location": True, "include_json": False},
    }
    saved = json.loads((data_dir / "settings" / "metadata_preferences.json").read_text())
    assert saved["camera_details"] is False


def test_preferences_must_be_an_object(client) -> None:
    assert client.post("/api/metadata-preferences", json={"preferences": []}).status_code == 400
    assert client.post("/api/metadata-preferences", data="nope").status_code == 400
