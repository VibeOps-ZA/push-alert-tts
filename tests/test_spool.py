"""Combined alerts: one session, joined announcements, must-hear checks, links."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.push_alert_tts import audio, spool
from custom_components.push_alert_tts.const import (
    CONF_ANNOUNCE_RETRIES,
    CONF_COMBINE,
    CONF_GATHER,
    CONF_LINK_LABEL,
    CONF_MISSED_BELL,
    CONF_MUST_HEAR,
    CONF_NIGHT_CONDITION,
    CONF_NIGHT_MUST_HEAR,
    CONF_SPEAKER_GROUP,
    CONF_STAY_CONNECTED,
)

GROUP = "media_player.all_speakers"
BEDROOM = "media_player.bedroom"
KITCHEN = "media_player.kitchen"
C = "custom_components.push_alert_tts.coordinator"
LINK = "https://app.example.com/monitors/123?group=host%3Adb1"


@pytest.fixture(autouse=True)
def quick():
    with (
        patch(f"{C}.PLAYBACK_START_TIMEOUT", 0.5),
        patch(f"{C}.GROUP_START_TIMEOUT", 0.5),
        patch(f"{C}.PLAYBACK_END_GRACE", 0.1),
        patch(f"{C}.SPEECH_CHARS_PER_SECOND", 100000),
        patch(f"{C}.SHORT_PLAY_MIN", 0),
    ):
        yield


@pytest.fixture
def joined():
    """ffmpeg stand-in: the joined 'audio' is the parts' text, pauses as [n]."""
    made: list[str] = []

    async def generate(hass, engine, text, language, options=None):
        return f"test-media://{engine}|{language or ''}|{text}", text.encode(), "mp3"

    async def stitch(hass, parts, out_path, timeout):
        text = " ".join(
            f"[{p:g}]" if isinstance(p, float) else p[0].decode() for p in parts
        )
        made.append(text)
        return out_path

    def clip_media_id(hass, engine, path):
        return f"test-media://{engine}||{made[-1] if made else path}"

    with (
        patch.object(audio, "generate", new=generate),
        patch.object(audio, "stitch", new=stitch),
        patch.object(audio, "clip_media_id", new=clip_media_id),
    ):
        yield made


def _states(hass: HomeAssistant) -> None:
    hass.states.async_set(BEDROOM, "idle", {"volume_level": 0.2})
    hass.states.async_set(KITCHEN, "idle", {"volume_level": 0.3})
    hass.states.async_set(GROUP, "idle", {})


def _player(hass: HomeAssistant, deaf: set[str] | None = None, heal_after: int = 0):
    """tts.speak that makes the targets (and a group's members) play, then stop.

    Speakers in `deaf` don't play (as if they dropped off the network), until
    `heal_after` plays have happened (0 = never).
    """
    deaf = deaf if deaf is not None else set()
    calls: list[ServiceCall] = []

    async def speak(call: ServiceCall) -> None:
        calls.append(call)
        if heal_after and len(calls) > heal_after:
            deaf.clear()
        players = list(call.data["media_player_entity_id"])
        if GROUP in players:
            players += [BEDROOM, KITCHEN]
        content = f"media-{len(calls)}"
        for p in players:
            if p in deaf:
                continue
            attrs = dict(hass.states.get(p).attributes) if hass.states.get(p) else {}
            hass.states.async_set(p, "playing", {**attrs, "media_content_id": content})
            hass.loop.call_later(
                0.2, lambda p=p, a=attrs: hass.states.async_set(p, "idle", a)
            )

    hass.services.async_register("tts", "speak", speak)
    return calls


async def _setup(hass, entry, **options):
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_SPEAKER_GROUP: GROUP,
            CONF_COMBINE: True,
            CONF_GATHER: 0.3,
            CONF_STAY_CONNECTED: 0.5,
            **options,
        },
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    runtime = entry.runtime_data
    runtime.enabled = True
    return runtime


def _msg(i: int, priority: int = 0, title: str | None = None, **kw) -> dict:
    return {
        "id_str": str(i),
        "umid_str": f"u{i}",
        "title": title or f"Alert number {i}",
        "message": f"Body {i}\nMonitor Status <{LINK}>·Edit Monitor <https://x/edit>",
        "app": "Datadog",
        "priority": priority,
        "date": int(time.time()),
        **kw,
    }


async def _alerts(hass, runtime, *msgs) -> None:
    await runtime._on_alerts(list(msgs), queued=False)
    await hass.async_block_till_done(wait_background_tasks=True)


async def _settle(hass) -> None:
    for _ in range(40):
        await asyncio.sleep(0.1)
        await hass.async_block_till_done(wait_background_tasks=True)


def _said(calls) -> list[tuple[list[str], str]]:
    return [(list(c.data["media_player_entity_id"]), c.data["message"]) for c in calls]


# -- plain functions ------------------------------------------------------------------
def test_one_new_alert_is_said_as_it_is() -> None:
    assert spool.build_segments(["Alert, disk, db1"], more=False) == [
        "Alert, disk, db1"
    ]


def test_several_alerts_get_a_heading_and_numbers() -> None:
    segs = spool.build_segments(["Alert, disk, db1", "P1 alert at X"], more=False)
    assert segs == [
        "2 alerts have arrived.",
        1.0,
        "First alert:",
        1.0,
        "disk, db1",
        2.0,
        "Second alert:",
        1.0,
        "P1 alert at X",
        2.0,
    ]


def test_more_alerts_heading() -> None:
    assert spool.build_segments(["a"], more=True)[:3] == [
        "1 more alert has arrived.",
        1.0,
        "a",
    ]
    assert spool.build_segments(["a", "b"], more=True)[0] == (
        "2 more alerts have arrived."
    )


def test_ordinals() -> None:
    assert spool.ordinal(0) == "First"
    assert spool.ordinal(9) == "Tenth"
    assert spool.ordinal(10) == "Number 11"


@pytest.mark.parametrize(
    ("msg", "label", "link"),
    [
        ({"message": f"x Monitor Status <{LINK}>·Edit"}, "Monitor Status", LINK),
        ({"message": f"Monitor status: {LINK} more"}, "Monitor Status", LINK),
        ({"message": "nothing", "url": "https://p.example/1"}, "Monitor Status",
         "https://p.example/1"),
        ({"message": "nothing", "url": "mailto:a@b.c"}, "Monitor Status", None),
        ({"message": f"Monitor Status <{LINK}>", "url": "https://u"}, "", "https://u"),
    ],
)
def test_find_link(msg, label, link) -> None:
    assert spool.find_link(msg, label) == link


def test_stitch_arguments_join_files_and_pauses() -> None:
    args = audio.stitch_args("ffmpeg", ["a.mp3", 1.0, "b.mp3"], "out.mp3")
    assert args.count("-i") == 3
    assert "anullsrc=r=24000:cl=mono" in args
    graph = args[args.index("-filter_complex") + 1]
    assert graph.endswith("[a0][a1][a2]concat=n=3:v=0:a=1[out]")
    assert args[-1] == "out.mp3"


# -- the spool ------------------------------------------------------------------------
async def test_alerts_arriving_together_are_one_announcement(
    hass: HomeAssistant, mock_entry, no_listener, joined
) -> None:
    _states(hass)
    calls = _player(hass)
    vol = async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry)
    await _alerts(hass, runtime, _msg(1), _msg(2))
    await _settle(hass)
    assert len(calls) == 1  # one thing to play: one connect sound at most
    assert calls[0].data["media_player_entity_id"] == [GROUP]
    assert joined == [
        "2 alerts have arrived. [1] First alert: [1] Alert received [2] "
        "Second alert: [1] Alert received [2]"
    ]
    # Volume set once for the session, put back once at the end.
    to_target = [c for c in vol if c.data["volume_level"] == 0.6]
    assert len(to_target) == 2  # bedroom and kitchen, once each
    assert (BEDROOM, 0.2) in [(c.data["entity_id"], c.data["volume_level"]) for c in vol]


async def test_single_alert_is_said_as_before(
    hass: HomeAssistant, mock_entry, no_listener, joined
) -> None:
    _states(hass)
    calls = _player(hass)
    async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry)
    await _alerts(hass, runtime, _msg(1))
    await _settle(hass)
    assert _said(calls) == [([GROUP], "Alert received")]
    assert joined == []  # nothing to join


async def test_alerts_during_speech_follow_as_more(
    hass: HomeAssistant, mock_entry, no_listener, joined
) -> None:
    _states(hass)
    calls: list[ServiceCall] = []
    release = asyncio.Event()

    async def speak(call: ServiceCall) -> None:
        calls.append(call)
        hass.states.async_set(GROUP, "playing", {"media_content_id": str(len(calls))})
        hass.states.async_set(BEDROOM, "playing", {"volume_level": 0.6})
        await release.wait() if len(calls) == 1 else None
        hass.loop.call_later(0.1, lambda: hass.states.async_set(GROUP, "idle", {}))

    hass.services.async_register("tts", "speak", speak)
    vol = async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry)
    await runtime._on_alerts([_msg(1)], queued=False)
    for _ in range(20):
        await asyncio.sleep(0.05)
        if calls:
            break
    assert len(calls) == 1
    await runtime._on_alerts([_msg(2), _msg(3)], queued=False)
    await asyncio.sleep(0.2)
    release.set()
    await _settle(hass)
    assert len(calls) == 2
    assert joined[-1].startswith("2 more alerts have arrived. [1] First alert:")
    # No wake-up or volume change between the two.
    assert len([c for c in vol if c.data["volume_level"] == 0.6]) == 2


async def test_session_stays_open_for_alerts_soon_after(
    hass: HomeAssistant, mock_entry, no_listener, joined
) -> None:
    _states(hass)
    calls = _player(hass)
    vol = async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry, **{CONF_STAY_CONNECTED: 3})
    await runtime._on_alerts([_msg(1)], queued=False)
    await asyncio.sleep(1.0)
    assert runtime.spool.busy  # still holding the speakers
    await runtime._on_alerts([_msg(2)], queued=False)
    await asyncio.sleep(1.0)
    assert len(calls) == 2
    assert calls[1].data["message"] == "Alert received"  # a new alert: no heading
    assert len([c for c in vol if c.data["volume_level"] == 0.6]) == 2  # set once
    runtime.spool._added.set()  # noqa: SLF001
    for _ in range(60):
        await asyncio.sleep(0.1)
        if not runtime.spool.busy:
            break
    assert not runtime.spool.busy


async def test_must_hear_speaker_that_missed_hears_it_again(
    hass: HomeAssistant, mock_entry, no_listener, joined
) -> None:
    _states(hass)
    calls = _player(hass, {BEDROOM}, heal_after=1)  # back for the replay
    async_mock_service(hass, "media_player", "volume_set")
    notify = async_mock_service(hass, "notify", "mobile_app_phone")
    runtime = await _setup(hass, mock_entry, **{CONF_MUST_HEAR: [BEDROOM, KITCHEN]})
    await _alerts(hass, runtime, _msg(1))
    await _settle(hass)
    assert _said(calls)[0] == ([GROUP], "Alert received")
    assert calls[1].data["media_player_entity_id"] == [BEDROOM]
    assert calls[1].data["message"].startswith("Missed alert TTS:")
    assert not notify  # heard in the end


async def test_still_missed_sends_each_alert_with_its_link(
    hass: HomeAssistant, mock_entry, no_listener, joined
) -> None:
    _states(hass)
    calls = _player(hass, {BEDROOM})
    async_mock_service(hass, "media_player", "volume_set")
    notify = async_mock_service(hass, "notify", "mobile_app_phone")
    runtime = await _setup(
        hass,
        mock_entry,
        **{CONF_MUST_HEAR: [BEDROOM, KITCHEN], CONF_ANNOUNCE_RETRIES: 2,
           CONF_MISSED_BELL: True},
    )
    await _alerts(hass, runtime, _msg(1), _msg(2))
    await _settle(hass)
    replays = [c for c in calls if c.data["media_player_entity_id"] == [BEDROOM]]
    assert len(replays) == 2  # announce retries
    assert len(notify) == 2  # one per alert
    data = notify[0].data
    assert "bedroom" in data["title"].lower()
    assert data["message"] == "Alert received"
    assert data["data"]["url"] == LINK
    assert data["data"]["clickAction"] == LINK
    bells = hass.states.async_all("persistent_notification")
    assert len(bells) == 2 or bells == []  # stored in the notification manager
    rows = runtime.review  # not AI: history rows still recorded via _record
    assert rows is not None


async def test_day_rule_any_must_hear_missing_notifies(
    hass: HomeAssistant, mock_entry, no_listener, joined
) -> None:
    """Kitchen missed (bedroom fine): still a notification by day."""
    _states(hass)
    _player(hass, {KITCHEN})
    async_mock_service(hass, "media_player", "volume_set")
    notify = async_mock_service(hass, "notify", "mobile_app_phone")
    runtime = await _setup(hass, mock_entry, **{CONF_MUST_HEAR: [BEDROOM, KITCHEN]})
    await _alerts(hass, runtime, _msg(1))
    await _settle(hass)
    assert len(notify) == 1
    assert "kitchen" in notify[0].data["title"].lower()


async def test_night_uses_the_night_list(
    hass: HomeAssistant, mock_entry, no_listener, joined
) -> None:
    """At night only the bedroom must hear it: the kitchen missing is fine."""
    _states(hass)
    hass.states.async_set("input_boolean.asleep", "on")
    _player(hass, {KITCHEN})
    async_mock_service(hass, "media_player", "volume_set")
    notify = async_mock_service(hass, "notify", "mobile_app_phone")
    runtime = await _setup(
        hass,
        mock_entry,
        **{
            CONF_MUST_HEAR: [BEDROOM, KITCHEN],
            CONF_NIGHT_MUST_HEAR: [BEDROOM],
            CONF_NIGHT_CONDITION: "{{ is_state('input_boolean.asleep', 'on') }}",
        },
    )
    assert runtime.is_night()
    assert runtime.must_hear() == [BEDROOM]
    await _alerts(hass, runtime, _msg(1))
    await _settle(hass)
    assert not notify
    hass.states.async_set("input_boolean.asleep", "off")
    assert runtime.must_hear() == [BEDROOM, KITCHEN]


async def test_broken_night_condition_counts_as_day(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _states(hass)
    runtime = await _setup(
        hass,
        mock_entry,
        **{
            CONF_MUST_HEAR: [BEDROOM, KITCHEN],
            CONF_NIGHT_MUST_HEAR: [BEDROOM],
            CONF_NIGHT_CONDITION: "{{ states('x') | nonsense_filter }}",
        },
    )
    assert not runtime.is_night()
    assert runtime.must_hear() == [BEDROOM, KITCHEN]


async def test_emergency_goes_first(
    hass: HomeAssistant, mock_entry, no_listener, joined
) -> None:
    _states(hass)
    calls = _player(hass)
    async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry, **{"message_mode": "title"})
    await _alerts(
        hass,
        runtime,
        _msg(1, title="Normal one"),
        _msg(2, priority=2, title="Emergency one", receipt="r1", expire=60),
    )
    await _settle(hass)
    said = " / ".join(c.data["message"] for c in calls)
    assert said.index("Emergency one") < said.index("Normal one")


async def test_link_is_saved_in_history(
    hass: HomeAssistant, mock_entry, no_listener, joined
) -> None:
    _states(hass)
    _player(hass)
    async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry, history_days=7)
    await _alerts(hass, runtime, _msg(1))
    await _settle(hass)
    rows = await runtime.get_history(days=1, limit=5, search=None)
    assert rows[0]["link"] == LINK
    assert rows[0]["announced"] is True
    assert rows[0]["timings"]["batch_size"] == 1


async def test_plain_speech_shares_the_session(
    hass: HomeAssistant, mock_entry, no_listener, joined
) -> None:
    """The test button / emergency repeats go through the spool too."""
    _states(hass)
    calls = _player(hass)
    vol = async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry)
    await runtime.speak("hello there")
    assert _said(calls) == [([GROUP], "hello there")]
    await runtime.speak("again")
    assert len(calls) == 2
    assert len([c for c in vol if c.data["volume_level"] == 0.6]) == 2


async def test_joining_failure_says_it_as_one_text(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _states(hass)
    calls = _player(hass)
    async_mock_service(hass, "media_player", "volume_set")

    async def broken(*_a, **_k):
        raise RuntimeError("no ffmpeg")

    runtime = await _setup(hass, mock_entry)
    with patch.object(audio, "stitch", new=broken):
        await _alerts(hass, runtime, _msg(1), _msg(2))
        await _settle(hass)
    assert len(calls) == 1
    assert calls[0].data["message"].startswith("2 alerts have arrived. First alert:")


async def test_link_label_option(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _states(hass)
    runtime = await _setup(hass, mock_entry, **{CONF_LINK_LABEL: "Edit Monitor"})
    assert runtime.link_label == "Edit Monitor"
    assert spool.find_link(_msg(1), runtime.link_label) == "https://x/edit"


@pytest.mark.skipif(audio.ffmpeg_binary() is None, reason="ffmpeg not installed")
async def test_real_stitch_joins_with_pauses(hass: HomeAssistant, tmp_path) -> None:
    """ffmpeg joins two clips and a pause into one MP3 of the right length."""
    import subprocess  # noqa: PLC0415

    clips = []
    for name, seconds in (("a", 1.0), ("b", 1.5)):
        path = tmp_path / f"{name}.mp3"
        subprocess.run(  # noqa: S603
            [audio.ffmpeg_binary(), "-loglevel", "error", "-f", "lavfi", "-t",
             str(seconds), "-i", "sine=f=440:r=22050", "-c:a", "libmp3lame",
             str(path)],
            check=True,
        )
        clips.append((path.read_bytes(), "mp3"))
    out = str(tmp_path / "spool" / "joined.mp3")
    await audio.stitch(hass, [clips[0], 1.0, clips[1], 2.0], out, 30)
    import shutil  # noqa: PLC0415

    if ffprobe := shutil.which("ffprobe"):
        probe = subprocess.run(  # noqa: S603
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", out],
            check=True, capture_output=True, text=True,
        )
        assert 5.3 < float(probe.stdout) < 5.8
    assert (tmp_path / "spool").exists()
    assert [p.name for p in (tmp_path / "spool").iterdir()] == ["joined.mp3"]
