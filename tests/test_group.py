"""Speaker group: plays all speakers in sync, with a fallback to each speaker."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.push_alert_tts.const import CONF_SPEAKER_GROUP

GROUP = "media_player.all_speakers"
MEMBERS = ["media_player.bedroom", "media_player.kitchen"]


@pytest.fixture(autouse=True)
def fast_group():
    with patch("custom_components.push_alert_tts.coordinator.GROUP_START_TIMEOUT", 0):
        yield


def _states(hass: HomeAssistant, group: str = "off") -> None:
    hass.states.async_set("media_player.bedroom", "idle", {"volume_level": 0.2})
    hass.states.async_set("media_player.kitchen", "idle", {"volume_level": 0.3})
    hass.states.async_set(GROUP, group, {})


def _msg(i: int) -> dict:
    return {
        "id_str": str(i),
        "umid_str": f"u{i}",
        "title": "T",
        "message": "M",
        "app": "Datadog",
        "priority": 0,
        "date": int(time.time()),
    }


async def _setup(hass, entry, group: str | None = GROUP, **options):
    entry.add_to_hass(hass)
    extra = {CONF_SPEAKER_GROUP: group} if group else {}
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, **extra, **options}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry.runtime_data


def _tts(hass: HomeAssistant, group_plays: bool = True, fail_on_group: bool = False):
    """A tts.speak that makes the group report playing (then idle)."""
    calls: list[ServiceCall] = []

    async def speak(call: ServiceCall) -> None:
        calls.append(call)
        players = call.data["media_player_entity_id"]
        if players == [GROUP]:
            if fail_on_group:
                raise RuntimeError("group gone")
            if group_plays:
                hass.states.async_set(
                    GROUP, "playing", {"media_content_id": f"tts-{len(calls)}"}
                )
                hass.loop.call_later(
                    0.3, lambda: hass.states.async_set(GROUP, "idle", {})
                )

    hass.services.async_register("tts", "speak", speak)
    return calls


def _targets(calls):
    return [c.data["media_player_entity_id"] for c in calls]


async def test_group_plays_in_sync_and_sets_member_volumes(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _states(hass)
    calls = _tts(hass)
    vol = async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry)
    timings: dict = {}
    await runtime.speak("hello", timings=timings, t0=time.monotonic())
    assert _targets(calls) == [[GROUP]]
    levels = [(c.data["entity_id"], c.data["volume_level"]) for c in vol]
    assert ("media_player.bedroom", 0.6) in levels
    assert ("media_player.bedroom", 0.2) in levels  # restored
    assert ("media_player.kitchen", 0.3) in levels
    assert all(c.data["entity_id"] != GROUP for c in vol)
    assert timings["route"] == "group"
    assert "playback_start_ms" in timings and "playback_end_ms" in timings


async def test_group_not_playing_falls_back_to_each_speaker(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _states(hass)
    calls = _tts(hass, group_plays=False)
    async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry)
    timings: dict = {}
    await runtime.speak("hello", timings=timings, t0=time.monotonic())
    assert _targets(calls) == [[GROUP], MEMBERS]
    assert timings["route"] == "group_fallback"
    assert "group_fallback_ms" in timings


async def test_group_error_falls_back_without_phone_warning(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _states(hass)
    calls = _tts(hass, fail_on_group=True)
    async_mock_service(hass, "media_player", "volume_set")
    notify = async_mock_service(hass, "notify", "mobile_app_phone")
    runtime = await _setup(hass, mock_entry)
    await runtime.speak("hello")
    assert _targets(calls) == [[GROUP], MEMBERS]
    assert not notify  # the alert was still spoken


async def test_unavailable_group_uses_each_speaker(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _states(hass, group="unavailable")
    calls = _tts(hass)
    async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry)
    timings: dict = {}
    await runtime.speak("hello", timings=timings, t0=time.monotonic())
    assert _targets(calls) == [MEMBERS]
    assert timings["route"] == "group_fallback"


async def test_no_group_unchanged(hass: HomeAssistant, mock_entry, no_listener) -> None:
    _states(hass)
    calls = _tts(hass)
    async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry, group=None)
    timings: dict = {}
    await runtime.speak("hello", timings=timings, t0=time.monotonic())
    assert _targets(calls) == [MEMBERS]
    assert timings["route"] == "speakers"
    assert "group_fallback_ms" not in timings


async def test_group_only_plays_on_group(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _states(hass)
    calls = _tts(hass)
    vol = async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry, speakers=[])
    await runtime.speak("hello")
    assert _targets(calls) == [[GROUP]]
    assert {c.data["entity_id"] for c in vol} == {GROUP}


async def test_emergency_alert_falls_back_too(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _states(hass)
    calls = _tts(hass, group_plays=False)
    async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry)
    runtime.enabled = True
    await runtime._on_alerts([{**_msg(1), "priority": 2, "receipt": "r1"}], False)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert _targets(calls) == [[GROUP], MEMBERS]


async def test_options_reject_group_in_speakers(
    hass: HomeAssistant, mock_entry
) -> None:
    mock_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    base = {"min_priority": "-2", "message_mode": "fixed"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**base, "speakers": [*MEMBERS, GROUP], CONF_SPEAKER_GROUP: GROUP},
    )
    assert result["errors"] == {CONF_SPEAKER_GROUP: "group_in_speakers"}
    with patch(
        "custom_components.push_alert_tts.async_setup_entry",
        new=AsyncMock(return_value=True),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {**base, "speakers": MEMBERS, CONF_SPEAKER_GROUP: GROUP},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_entry.options[CONF_SPEAKER_GROUP] == GROUP
