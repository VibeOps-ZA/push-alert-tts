"""Entities, announcing, repeats and acknowledging."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.push_alert_tts.const import EVENT_ALERT


def _speakers(hass: HomeAssistant, kitchen: str = "idle") -> None:
    hass.states.async_set("media_player.bedroom", "idle", {"volume_level": 0.2})
    hass.states.async_set("media_player.kitchen", kitchen, {"volume_level": 0.3})


async def _setup(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry.runtime_data


def _msg(i, **kw):
    return {
        "id_str": str(i),
        "umid_str": f"u{i}",
        "title": "T",
        "message": "M",
        "app": "Datadog",
        "priority": 0,
        "date": int(time.time()),
        **kw,
    }


async def test_entities_created(hass: HomeAssistant, mock_entry, no_listener) -> None:
    await _setup(hass, mock_entry)
    for entity_id in (
        "switch.push_alert_tts",
        "switch.push_alert_tts_repeat_emergencies",
        "number.push_alert_tts_announce_volume",
        "button.push_alert_tts_acknowledge",
        "button.push_alert_tts_test_announcement",
        "binary_sensor.push_alert_tts_pushover_connected",
        "sensor.push_alert_tts_last_alert",
    ):
        assert hass.states.get(entity_id) is not None, entity_id
    assert hass.states.get("number.push_alert_tts_announce_volume").state == "60"


async def test_disabled_does_not_speak(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _speakers(hass)
    tts = async_mock_service(hass, "tts", "speak")
    events = []
    hass.bus.async_listen(EVENT_ALERT, events.append)
    runtime = await _setup(hass, mock_entry)
    await runtime._on_alerts([_msg(1)], queued=False)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert not tts
    assert events[0].data["announced"] is False


async def test_enabled_speaks_on_all_speakers(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _speakers(hass)
    tts = async_mock_service(hass, "tts", "speak")
    vol = async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.push_alert_tts"}, blocking=True
    )
    with patch(
        "custom_components.push_alert_tts.coordinator.PLAYBACK_START_TIMEOUT", 0
    ):
        await runtime._on_alerts([_msg(1)], queued=False)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert len(tts) == 1
    assert tts[0].data["media_player_entity_id"] == [
        "media_player.bedroom",
        "media_player.kitchen",
    ]
    assert tts[0].data["message"] == "Alert received"
    levels = [(c.data["entity_id"], c.data["volume_level"]) for c in vol]
    assert ("media_player.bedroom", 0.6) in levels and (
        "media_player.bedroom",
        0.2,
    ) in levels
    assert ("media_player.kitchen", 0.3) in levels  # restored


async def test_queued_batch_says_multiple(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _speakers(hass)
    tts = async_mock_service(hass, "tts", "speak")
    async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry)
    runtime.enabled = True
    with patch(
        "custom_components.push_alert_tts.coordinator.PLAYBACK_START_TIMEOUT", 0
    ):
        await runtime._on_alerts([_msg(1), _msg(2)], queued=True)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert tts[0].data["message"] == "Multiple Pushover alerts recorded"


async def test_unavailable_speaker_notifies_phone(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _speakers(hass, kitchen="unavailable")
    tts = async_mock_service(hass, "tts", "speak")
    async_mock_service(hass, "media_player", "volume_set")
    notify = async_mock_service(hass, "notify", "mobile_app_phone")
    runtime = await _setup(hass, mock_entry)
    runtime.enabled = True
    with patch(
        "custom_components.push_alert_tts.coordinator.PLAYBACK_START_TIMEOUT", 0
    ):
        await runtime._on_alerts([_msg(1)], queued=False)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert tts[0].data["media_player_entity_id"] == ["media_player.bedroom"]
    assert "media_player.kitchen" in notify[0].data["message"]


async def test_duplicate_emergency_resend_not_repeated(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _speakers(hass)
    tts = async_mock_service(hass, "tts", "speak")
    async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry)
    runtime.enabled = True
    with patch(
        "custom_components.push_alert_tts.coordinator.PLAYBACK_START_TIMEOUT", 0
    ):
        await runtime._on_alerts([_msg(1, priority=2, receipt="r1")], queued=False)
        await runtime._on_alerts(
            [_msg(2, umid_str="u1", priority=2, receipt="r1")], queued=False
        )
        await hass.async_block_till_done(wait_background_tasks=True)
    assert len(tts) == 1
    assert runtime.pending_receipts == ["r1"]


async def test_acknowledge_button(hass: HomeAssistant, mock_entry, no_listener) -> None:
    runtime = await _setup(hass, mock_entry)
    runtime._receipts = {"r1": time.time() + 60, "r2": time.time() + 60}
    with patch(
        "custom_components.push_alert_tts.client.api.async_acknowledge", new=AsyncMock()
    ) as ack:
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.push_alert_tts_acknowledge"},
            blocking=True,
        )
    assert [c.args[2] for c in ack.await_args_list] == ["r1", "r2"]
    assert runtime.pending_receipts == []


async def test_speak_action(hass: HomeAssistant, mock_entry, no_listener) -> None:
    _speakers(hass)
    tts = async_mock_service(hass, "tts", "speak")
    async_mock_service(hass, "media_player", "volume_set")
    await _setup(hass, mock_entry)
    with patch(
        "custom_components.push_alert_tts.coordinator.PLAYBACK_START_TIMEOUT", 0
    ):
        await hass.services.async_call(
            "push_alert_tts", "speak", {"message": "hello"}, blocking=True
        )
    assert tts[0].data["message"] == "hello"


async def test_repeat_until_acknowledged(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _speakers(hass)
    tts = async_mock_service(hass, "tts", "speak")
    async_mock_service(hass, "media_player", "volume_set")
    mock_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_entry,
        options={**mock_entry.options, "repeat_interval": 0.05, "repeat_max": 5},
    )
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    runtime = mock_entry.runtime_data
    runtime.enabled = True
    runtime.repeat_until_ack = True
    with (
        patch("custom_components.push_alert_tts.coordinator.PLAYBACK_START_TIMEOUT", 0),
        patch(
            "custom_components.push_alert_tts.client.api.async_acknowledge",
            new=AsyncMock(),
        ) as ack,
    ):
        await runtime._on_alerts([_msg(1, priority=2, receipt="r1")], queued=False)
        await hass.async_block_till_done(wait_background_tasks=True)
        assert len(tts) == 6  # first announcement + 5 repeats (never acknowledged)
        await runtime._on_alerts([_msg(2, priority=2, receipt="r2")], queued=False)
        await runtime.acknowledge()  # acknowledged straight away
        await hass.async_block_till_done(wait_background_tasks=True)
    assert len(tts) == 7  # second alert spoken once, no repeats after the ack
    assert runtime.pending_receipts == []
    assert {c.args[2] for c in ack.await_args_list} == {"r1", "r2"}


async def test_ack_on_phone_stops_repeats(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    runtime = await _setup(hass, mock_entry)
    runtime.enabled = True
    runtime._receipts = {"r1": time.time() + 600}
    await runtime._on_alerts([_msg(5, priority=2, receipt="r1", acked=1)], queued=False)
    assert runtime.pending_receipts == []
    assert runtime._ack_event.is_set()


async def test_concurrent_acknowledge(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    import asyncio

    runtime = await _setup(hass, mock_entry)
    runtime._receipts = {"r1": time.time() + 600}
    with patch(
        "custom_components.push_alert_tts.client.api.async_acknowledge", new=AsyncMock()
    ):
        await asyncio.gather(runtime.acknowledge(), runtime.acknowledge())
    assert runtime.pending_receipts == []


async def test_no_offline_alert_after_unload(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    notify = async_mock_service(hass, "notify", "mobile_app_phone")
    runtime = await _setup(hass, mock_entry)
    runtime.enabled = True
    await hass.config_entries.async_unload(mock_entry.entry_id)
    runtime.listener.status = "stopped"
    runtime._on_status()
    assert runtime._offline_timer is None
    assert not notify


async def test_hung_tts_times_out_and_notifies(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    import asyncio

    _speakers(hass)
    async_mock_service(hass, "media_player", "volume_set")
    notify = async_mock_service(hass, "notify", "mobile_app_phone")

    async def hang(call):
        await asyncio.sleep(10)

    hass.services.async_register("tts", "speak", hang)
    runtime = await _setup(hass, mock_entry)
    with patch("custom_components.push_alert_tts.coordinator.TTS_TIMEOUT", 0.05):
        await runtime.speak("hello")
    assert "announcement failed" in notify[0].data["message"]
    assert not runtime._speak_lock.locked()


async def test_muted_and_off_speakers_restored(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    hass.states.async_set(
        "media_player.bedroom", "off", {"volume_level": 0.2, "is_volume_muted": True}
    )
    hass.states.async_set("media_player.kitchen", "idle", {"volume_level": 0.3})
    async_mock_service(hass, "tts", "speak")
    async_mock_service(hass, "media_player", "volume_set")
    mute = async_mock_service(hass, "media_player", "volume_mute")
    off = async_mock_service(hass, "media_player", "turn_off")
    runtime = await _setup(hass, mock_entry)
    await runtime.speak("hello")
    assert [c.data["is_volume_muted"] for c in mute] == [False, True]
    assert [c.data["entity_id"] for c in off] == ["media_player.bedroom"]
