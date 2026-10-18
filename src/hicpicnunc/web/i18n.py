"""
Interface translations: one flat JSON catalog per language in ``locales/``.

English is the source language and the fallback for any missing key. A plural string is
an object keyed by CLDR plural category ("one", "other", ...). Keys ending in ``_html``
hold trusted markup, and the values put into them are escaped. Keys starting with
``js.`` are the strings the page's scripts need; ``js_catalog`` sends them to the page.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path

from flask import g, has_request_context, request
from markupsafe import Markup, escape

LOCALES_DIR = Path(__file__).resolve().parent / "locales"
DEFAULT_LANGUAGE = "en"
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")

Message = str | dict[str, str]


@cache
def load_catalog(lang: str) -> dict[str, Message]:
    with (LOCALES_DIR / f"{lang}.json").open(encoding="utf-8") as f:
        return json.load(f)


@cache
def available_languages() -> tuple[str, ...]:
    """Every language with a catalog; adding a language means adding its JSON file."""
    return tuple(sorted(path.stem for path in LOCALES_DIR.glob("*.json")))


def current_language() -> str:
    """The browser's most preferred language we have, chosen once per request.

    Only the primary subtag counts, so "en-US, it;q=0.5" stays English. Werkzeug's
    ``best_match`` would pick Italian there, since only "it" matches exactly.
    """
    if not has_request_context():
        return DEFAULT_LANGUAGE
    if "lang" not in g:
        g.lang = DEFAULT_LANGUAGE
        for value, _quality in request.accept_languages:  # most preferred first
            primary = re.split(r"[-_]", value, maxsplit=1)[0].lower()
            if primary in available_languages():
                g.lang = primary
                break
    return g.lang


def plural_category(lang: str, count: int) -> str:
    """CLDR plural category of a whole number.

    English and Italian only tell "one" from "other". A language with more categories
    (e.g. Polish "few" and "many") needs its own rule here.
    """
    return "one" if count == 1 else "other"


def _lookup(key: str, lang: str) -> Message:
    for code in (lang, DEFAULT_LANGUAGE):
        message = load_catalog(code).get(key)
        if message is not None:
            return message
    return key


def _format(key: str, text: str, variables: dict[str, object]) -> str:
    is_html = key.endswith("_html")

    def substitute(match: re.Match[str]) -> str:
        name = match[1]
        if name not in variables:
            return match[0]
        return str(escape(variables[name])) if is_html else str(variables[name])

    result = _PLACEHOLDER_RE.sub(substitute, text)
    return Markup(result) if is_html else result


def t(key: str, **variables: object) -> str:
    """The current language's text for ``key``, with ``{name}`` placeholders filled in."""
    message = _lookup(key, current_language())
    if isinstance(message, dict):
        message = message.get("other", key)
    return _format(key, message, variables)


def tn(key: str, count: int, **variables: object) -> str:
    """Like ``t`` for a plural string: picks the form for ``count``, also passed as ``{count}``."""
    lang = current_language()
    message = _lookup(key, lang)
    if isinstance(message, dict):
        message = message.get(plural_category(lang, count)) or message.get("other", key)
    return _format(key, message, {"count": count, **variables})


def js_catalog() -> dict[str, object]:
    """The ``js.`` strings for the current language, English filling any gaps."""
    lang = current_language()
    merged = {**load_catalog(DEFAULT_LANGUAGE), **load_catalog(lang)}
    return {"lang": lang, "strings": {k: v for k, v in merged.items() if k.startswith("js.")}}
