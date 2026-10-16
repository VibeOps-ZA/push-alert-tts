"""Spoken templates, tidying and the safety nets."""

import pytest

from custom_components.push_alert_tts.text import (
    build_spoken,
    build_text,
    expand_abbreviations,
    render_template,
    tidy,
    unknown_placeholders,
)

# The pattern from the README: "[P1] Triggered: a | b | c [tags]"
STATUS_RE = (
    r"^\s*\[P\d\]\s*(?P<state>[A-Za-z][A-Za-z -]{0,19}):\s*"
    r"(?P<s1>[^|\[]{1,60})(?:\|\s*(?P<s2>[^|\[]{1,60}))?"
    r"(?:\|\s*(?P<s3>[^|\[]{1,60}))?"
)
OPTS = {
    "message_mode": "regex",
    "regex": STATUS_RE,
    "regex_source": "title",
    "spoken_template": "Alert, {s1}, {s2}, {s3}, {state}",
    "part_max_length": 30,
    "max_length": 100,
    "fixed_message": "Pushover alert received",
}


def alert(title, message="details\nmore details", **kw):
    return {"title": title, "message": message, "app": "Monitor", "priority": 1, **kw}


def test_template_three_parts():
    title = "[P1] Re-Triggered: http | web_service_failure_check | shop.app01.prod"
    assert build_text([alert(title)], OPTS) == (
        "Alert, http, web service failure check, shop app01 prod, Re-Triggered"
    )


def test_template_skips_missing_part():
    title = "[P2] Recovered: disk | db01 [env:prod]"
    assert build_text([alert(title)], OPTS) == "Alert, disk, db01, Recovered"


def test_template_too_empty_falls_back():
    # Only {state} filled: 1 of 4 placeholders, less than half.
    result = build_spoken([alert("[P1] Triggered: | | [P1]")], OPTS)
    assert result["text"] == "Pushover alert received"
    assert result["outcome"] == "fallback_template_too_empty"


def test_no_match_falls_back():
    result = build_spoken([alert("Home Assistant test")], OPTS)
    assert result == {
        "text": "Pushover alert received",
        "outcome": "fallback_no_match",
        "groups": {},
    }


def test_title_only_ignores_message():
    msg = alert("plain title", message="[P1] Triggered: a | b | c")
    assert build_spoken([msg], OPTS)["outcome"] == "fallback_no_match"
    both = {**OPTS, "regex_source": "title_message"}
    assert build_text([msg], both) == "Alert, a, b, c, Triggered"


def test_part_and_total_caps():
    long = "word " * 200
    title = f"[P1] Triggered: {long}| {long}| {long}"
    text = build_text([alert(title)], OPTS)
    assert len(text) <= 101  # max_length plus the closing full stop
    huge = build_text([alert(title)], {**OPTS, "max_length": 0})
    assert len(huge) < 4 * 31 + 30  # each part capped at 30


def test_huge_message_is_capped_before_matching():
    opts = {"message_mode": "regex", "regex": r"(?P<say>END)", "max_length": 0}
    msg = alert("t", message="x" * 10_000 + "END")
    assert build_spoken([msg], opts)["outcome"] == "fallback_no_match"


def test_builtins_and_numbered_groups():
    opts = {
        "message_mode": "regex",
        "regex": r"host (\S+)",
        "spoken_template": "{priority_name} {app} alert on {1}",
    }
    msg = alert("t", message="host db_01 down")
    assert build_text([msg], opts) == "high Monitor alert on db 01"


def test_escaped_braces_and_tidy_off():
    opts = {
        "message_mode": "regex",
        "regex": r"(?P<h>\S+_\S+)",
        "spoken_template": "{{x}} {h}",
        "tidy_text": False,
    }
    assert build_text([alert("t", message="a_b")], opts) == "{x} a_b"


def test_regex_without_template_still_works():
    opts = {"message_mode": "regex", "regex": r"Host (?P<say>\S+)"}
    assert build_text([alert("t", message="Host web_01.prod up")], opts) == (
        "web 01 prod"
    )


@pytest.mark.parametrize(
    ("raw", "spoken"),
    [
        ("web_service_check", "web service check"),
        ("app01.prod.example", "app01 prod example"),
        ("load 2.5 on v1.2", "load 2.5 on v1.2"),
        ("a | b || c", "a, b, c"),
        ("a , , b,", "a, b"),
        ("1,000 errors", "1,000 errors"),
    ],
)
def test_tidy(raw, spoken):
    assert tidy(raw) == spoken


def test_render_counts():
    text, filled, used = render_template("A {x} {y}", {"x": "1"}, 0, True)
    assert (text, filled, used) == ("A 1", 1, 2)


def test_unknown_placeholders():
    assert unknown_placeholders("{s1} {app} {2}", r"(?P<s1>a)(b)") == []
    assert unknown_placeholders("{nope} {3}", r"(a)") == ["nope", "3"]


def test_repeated_words_removed():
    title = "[P1] Re-Triggered: za_mtn_momo_hr | threshold | integration momo mtn | x"
    assert build_text([alert(title)], OPTS) == (
        "Alert, za mtn momo hr, threshold, integration, Re-Triggered"
    )
    keep = {**OPTS, "remove_repeated_words": False}
    assert "integration momo mtn" in build_text([alert(title)], keep)


def test_part_emptied_by_repeats_still_counts_as_filled():
    # s2 and s3 repeat s1 entirely: 4 of 4 filled, so no fallback.
    title = "[P1] Triggered: disk db01 | disk | db01"
    result = build_spoken([alert(title)], OPTS)
    assert result["outcome"] == "template"
    assert result["text"] == "Alert, disk db01, Triggered"


def test_expand_abbreviations():
    opts = {**OPTS, "expand_abbreviations": True, "max_length": 0}
    title = "[P1] Triggered: logs | error or fatal | telkom.lb01.prod"
    assert build_text([alert(title)], opts) == (
        "Alert, logs, error or fatal, telkom load balancer 01, Triggered"
    )  # "production" is cut by the 30-character part limit
    assert expand_abbreviations("DB svc k8s prodx dbase") == (
        "database service Kubernetes prodx dbase"
    )
    assert "load balancer" not in build_text([alert(title)], OPTS)  # off by default


def test_expand_in_title_mode():
    opts = {"message_mode": "title", "expand_abbreviations": True}
    assert build_text([alert("prod db_02 err")], opts) == (
        "production database 02 error"
    )
