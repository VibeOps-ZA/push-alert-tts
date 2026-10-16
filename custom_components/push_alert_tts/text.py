"""Turn Pushover messages into the text that is spoken.

Everything here is plain Python with no Home Assistant imports, so it can run
in a worker thread (see ``coordinator.AlertTTS.compute_spoken``) and be tested
on its own.

Safety nets, in the order they apply:

1. Only the first ``MAX_TITLE_INPUT`` / ``MAX_MESSAGE_INPUT`` characters of the
   title / message are ever searched.
2. Each template placeholder is cut to ``part_max_length`` characters.
3. A template that ends up less than half filled is not spoken; the fixed
   phrase is used instead (so you never hear "Alert, , , ").
4. Words already spoken by an earlier placeholder are dropped (optional).
5. The whole sentence is cut to ``max_length`` (and never more than
   ``HARD_MAX_SPOKEN``) characters, at a word boundary.
6. The coordinator gives the regular expression ``TEXT_TIMEOUT`` seconds; a
   runaway pattern falls back to the fixed phrase.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable, Mapping
from typing import Any

from .api import as_int
from .const import (
    CONF_APP_FILTER,
    CONF_EXPAND_ABBREVIATIONS,
    CONF_FIXED_MESSAGE,
    CONF_MAX_LENGTH,
    CONF_MESSAGE_MODE,
    CONF_MIN_PRIORITY,
    CONF_MULTIPLE_MESSAGE,
    CONF_PART_MAX_LENGTH,
    CONF_REGEX,
    CONF_REGEX_SOURCE,
    CONF_REMOVE_REPEATS,
    CONF_SPOKEN_TEMPLATE,
    CONF_TIDY_TEXT,
    DEFAULT_FIXED_MESSAGE,
    DEFAULT_MAX_LENGTH,
    DEFAULT_MIN_PRIORITY,
    DEFAULT_MULTIPLE_MESSAGE,
    DEFAULT_PART_MAX_LENGTH,
    HARD_MAX_SPOKEN,
    MAX_MESSAGE_INPUT,
    MAX_TITLE_INPUT,
    MODE_FIXED,
    MODE_FULL,
    MODE_REGEX,
    MODE_TITLE,
    SOURCE_MESSAGE,
    SOURCE_TITLE,
    SOURCE_TITLE_MESSAGE,
)

_TAG_RE = re.compile(r"<[^>]+>")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")
# A dot joining words, e.g. "app01.prod" or "web.example" (not "2.5").
_DOT_RE = re.compile(r"(?<=[A-Za-z0-9])\.(?=[A-Za-z])|(?<=[A-Za-z])\.(?=[0-9])")
_PIPE_RE = re.compile(r"\s*\|+\s*")
_REPEATED_SEP_RE = re.compile(r"\s*([,;:])(?:\s*[,;:])+")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,;:.!?])")
# {name}, {1}, or the escapes {{ and }}.
_PLACEHOLDER_RE = re.compile(r"\{\{|\}\}|\{([A-Za-z0-9_]+)\}")
_EDGE_CHARS = " ,;:|"

REGEX_FLAGS = re.IGNORECASE | re.DOTALL | re.MULTILINE

# Common IT shorthand, spoken in full when "Expand common abbreviations" is on.
# Whole words only (a number may follow: "lb01" -> "load balancer 01").
# Deliberately conservative: nothing that is already a speakable word or that
# has two common meanings (e.g. "sec", "auth", "ms").
ABBREVIATIONS: dict[str, str] = {
    "avg": "average",
    "cnt": "count",
    "conn": "connection",
    "conns": "connections",
    "db": "database",
    "dbs": "databases",
    "dev": "development",
    "env": "environment",
    "err": "error",
    "errs": "errors",
    "k8s": "Kubernetes",
    "lb": "load balancer",
    "mem": "memory",
    "mgmt": "management",
    "msg": "message",
    "msgs": "messages",
    "prod": "production",
    "qty": "quantity",
    "req": "request",
    "reqs": "requests",
    "resp": "response",
    "srv": "server",
    "stg": "staging",
    "svc": "service",
    "svcs": "services",
    "txn": "transaction",
    "txns": "transactions",
}
_ABBREVIATION_RE = re.compile(
    r"(?<![A-Za-z0-9])("
    + "|".join(sorted(map(re.escape, ABBREVIATIONS), key=len, reverse=True))
    + r")(?![A-Za-z])(\d*)",
    re.IGNORECASE,
)
_WORD_KEY_RE = re.compile(r"[^\w]+")

PRIORITY_NAMES = {-2: "lowest", -1: "low", 0: "normal", 1: "high", 2: "emergency"}
# Placeholders that always exist, whatever the regular expression captures.
# A named group with the same name wins.
BUILTIN_PLACEHOLDERS = ("app", "title", "message", "priority", "priority_name")

# Outcomes reported by build_spoken() (shown by the preview action).
OUTCOME_FIXED = "fixed"
OUTCOME_MULTIPLE = "multiple"
OUTCOME_TITLE = "title"
OUTCOME_FULL = "full"
OUTCOME_REGEX = "regex"
OUTCOME_TEMPLATE = "template"
OUTCOME_NO_MATCH = "fallback_no_match"
OUTCOME_TOO_FEW = "fallback_template_too_empty"
OUTCOME_EMPTY = "fallback_empty"
OUTCOME_TIMEOUT = "fallback_timeout"
OUTCOME_ERROR = "fallback_error"


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


def tidy(text: str) -> str:
    """Make machine-ish text read naturally.

    ``web_service_check`` -> ``web service check``, ``app01.prod`` ->
    ``app01 prod`` (decimals like ``2.5`` are kept), ``a | b`` -> ``a, b``,
    repeated or dangling commas are removed.
    """
    if not text:
        return ""
    text = text.replace("_", " ")
    text = _DOT_RE.sub(" ", text)
    text = _PIPE_RE.sub(", ", text)
    text = _REPEATED_SEP_RE.sub(r"\1", text)
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    return _SPACE_RE.sub(" ", text).strip(_EDGE_CHARS)


def expand_abbreviations(text: str) -> str:
    """``lb01 prod db`` -> ``load balancer 01 production database``."""
    if not text:
        return ""

    def _sub(m: re.Match[str]) -> str:
        word = ABBREVIATIONS[m.group(1).lower()]
        return f"{word} {m.group(2)}" if m.group(2) else word

    return _ABBREVIATION_RE.sub(_sub, text)


def remove_seen_words(text: str, seen: set[str]) -> str:
    """Drop words already in ``seen`` (case-insensitive), then remember these."""
    kept = []
    for word in text.split():
        key = _WORD_KEY_RE.sub("", word).lower()
        if key and key in seen:
            continue
        kept.append(word)
    for word in text.split():
        if key := _WORD_KEY_RE.sub("", word).lower():
            seen.add(key)
    return " ".join(kept).strip(_EDGE_CHARS)


def truncate(text: str, max_length: int) -> str:
    """Cut to max_length characters, at a word boundary where possible."""
    if max_length <= 0 or len(text) <= max_length:
        return text
    cut = text[:max_length]
    if " " in cut[max_length // 2 :]:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-") + "."


def cut_part(text: str, max_length: int) -> str:
    """Like truncate() but without the full stop: for template placeholders."""
    if max_length <= 0 or len(text) <= max_length:
        return text
    cut = text[:max_length]
    if " " in cut[max_length // 2 :]:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-.|")


def regex_sources(msg: Mapping[str, Any], order: str | None) -> list[str]:
    """The (length-capped) texts to search, in the configured order."""
    title = str(msg.get("title") or "")[:MAX_TITLE_INPUT]
    message = str(msg.get("message") or "")[:MAX_MESSAGE_INPUT]
    if order == SOURCE_TITLE:
        return [title]
    if order == SOURCE_MESSAGE:
        return [message]
    if order == SOURCE_TITLE_MESSAGE:
        return [title, message]
    return [message, title]  # SOURCE_MESSAGE_TITLE, the default


def regex_search(pattern: str, sources: Iterable[str]) -> re.Match[str] | None:
    """First match of ``pattern`` in ``sources``."""
    if not pattern:
        return None
    compiled = re.compile(pattern, REGEX_FLAGS)
    for source in sources:
        if source and (match := compiled.search(source)):
            return match
    return None


def match_text(match: re.Match[str]) -> str:
    """The `say` group, else group 1, else the whole match."""
    groups = match.re.groupindex
    if "say" in groups and match.group("say"):
        return match.group("say")
    if match.re.groups and match.group(1):
        return match.group(1)
    return match.group(0)


def regex_extract(pattern: str, *sources: str | None) -> str | None:
    """Return the `say` group, else group 1, else the whole match."""
    match = regex_search(pattern, [s for s in sources if s])
    return match_text(match) if match else None


def template_placeholders(template: str) -> list[str]:
    """Names used in a template, in order (escapes {{ }} are skipped)."""
    return [m.group(1) for m in _PLACEHOLDER_RE.finditer(template) if m.group(1)]


def unknown_placeholders(template: str, pattern: str | None) -> list[str]:
    """Placeholders that neither the pattern nor the built-ins provide."""
    names: set[str] = set(BUILTIN_PLACEHOLDERS)
    groups = 0
    if pattern:
        compiled = re.compile(pattern, REGEX_FLAGS)
        names.update(compiled.groupindex)
        groups = compiled.groups
    unknown = []
    for name in template_placeholders(template):
        if name in names or (name.isdigit() and int(name) <= groups):
            continue
        if name not in unknown:
            unknown.append(name)
    return unknown


def render_template(
    template: str,
    values: Mapping[str, str],
    part_max_length: int,
    tidy_parts: bool,
    expand: bool = False,
    remove_repeats: bool = False,
) -> tuple[str, int, int]:
    """Fill a template. Returns (text, placeholders filled, placeholders used).

    A placeholder emptied only because all its words were already spoken still
    counts as filled (it had a value), so it can't trigger the fallback.
    """
    filled = 0
    used = 0
    seen: set[str] = set()

    def _sub(m: re.Match[str]) -> str:
        nonlocal filled, used
        token = m.group(0)
        if token == "{{":
            return "{"
        if token == "}}":
            return "}"
        used += 1
        value = clean(values.get(m.group(1)))
        if tidy_parts:
            value = tidy(value)
        if expand:
            value = expand_abbreviations(value)
        if value:
            filled += 1
        if remove_repeats:
            value = remove_seen_words(value, seen)
        return cut_part(value, part_max_length)

    text = _PLACEHOLDER_RE.sub(_sub, template)
    # Tidy the joins left by empty placeholders: "a, , b" -> "a, b".
    text = _REPEATED_SEP_RE.sub(r"\1", text)
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    text = _SPACE_RE.sub(" ", text).strip(_EDGE_CHARS)
    return text, filled, used


def template_values(
    msg: Mapping[str, Any], match: re.Match[str] | None
) -> dict[str, str]:
    """Built-in values plus the regular expression's captured groups."""
    priority = as_int(msg.get("priority"))
    values: dict[str, str] = {
        "app": str(msg.get("app") or ""),
        "title": str(msg.get("title") or "")[:MAX_TITLE_INPUT],
        "message": str(msg.get("message") or "")[:MAX_MESSAGE_INPUT],
        "priority": str(priority),
        "priority_name": PRIORITY_NAMES.get(priority, str(priority)),
    }
    if match:
        for index in range(1, match.re.groups + 1):
            values[str(index)] = match.group(index) or ""
        for name, value in match.groupdict().items():
            values[name] = value or ""
    return values


def _limit(options: Mapping[str, Any]) -> int:
    limit = as_int(options.get(CONF_MAX_LENGTH, DEFAULT_MAX_LENGTH))
    return HARD_MAX_SPOKEN if limit <= 0 or limit > HARD_MAX_SPOKEN else limit


def build_spoken(
    alerts: list[Mapping[str, Any]], options: Mapping[str, Any]
) -> dict[str, Any]:
    """Build the sentence to speak, and say how it was made.

    Returns ``{"text": str, "outcome": str, "groups": dict}``; ``groups`` holds
    what the regular expression captured (empty when it was not used).
    """
    fixed = options.get(CONF_FIXED_MESSAGE) or DEFAULT_FIXED_MESSAGE
    if len(alerts) > 1:
        text = options.get(CONF_MULTIPLE_MESSAGE) or DEFAULT_MULTIPLE_MESSAGE
        return {"text": text, "outcome": OUTCOME_MULTIPLE, "groups": {}}
    if not alerts:
        return {"text": fixed, "outcome": OUTCOME_FIXED, "groups": {}}

    msg = alerts[0]
    mode = options.get(CONF_MESSAGE_MODE, MODE_FIXED)
    do_tidy = bool(options.get(CONF_TIDY_TEXT, True))
    do_expand = bool(options.get(CONF_EXPAND_ABBREVIATIONS, False))
    groups: dict[str, str] = {}

    def _tidy(value: str) -> str:
        value = tidy(value) if do_tidy else value
        return expand_abbreviations(value) if do_expand else value

    if mode == MODE_TITLE:
        outcome = OUTCOME_TITLE
        text = _tidy(clean(str(msg.get("title") or msg.get("app") or "")))
    elif mode == MODE_FULL:
        outcome = OUTCOME_FULL
        title = _tidy(clean(str(msg.get("title") or msg.get("app") or "")))
        body = _tidy(clean(str(msg.get("message") or "")[:MAX_MESSAGE_INPUT]))
        text = ". ".join(part for part in (title, body) if part)
    elif mode == MODE_REGEX:
        match = regex_search(
            options.get(CONF_REGEX) or "",
            regex_sources(msg, options.get(CONF_REGEX_SOURCE)),
        )
        if match is None:
            return {"text": fixed, "outcome": OUTCOME_NO_MATCH, "groups": {}}
        # What was captured (shown by the preview action): named groups if
        # the pattern has any, otherwise numbered ones.
        groups = {k: v or "" for k, v in match.groupdict().items()} or {
            str(i): match.group(i) or "" for i in range(1, match.re.groups + 1)
        }
        template = (options.get(CONF_SPOKEN_TEMPLATE) or "").strip()
        if template:
            text, filled, used = render_template(
                template,
                template_values(msg, match),
                as_int(options.get(CONF_PART_MAX_LENGTH, DEFAULT_PART_MAX_LENGTH)),
                do_tidy,
                do_expand,
                bool(options.get(CONF_REMOVE_REPEATS, True)),
            )
            if used and (filled == 0 or filled * 2 < used):
                return {"text": fixed, "outcome": OUTCOME_TOO_FEW, "groups": groups}
            outcome = OUTCOME_TEMPLATE
        else:
            text = _tidy(clean(match_text(match)))
            outcome = OUTCOME_REGEX
    else:
        return {"text": fixed, "outcome": OUTCOME_FIXED, "groups": {}}

    text = truncate(text, _limit(options))
    if not text:
        return {"text": fixed, "outcome": OUTCOME_EMPTY, "groups": groups}
    return {"text": text, "outcome": outcome, "groups": groups}


def build_text(alerts: list[Mapping[str, Any]], options: Mapping[str, Any]) -> str:
    """Build the sentence to speak for a batch of alerts."""
    return build_spoken(alerts, options)["text"]
