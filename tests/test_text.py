"""Spoken-text building."""

from custom_components.push_alert_tts.text import (
    build_text,
    clean,
    should_announce,
    truncate,
)

MSG = {
    "title": "PROD: disk full",
    "message": "Host web-01 /var at 98%\nRunbook: https://wiki/x\nMore detail here",
    "app": "Datadog",
    "priority": 1,
}


def test_fixed():
    assert build_text([MSG], {"message_mode": "fixed", "fixed_message": "Hi"}) == "Hi"


def test_multiple():
    assert build_text([MSG, MSG], {"message_mode": "full"}) == (
        "Multiple Pushover alerts recorded"
    )


def test_title():
    assert build_text([MSG], {"message_mode": "title"}) == "PROD: disk full"


def test_full_strips_urls_and_newlines():
    text = build_text([MSG], {"message_mode": "full", "max_length": 0})
    assert "https" not in text and "\n" not in text
    assert text.startswith("PROD: disk full. Host web-01")


def test_regex_named_group():
    opts = {"message_mode": "regex", "regex": r"Host (?P<say>\S+)"}
    assert build_text([MSG], opts) == "web-01"


def test_regex_first_line():
    opts = {"message_mode": "regex", "regex": r"^([^\n]+)"}
    assert build_text([MSG], opts) == "Host web-01 /var at 98%"


def test_regex_no_match_falls_back():
    opts = {"message_mode": "regex", "regex": "zzz", "fixed_message": "Fallback"}
    assert build_text([MSG], opts) == "Fallback"


def test_truncate_on_word():
    assert truncate("one two three four five", 12) == "one two."


def test_clean_html():
    assert clean("<b>Hi</b> &amp; bye") == "Hi & bye"


def test_filters():
    assert should_announce(MSG, {})
    assert not should_announce(MSG, {"min_priority": "2"})
    assert should_announce(MSG, {"app_filter": "datadog, Grafana"})
    assert not should_announce(MSG, {"app_filter": "Grafana"})
