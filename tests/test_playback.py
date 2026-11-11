"""Playback end detection, retries when an announcement is cut short, wake-up wait."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.push_alert_tts.const import (
    CONF_ANNOUNCE_RETRIES,
    CONF_PRECONNECT_GROUP,
    CONF_SPEAKER_GROUP,
    CONF_TTS_BACKUP,
    CONF_TTS_LANGUAGE,
    CONF_WAKE_WAIT,
)

GROUP = "media_player.all_speakers"
MEMBERS = ["media_player.bedroom", "media_player.kitchen"]
TEXT = "P1 alert at Example on load balancer 1. Large number of errors in logs."
C = "custom_components.push_alert_tts.coordinator"


@pytest.fixture(autouse=True)
def quick():
    with (
        patch(f"{C}.GROUP_START_TIMEOUT", 1),
        patch(f"{C}.PLAYBACK_END_GRACE", 0.6),
        patch(f"{C}.SHORT_PLAY_MIN", 1.0),
        patch(f"{C}.SPEECH_CHARS_PER_SECOND", 1000),  # expected time ~0: use the minimum
    ):
        yield


def _states(hass: HomeAssistant, group: str = "idle") -> None:
    hass.states.async_set("media_player.bedroom", "idle", {"volume_level": 0.2})
    hass.states.async_set("media_player.kitchen", "idle", {"volume_level": 0.3})
    hass.states.async_set(GROUP, group, {})


async def _setup(hass, entry, **options):
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_SPEAKER_GROUP: GROUP, **options}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry.runtime_data


def _tts(hass: HomeAssistant, plays: list[list[tuple[float, str]]]):
    """tts.speak on the group: each call runs the next state script.

    A script is [(delay_s, state), ...], set one after another from the call.
    """
    calls: list[ServiceCall] = []

    async def speak(call: ServiceCall) -> None:
        calls.append(call)
        if call.data["media_player_entity_id"] != [GROUP]:
            return
        script = plays[min(len(calls), len(plays)) - 1]
        content = f"tts-{len(calls)}"
        at = 0.0
        for delay, state in script:
            at += delay
            hass.loop.call_later(
                at,
                lambda st=state: hass.states.async_set(
                    GROUP, st, {"media_content_id": content}
                ),
            )

    hass.services.async_register("tts", "speak", speak)
    return calls


GOOD = [(0.05, "playing"), (1.5, "idle")]
CUT = [(0.05, "playing"), (0.2, "off")]


async def test_buffering_in_the_middle_does_not_end_playback(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    """The 0.8.0 bug: a short 'buffering' ended it and the speakers were turned off."""
    _states(hass)
    calls = _tts(
        hass,
        [[(0.05, "playing"), (0.3, "buffering"), (0.3, "playing"), (1.0, "idle")]],
    )
    async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry)
    timings: dict = {}
    await runtime.speak(TEXT, timings=timings, t0=time.monotonic())
    assert len(calls) == 1
    assert timings["outcome"] == "ok"
    assert timings["attempts"] == 1
    assert timings["played_s"] >= 1.0


async def test_short_stop_waits_for_grace_before_finishing(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    """Idle for less than the grace time, then playing again: still one announcement."""
    _states(hass)
    calls = _tts(
        hass, [[(0.05, "playing"), (0.3, "idle"), (0.3, "playing"), (1.0, "idle")]]
    )
    async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry)
    timings: dict = {}
    await runtime.speak(TEXT, timings=timings, t0=time.monotonic())
    assert len(calls) == 1
    assert timings["outcome"] == "ok"


async def test_cut_short_is_retried_on_the_group(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _states(hass)
    calls = _tts(hass, [CUT, GOOD])
    async_mock_service(hass, "media_player", "volume_set")
    notify = async_mock_service(hass, "notify", "mobile_app_phone")
    runtime = await _setup(hass, mock_entry, **{CONF_ANNOUNCE_RETRIES: 1})
    timings: dict = {}
    await runtime.speak(TEXT, timings=timings, t0=time.monotonic())
    assert [c.data["media_player_entity_id"] for c in calls] == [[GROUP], [GROUP]]
    assert timings["attempts"] == 2
    assert timings["retry_reason"] == "cut_short"
    assert timings["outcome"] == "ok"
    assert "retry_ms" in timings
    assert not notify


async def test_every_try_cut_short_warns_on_the_phone(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _states(hass)
    calls = _tts(hass, [CUT])
    async_mock_service(hass, "media_player", "volume_set")
    notify = async_mock_service(hass, "notify", "mobile_app_phone")
    runtime = await _setup(hass, mock_entry, **{CONF_ANNOUNCE_RETRIES: 2})
    timings: dict = {}
    await runtime.speak(TEXT, timings=timings, t0=time.monotonic())
    assert len(calls) == 3
    assert timings["outcome"] == "cut_short"
    assert len(notify) == 1
    assert notify[0].data["message"] == f"{TEXT} (announcement was cut short)"


async def test_speakers_never_playing_retry_then_warn(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    """Group never starts, so the retry uses each speaker; it never plays: warn."""
    _states(hass)
    calls = _tts(hass, [[]])
    async_mock_service(hass, "media_player", "volume_set")
    notify = async_mock_service(hass, "notify", "mobile_app_phone")
    with patch(f"{C}.GROUP_START_TIMEOUT", 0):
        runtime = await _setup(hass, mock_entry, **{CONF_ANNOUNCE_RETRIES: 1})
        timings: dict = {}
        await runtime.speak(TEXT, timings=timings, t0=time.monotonic())
    assert [c.data["media_player_entity_id"] for c in calls] == [[GROUP], MEMBERS]
    assert timings["outcome"] == "not_started"
    assert len(notify) == 1
    assert "never started playing" in notify[0].data["message"]


async def test_retries_off_keeps_old_behaviour(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _states(hass)
    calls = _tts(hass, [CUT])
    async_mock_service(hass, "media_player", "volume_set")
    notify = async_mock_service(hass, "notify", "mobile_app_phone")
    runtime = await _setup(hass, mock_entry, **{CONF_ANNOUNCE_RETRIES: 0})
    timings: dict = {}
    await runtime.speak(TEXT, timings=timings, t0=time.monotonic())
    assert len(calls) == 1
    assert timings["attempts"] == 1
    assert not notify


async def test_failed_tts_call_is_retried(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    """No group: the text-to-speech call fails once, the retry works."""
    _states(hass)
    calls: list[ServiceCall] = []

    async def speak(call: ServiceCall) -> None:
        calls.append(call)
        if len(calls) == 1:
            raise RuntimeError("cloud TTS hiccup")
        hass.states.async_set("media_player.bedroom", "playing", {"media_content_id": "x"})
        hass.loop.call_later(
            1.5, lambda: hass.states.async_set("media_player.bedroom", "idle", {})
        )

    hass.services.async_register("tts", "speak", speak)
    async_mock_service(hass, "media_player", "volume_set")
    notify = async_mock_service(hass, "notify", "mobile_app_phone")
    with patch(f"{C}.PLAYBACK_START_TIMEOUT", 1):
        runtime = await _setup(
            hass, mock_entry, **{CONF_SPEAKER_GROUP: "", CONF_ANNOUNCE_RETRIES: 1}
        )
        timings: dict = {}
        await runtime.speak(TEXT, timings=timings, t0=time.monotonic())
    assert len(calls) == 2
    assert timings["retry_reason"] == "failed"
    assert timings["outcome"] == "ok"
    assert not notify


async def test_group_woken_once_then_waits_for_speakers(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    """With a group, only the group is woken; its speakers report in after."""
    _states(hass, group="off")
    hass.states.async_set("media_player.kitchen", "off", {})
    on: list[str] = []

    async def turn_on(call: ServiceCall) -> None:
        on.append(call.data["entity_id"])
        hass.states.async_set(GROUP, "idle", {})
        hass.loop.call_later(
            0.6,
            lambda: hass.states.async_set(
                "media_player.kitchen", "idle", {"volume_level": 0.3}
            ),
        )

    hass.services.async_register("media_player", "turn_on", turn_on)
    async_mock_service(hass, "media_player", "turn_off")
    calls = _tts(hass, [GOOD])
    vol = async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry, **{CONF_WAKE_WAIT: 5})
    timings: dict = {}
    await runtime.speak(TEXT, timings=timings, t0=time.monotonic())
    assert on == [GROUP]  # never each speaker
    assert timings["group_connected"] is True
    assert timings["tts_call_ms"] >= 600  # waited for the kitchen's volume
    assert ("media_player.kitchen", 0.6) in [
        (c.data["entity_id"], c.data["volume_level"]) for c in vol
    ]
    assert len(calls) == 1


async def test_group_off_is_not_waited_for(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    """0.9.0 waited for an off Cast group, which only comes on when played to."""
    _states(hass, group="off")
    calls = _tts(hass, [GOOD])
    async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry, **{CONF_WAKE_WAIT: 5})
    timings: dict = {}
    await runtime.speak(TEXT, timings=timings, t0=time.monotonic())
    assert "awake_timeout" not in timings
    assert timings["tts_call_ms"] < 1500
    assert [c.data["media_player_entity_id"] for c in calls] == [[GROUP]]
    assert timings["outcome"] == "ok"


async def test_group_connect_gives_up_and_speaks_anyway(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    """A speaker that never reports its volume doesn't stop the announcement."""
    _states(hass, group="off")
    hass.states.async_set("media_player.kitchen", "off", {})
    async_mock_service(hass, "media_player", "turn_on")
    async_mock_service(hass, "media_player", "turn_off")
    calls = _tts(hass, [GOOD])
    async_mock_service(hass, "media_player", "volume_set")
    with patch(f"{C}.GROUP_CONNECT_WAIT", 1):
        runtime = await _setup(hass, mock_entry)
        timings: dict = {}
        await runtime.speak(TEXT, timings=timings, t0=time.monotonic())
    assert timings["tts_call_ms"] >= 1000
    assert len(calls) == 1
    assert timings["outcome"] == "ok"


async def test_wake_wait_off_does_not_wait(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _states(hass, group="off")
    _tts(hass, [GOOD])
    async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry, **{CONF_WAKE_WAIT: 0})
    timings: dict = {}
    await runtime.speak(TEXT, timings=timings, t0=time.monotonic())
    assert "awake_ms" not in timings and "awake_timeout" not in timings
    assert timings["tts_call_ms"] < 500


async def test_retry_uses_backup_voice(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _states(hass)
    calls = _tts(hass, [CUT, GOOD])
    async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(
        hass,
        mock_entry,
        **{
            CONF_ANNOUNCE_RETRIES: 1,
            CONF_TTS_BACKUP: "tts.backup",
            CONF_TTS_LANGUAGE: "en-ZA",
        },
    )
    timings: dict = {}
    await runtime.speak(TEXT, timings=timings, t0=time.monotonic())
    assert [c.data["entity_id"] for c in calls] == ["tts.test", "tts.backup"]
    assert calls[0].data["language"] == "en-ZA"
    assert "language" not in calls[1].data  # the language is for the main voice
    assert timings["tts_used"] == "backup"
    assert timings["outcome"] == "ok"


def _sleepy_speakers(hass: HomeAssistant):
    """Speakers that are off (no volume) until turned on; record turn_on/off."""
    hass.states.async_set("media_player.bedroom", "off", {})
    hass.states.async_set("media_player.kitchen", "off", {})
    hass.states.async_set(GROUP, "off", {})
    on: list[str] = []
    off: list[str] = []

    def ids(call: ServiceCall) -> list[str]:
        e = call.data["entity_id"]
        return [e] if isinstance(e, str) else list(e)

    async def turn_on(call: ServiceCall) -> None:
        for e in ids(call):
            on.append(e)
            for x in [e, *(MEMBERS if e == GROUP else [])]:
                hass.states.async_set(x, "idle", {"volume_level": 0.4})

    async def turn_off(call: ServiceCall) -> None:
        for e in ids(call):
            off.append(e)
            for x in [e, *(MEMBERS if e == GROUP else [])]:
                hass.states.async_set(x, "off", {})

    hass.services.async_register("media_player", "turn_on", turn_on)
    hass.services.async_register("media_player", "turn_off", turn_off)
    return on, off


def _alert() -> dict:
    return {
        "id_str": "1",
        "umid_str": "u1",
        "title": "T",
        "message": "M",
        "app": "Datadog",
        "priority": 1,
        "date": int(time.time()),
    }


async def test_group_woken_once_and_put_back(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    """Speakers are never woken one by one: the group once, off again after."""
    on, off = _sleepy_speakers(hass)
    _tts(hass, [GOOD])
    async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry)
    runtime.enabled = True
    await runtime._on_alerts([_alert()], False)
    await hass.async_block_till_done(wait_background_tasks=True)
    timings = runtime.last_alert["timings"]
    assert on == [GROUP]
    assert off == [GROUP]  # it was off before, so off again after
    assert timings["outcome"] == "ok"


async def test_preconnect_group_when_chosen(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    on, _off = _sleepy_speakers(hass)
    _tts(hass, [GOOD])
    async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry, **{CONF_PRECONNECT_GROUP: True})
    runtime.enabled = True
    ai_calls = []

    async def slow_ai(*args, **kwargs):
        ai_calls.append(list(on))  # what was switched on while the AI worked
        await asyncio.sleep(0.3)

    with patch.object(runtime, "ai_wording", side_effect=slow_ai):
        await runtime._on_alerts([_alert()], False)
        await hass.async_block_till_done(wait_background_tasks=True)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert on == [GROUP]  # connected early, once; never each speaker
    assert ai_calls == [[]] or ai_calls == [[GROUP]]
    assert runtime.last_alert["timings"]["group_preconnected"] is True


async def test_not_prepared_when_switched_off(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    on, _off = _sleepy_speakers(hass)
    calls = _tts(hass, [GOOD])
    runtime = await _setup(hass, mock_entry)
    runtime.enabled = False
    await runtime._on_alerts([_alert()], False)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert not on and not calls


async def test_second_alert_keeps_first_snapshot(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    """Two alerts close together: speakers that were off are still put back off."""
    _on, off = _sleepy_speakers(hass)
    _tts(hass, [GOOD])
    async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry)
    runtime.enabled = True
    runtime._prepare({}, time.monotonic())
    await hass.async_block_till_done(wait_background_tasks=True)
    runtime._prepare({}, time.monotonic())  # speakers now awake; keep the first
    await runtime.speak(TEXT)
    assert off == [GROUP]
