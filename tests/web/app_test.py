"""Tests for hicpicnunc.web.app."""

from __future__ import annotations

import pytest

from hicpicnunc.web.app import is_local_host_header


@pytest.mark.parametrize(
    "host", ["localhost:5001", "127.0.0.1", "[::1]:5001", "[::1]", "LOCALHOST"]
)
def test_loopback_hosts_are_served(client, host: str) -> None:
    assert is_local_host_header(host)
    assert client.get("/", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("host", ["evil.example:5001", "127.0.0.1.evil.example", "localhost.evil"])
def test_foreign_host_header_is_rejected(client, host: str) -> None:
    # A DNS-rebinding page reaches 127.0.0.1 but still sends its own hostname.
    assert client.get("/api/check-auth", headers={"Host": host}).status_code == 403


def test_create_app_prepares_writable_folders(app, data_dir) -> None:
    assert (data_dir / "data" / "uploads").is_dir()
    assert (data_dir / "data" / "outputs").is_dir()


def test_templates_see_google_setup_state(client) -> None:
    # No client_secrets.json in the temp data dir's resource tree is required for the page.
    assert b"Hic Pic Nunc" in client.get("/").data


def test_footer_links_the_privacy_policy_and_home_only_off_the_home_page(client, make_jpeg) -> None:
    home = client.get("/").get_data(as_text=True)
    upload = client.post(
        "/upload",
        data={"file": (make_jpeg().open("rb"), "IMG.jpg"), "include_json": "false"},
        headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
    ).get_json()
    job_page = client.get(upload["job_url"]).get_data(as_text=True)

    assert "privacy.html" in home and "privacy.html" in job_page
    assert "Back to home" not in home
    assert "Back to home" in job_page
