"""Tests for hicpicnunc.web.i18n."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hicpicnunc.web import i18n
from hicpicnunc.web.i18n import (
    DEFAULT_LANGUAGE,
    available_languages,
    js_catalog,
    load_catalog,
    plural_category,
    t,
    tn,
)

WEB_DIR = Path(i18n.__file__).resolve().parent
TRANSLATIONS = [lang for lang in available_languages() if lang != DEFAULT_LANGUAGE]
JOB_ID = "0f8fad5b-d9cb-469f-a165-70867728950e"


def _placeholders(message: i18n.Message) -> set[str]:
    texts = message.values() if isinstance(message, dict) else [message]
    return {name for text in texts for name in re.findall(r"\{(\w+)\}", text)}


def _used_keys() -> set[str]:
    """Every catalog key the templates, routes and scripts ask for."""
    keys: set[str] = set()
    call = re.compile(r"\btn?\(\s*[\"']([\w.]+)[\"']")
    for path in [*(WEB_DIR / "templates").glob("*.html"), *WEB_DIR.rglob("*.py")]:
        keys |= set(call.findall(path.read_text(encoding="utf-8")))
    for path in (WEB_DIR / "static" / "js").glob("*.js"):
        keys |= set(re.findall(r"[\"'](js\.[\w.]+)[\"']", path.read_text(encoding="utf-8")))
    return keys


def test_italian_is_available() -> None:
    assert available_languages() == ("en", "it")


@pytest.mark.parametrize("lang", TRANSLATIONS)
def test_every_english_key_is_translated(lang: str) -> None:
    missing = load_catalog(DEFAULT_LANGUAGE).keys() - load_catalog(lang).keys()

    assert not missing, f"{lang}.json is missing: {sorted(missing)}"


@pytest.mark.parametrize("lang", TRANSLATIONS)
def test_translations_have_no_stale_keys(lang: str) -> None:
    stale = load_catalog(lang).keys() - load_catalog(DEFAULT_LANGUAGE).keys()

    assert not stale, f"{lang}.json has keys English no longer uses: {sorted(stale)}"


@pytest.mark.parametrize("lang", TRANSLATIONS)
def test_translations_keep_the_placeholders(lang: str) -> None:
    english = load_catalog(DEFAULT_LANGUAGE)
    for key, message in load_catalog(lang).items():
        if key in english:
            assert _placeholders(message) == _placeholders(english[key]), key


@pytest.mark.parametrize("lang", available_languages())
def test_plural_strings_have_every_form_the_language_needs(lang: str) -> None:
    needed = {plural_category(lang, n) for n in range(200)}
    english = load_catalog(DEFAULT_LANGUAGE)
    for key, message in load_catalog(lang).items():
        assert isinstance(message, dict) == isinstance(english.get(key), dict), key
        if isinstance(message, dict):
            assert needed <= message.keys(), key


def test_every_key_in_use_exists() -> None:
    unknown = _used_keys() - load_catalog(DEFAULT_LANGUAGE).keys()

    assert not unknown, f"Keys used in code but missing from en.json: {sorted(unknown)}"


@pytest.mark.parametrize(
    ("accept_language", "lang"),
    [
        (None, "en"),
        ("it", "it"),
        ("it-IT,it;q=0.9,en;q=0.8", "it"),
        ("fr-FR, it;q=0.5", "it"),
        ("de-DE", "en"),
        ("en-US,it;q=0.5", "en"),
        ("IT_it", "it"),
        ("*", "en"),
    ],
)
def test_language_follows_accept_language(client, accept_language, lang: str) -> None:
    headers = {"Accept-Language": accept_language} if accept_language else {}

    page = client.get("/", headers=headers).get_data(as_text=True)

    assert f'<html lang="{lang}">' in page


def test_home_page_in_italian(client) -> None:
    page = client.get("/", headers={"Accept-Language": "it"}).get_data(as_text=True)

    assert "Esporta la tua libreria" in page
    assert "Impostazioni" in page
    assert "Export your library" not in page


def test_result_page_in_italian_uses_plurals(client, data_dir) -> None:
    job_dir = data_dir / "data" / "outputs" / JOB_ID
    job_dir.mkdir(parents=True)
    for i, name in enumerate(["IMG_1_exif.jpg", "IMG_2_exif.jpg", "VID_1.mp4"]):
        (job_dir / f"{JOB_ID}_{i}_{name}").write_bytes(b"x")

    resp = client.get(f"/job/{JOB_ID}?failed=1", headers={"Accept-Language": "it"})
    page = " ".join(resp.get_data(as_text=True).split())

    assert "<strong>3</strong> file: 2 immagini, 1 video" in page
    assert "1 elemento non è stato salvato." in page
    assert "Scarica lo ZIP" in page


def test_flash_messages_are_translated(client, make_jpeg) -> None:
    resp = client.post(
        "/upload",
        data={"file": (make_jpeg().open("rb"), "IMG.jpg"), "include_json": "false"},
        headers={"Accept-Language": "it"},
        follow_redirects=True,
    )

    assert "Fatto. Metadati salvati per 1 immagine." in resp.get_data(as_text=True)


def test_page_receives_the_script_strings(app) -> None:
    with app.test_request_context(headers={"Accept-Language": "it"}):
        catalog = js_catalog()

    assert catalog["lang"] == "it"
    assert catalog["strings"]["js.picker.exporting"] == "Esportazione in corso…"
    assert all(key.startswith("js.") for key in catalog["strings"])


def test_plural_forms_follow_the_count(app) -> None:
    with app.test_request_context(headers={"Accept-Language": "it"}):
        assert tn("js.picker.minutes_left", 1) == "manca circa 1 minuto"
        assert tn("js.picker.minutes_left", 3) == "mancano circa 3 minuti"
        assert tn("job.image_count", 0) == "0 immagini"


def test_html_keys_escape_their_values(app) -> None:
    with app.test_request_context():
        text = t("local.suffix_hint_html", suffix="<b>")

    assert text == "New copies use the &lt;b&gt; suffix."


def test_missing_keys_fall_back_to_english_then_to_the_key(app, monkeypatch) -> None:
    catalogs = {"en": {"only.english": "Hello {name}"}, "it": {}}
    monkeypatch.setattr(i18n, "load_catalog", catalogs.__getitem__)

    with app.test_request_context(headers={"Accept-Language": "it"}):
        assert t("only.english", name="Ada") == "Hello Ada"
        assert t("no.such.key") == "no.such.key"
        assert tn("no.such.key", 2) == "no.such.key"


def test_placeholders_without_a_value_are_left_as_they_are() -> None:
    assert t("js.picker.progress_count", done=1) == "1 of {total}"


def test_t_on_a_plural_string_uses_the_other_form() -> None:
    assert t("job.image_count", count=2) == "2 images"


def test_outside_a_request_english_is_used() -> None:
    assert t("settings.title") == "Settings"
