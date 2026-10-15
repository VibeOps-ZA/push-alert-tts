"""Alert history, the preview action and the regex time limit."""

from __future__ import annotations

import os
import time
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.push_alert_tts.const import DOMAIN
from custom_components.push_alert_tts.coordinator import (
    append_history,
    prune_history,
    read_history,
)


async def _setup(hass, entry, **options):
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry.runtime_data


def _msg(i, title="[P1] Triggered: disk | db_01", **kw):
    return {
        "id_str": str(i),
        "umid_str": f"u{i}",
        "title": title,
        "message": "body",
        "app": "Monitor",
        "priority": 0,
        "date": int(time.time()),
        **kw,
    }


TEMPLATE = {
    "message_mode": "regex",
    "regex": r"\[P\d\]\s*(?P<state>[A-Za-z -]+):\s*(?P<s1>[^|]+)\|\s*(?P<s2>.+)",
    "regex_source": "title",
    "spoken_template": "Alert, {s1}, {s2}, {state}",
}


async def test_history_recorded_and_searchable(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    runtime = await _setup(hass, mock_entry, history_days=31, **TEMPLATE)
    await runtime._on_alerts([_msg(1), _msg(2, title="other")], queued=False)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert os.path.exists(runtime.history_path)

    result = await hass.services.async_call(
        DOMAIN, "get_history", {}, blocking=True, return_response=True
    )
    assert result["history_days"] == 31
    assert [a["title"] for a in result["alerts"]] == [
        "other",
        "[P1] Triggered: disk | db_01",
    ]
    result = await hass.services.async_call(
        DOMAIN, "get_history", {"search": "DB_01"}, blocking=True, return_response=True
    )
    assert len(result["alerts"]) == 1


async def test_history_off_records_nothing_and_deletes(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    runtime = await _setup(hass, mock_entry, history_days=5)
    await runtime._on_alerts([_msg(1)], queued=False)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert os.path.exists(runtime.history_path)
    hass.config_entries.async_update_entry(
        mock_entry, options={**mock_entry.options, "history_days": 0}
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert not os.path.exists(runtime.history_path)
    await runtime._on_alerts([_msg(2)], queued=False)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert not os.path.exists(runtime.history_path)


def test_prune_and_read(tmp_path) -> None:
    path = str(tmp_path / "h" / "history.jsonl")
    now = dt_util.utcnow()
    old = {"received": (now - timedelta(days=40)).isoformat(), "title": "old"}
    new = {"received": now.isoformat(), "title": "new"}
    append_history(path, [old, new])
    with open(path, "a", encoding="utf-8") as handle:
        handle.write('{"broken')  # half-written line
    assert prune_history(path, 31, now) == 1
    assert [r["title"] for r in read_history(path, 0, 10, None, now)] == ["new"]
    prune_history(path, 0, now)
    assert not os.path.exists(path)


async def test_preview_last_alert_and_speak(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    hass.states.async_set("media_player.bedroom", "idle", {"volume_level": 0.2})
    hass.states.async_set("media_player.kitchen", "idle", {"volume_level": 0.3})
    tts = async_mock_service(hass, "tts", "speak")
    async_mock_service(hass, "media_player", "volume_set")
    runtime = await _setup(hass, mock_entry, **TEMPLATE)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "preview", {"last_alert": True}, blocking=True, return_response=True
        )

    await runtime._on_alerts([_msg(1)], queued=False)  # disabled: not spoken
    await hass.async_block_till_done(wait_background_tasks=True)
    assert not tts
    result = await hass.services.async_call(
        DOMAIN,
        "preview",
        {"last_alert": True, "speak": True},
        blocking=True,
        return_response=True,
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert result["spoken_text"] == "Alert, disk, db 01, Triggered"
    assert result["outcome"] == "template"
    assert result["groups"]["s1"] == "disk "
    assert tts[0].data["message"] == "Alert, disk, db 01, Triggered"

    result = await hass.services.async_call(
        DOMAIN,
        "preview",
        {"title": "nothing useful"},
        blocking=True,
        return_response=True,
    )
    assert result["outcome"] == "fallback_no_match"


async def test_slow_regex_falls_back(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    runtime = await _setup(hass, mock_entry, **TEMPLATE)

    def slow(*_args):
        time.sleep(0.3)
        return {"text": "late", "outcome": "template", "groups": {}}

    with (
        patch("custom_components.push_alert_tts.coordinator.TEXT_TIMEOUT", 0.05),
        patch("custom_components.push_alert_tts.coordinator.build_spoken", slow),
    ):
        result = await runtime.compute_spoken([_msg(1)])
    assert result == {
        "text": "Alert received",
        "outcome": "fallback_timeout",
        "groups": {},
    }
