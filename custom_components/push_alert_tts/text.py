"""Turn Pushover messages into the text that is spoken."""

from __future__ import annotations

import html
import re
from collections.abc import Iterable, Mapping
from typing import Any

from .api import as_int
from .const import (
    CONF_APP_FILTER,
    CONF_FIXED_MESSAGE,
    CONF_MAX_LENGTH,
    CONF_MESSAGE_MODE,
    CONF_MIN_PRIORITY,
    CONF_MULTIPLE_MESSAGE,
    CONF_REGEX,
    DEFAULT_FIXED_MESSAGE,
    DEFAULT_MAX_LENGTH,
    DEFAULT_MIN_PRIORITY,
    DEFAULT_MULTIPLE_MESSAGE,
    MODE_FIXED,
    MODE_FULL,
    MODE_REGEX,
    MODE_TITLE,
)

_TAG_RE = re.compile(r"<[^>]+>")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")
REGEX_FLAGS = re.IGNORECASE | re.DOTALL | re.MULTILINE


def parse_app_filter(value: str | Iterable[str] | None) -> list[str]:
    """Accept a comma/newline separated string or a list."""
    if not value:
        return []
    if isinstance(value, str):
        value = re.split(r"[,\n]", value)
    return [v.strip().lower() for v in value if v and v.strip()]


def should_announce(msg: Mapping[str, Any], options: Mapping[str, Any]) -> bool:
    """Apply the app and priority filters."""
    if as_int(msg.get("priority")) < as_int(
        options.get(CONF_MIN_PRIORITY, DEFAULT_MIN_PRIORITY)
    ):
        return False
    apps = parse_app_filter(options.get(CONF_APP_FILTER))
    return not apps or str(msg.get("app") or "").strip().lower() in apps


def clean(text: str | None) -> str:
    """Make message text suitable for speaking."""
    if not text:
        return ""
    text = html.unescape(_TAG_RE.sub(" ", text))
    text = _URL_RE.sub("link", text)
    return _SPACE_RE.sub(" ", text).strip()


def truncate(text: str, max_length: int) -> str:
    """Cut to max_length characters, at a word boundary where possible."""
    if max_length <= 0 or len(text) <= max_length:
        return text
    cut = text[:max_length]
    if " " in cut[max_length // 2 :]:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-") + "."


def regex_extract(pattern: str, *sources: str | None) -> str | None:
    """Return the `say` group, else group 1, else the whole match."""
    if not pattern:
        return None
    compiled = re.compile(pattern, REGEX_FLAGS)
    for source in sources:
        if not source:
            continue
        match = compiled.search(source)
        if not match:
            continue
        if "say" in compiled.groupindex and match.group("say"):
            return match.group("say")
        if compiled.groups and match.group(1):
            return match.group(1)
        return match.group(0)
    return None


def build_text(alerts: list[Mapping[str, Any]], options: Mapping[str, Any]) -> str:
    """Build the sentence to speak for a batch of alerts."""
    fixed = options.get(CONF_FIXED_MESSAGE) or DEFAULT_FIXED_MESSAGE
    if len(alerts) > 1:
        return options.get(CONF_MULTIPLE_MESSAGE) or DEFAULT_MULTIPLE_MESSAGE
    if not alerts:
        return fixed

    msg = alerts[0]
    title = clean(msg.get("title") or msg.get("app"))
    body = clean(msg.get("message"))
    mode = options.get(CONF_MESSAGE_MODE, MODE_FIXED)

    if mode == MODE_TITLE:
        text = title
    elif mode == MODE_FULL:
        text = ". ".join(part for part in (title, body) if part)
    elif mode == MODE_REGEX:
        # Match against the raw message first (so patterns can rely on its
        # line structure), then the title.
        found = regex_extract(
            options.get(CONF_REGEX) or "", msg.get("message"), msg.get("title")
        )
        text = clean(found)
    else:
        text = fixed

    text = truncate(text, as_int(options.get(CONF_MAX_LENGTH, DEFAULT_MAX_LENGTH)))
    return text or fixed
