"""AI wording: the LLM call, fallbacks, memory, review sensor and options."""

from __future__ import annotations

import json
import os
import time
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.push_alert_tts import ai_wording as llm
from custom_components.push_alert_tts.const import DOMAIN
from custom_components.push_alert_tts.memory import (
    read_memory,
    split_lines,
    write_memory,
)

OLLAMA = "http://llm.local:11434"
CHAT = f"{OLLAMA}/api/chat"
AI = {
    "ai_enabled": True,
    "ai_api": "ollama",
    "ai_url": OLLAMA,
    "ai_model": "test-model",
    "ai_timeout": 60,
    "ai_emergency_timeout": 5,
    "ai_max_words": 20,
    "history_days": 31,
}


def _answer(text: str) -> dict:
    return {"message": {"role": "assistant", "content": text}}


def _msg(i, title="[P1] Triggered: disk | acme.db1.prod [P1]", **kw):
    return {
        "id_str": str(i),
        "umid_str": f"u{i}",
        "title": title,
        "message": f"{title}\nDisk usage over 90% on acme.db1.prod",
        "app": "Monitor",
        "priority": 1,
        "date": int(time.time()),
        **kw,
    }


def _speakers(hass: HomeAssistant) -> None:
    hass.states.async_set("media_player.bedroom", "idle", {"volume_level": 0.2})
    hass.states.async_set("media_player.kitchen", "idle", {"volume_level": 0.3})


async def _setup(hass, entry, **options):
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry.runtime_data


async def _alert(hass, runtime, *msgs) -> None:
    await runtime._on_alerts(list(msgs), queued=False)
    await hass.async_block_till_done(wait_background_tasks=True)


def _history(runtime) -> list[dict]:
    with open(runtime.history_path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


# -- plain functions ---------------------------------------------------------------
@pytest.mark.parametrize(
    ("answer", "text", "reason"),
    [
        (
            "P1 alert at Acme on database 1. Disk full.",
            "P1 alert at Acme on database 1. Disk full.",
            None,
        ),
        ('  "P1 alert at Acme. Disk full."  ', "P1 alert at Acme. Disk full.", None),
        (
            "<think>hmm</think>P1 alert at Acme. Disk full.",
            "P1 alert at Acme. Disk full.",
            None,
        ),
        ("", None, llm.REASON_EMPTY),
        ("word " * 40, None, llm.REASON_TOO_LONG),
        ("**P1** alert at Acme", None, llm.REASON_SYMBOLS),
        ("See https://example.com", None, llm.REASON_SYMBOLS),
        ("host acme_db1 is down", None, llm.REASON_SYMBOLS),
        ("Sure! Here is the message", None, llm.REASON_SHAPE),
    ],
)
def test_check_answer(answer, text, reason) -> None:
    assert llm.check_answer(answer, 20, r"^(P\d alert|Alert) at ") == (text, reason)


def test_check_answer_without_pattern() -> None:
    assert llm.check_answer("Disk full on Acme.", 20, None) == (
        "Disk full on Acme.",
        None,
    )


def test_alert_text_is_raw_and_not_repeated() -> None:
    assert llm.alert_text({"title": "T", "message": "T\nbody"}) == "T\nbody"
    assert llm.alert_text({"title": "T", "message": "body"}) == "T\nbody"
    assert llm.alert_text({"title": "T", "message": ""}) == "T"
    assert llm.alert_text({"message": "only body"}) == "only body"


def test_system_prompt_adds_memory_and_words() -> None:
    prompt = llm.system_prompt(None, ["Say HAProxy as HA proxy", " "], 15)
    assert "At most 15 words" in prompt
    assert prompt.endswith(llm.MEMORY_HEADING + "\n- Say HAProxy as HA proxy")
    assert llm.system_prompt("Custom {max_words}", [], 9) == "Custom 9"


def test_endpoints() -> None:
    assert llm.endpoint("ollama", "http://h:11434/") == "http://h:11434/api/chat"
    assert (
        llm.endpoint("openai", "http://h:1234") == "http://h:1234/v1/chat/completions"
    )
    assert (
        llm.endpoint("openai", "http://h:1234/v1")
        == "http://h:1234/v1/chat/completions"
    )


def test_memory_file_and_versions(tmp_path) -> None:
    path = str(tmp_path / "ai_memory_x.txt")
    versions = str(tmp_path / "versions")
    now = __import__("datetime").datetime(2026, 1, 1)
    assert read_memory(path) == []
    write_memory(path, ["one"], versions, now)
    assert not os.path.exists(versions)  # nothing to keep yet
    for i in range(25):
        write_memory(
            path, ["one", f"v{i}"], versions, now.replace(second=i % 60, minute=i)
        )
    assert read_memory(path) == ["one", "v24"]
    assert len(os.listdir(versions)) == 20
    assert split_lines("- a\n\n  * b  \n") == ["a", "b"]


async def test_openai_compatible_answer(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(
        "http://h:1234/v1/chat/completions",
        json={"choices": [{"message": {"content": "Alert at Acme. Disk full."}}]},
    )
    answer = await llm.ask(
        async_get_clientsession(hass),
        api="openai",
        url="http://h:1234",
        model="m",
        system="s",
        user="u",
        timeout=5,
        api_key="k",
    )
    assert answer == "Alert at Acme. Disk full."
    _method, _url, body, headers = aioclient_mock.mock_calls[0]
    assert body["temperature"] == 0 and headers["Authorization"] == "Bearer k"


async def test_ollama_without_think_support(
    hass: HomeAssistant, aioclient_mock
) -> None:
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMockResponse,
    )

    calls = []

    async def _reply(method, url, data):
        calls.append(dict(data))
        if "think" in data:
            return AiohttpClientMockResponse(
                method,
                url,
                status=400,
                text='{"error":"model does not support thinking"}',
            )
        return AiohttpClientMockResponse(
            method, url, json=_answer("Alert at Acme. ok.")
        )

    aioclient_mock.post(CHAT, side_effect=_reply)
    answer = await llm.ask(
        async_get_clientsession(hass),
        api="ollama",
        url=OLLAMA,
        model="m",
        system="s",
        user="u",
        timeout=5,
    )
    assert answer == "Alert at Acme. ok."
    assert "think" in calls[0] and "think" not in calls[1]


# -- runtime -------------------------------------------------------------------------
async def test_ai_text_is_spoken_and_recorded(
    hass: HomeAssistant, mock_entry, no_listener, aioclient_mock
) -> None:
    _speakers(hass)
    tts = async_mock_service(hass, "tts", "speak")
    async_mock_service(hass, "media_player", "volume_set")
    aioclient_mock.post(
        CHAT, json=_answer("P1 alert at Acme on database 1. Disk over 90 percent.")
    )
    runtime = await _setup(hass, mock_entry, **AI)
    await runtime.async_add_memory("Say HAProxy as HA proxy")
    runtime.enabled = True

    await _alert(hass, runtime, _msg(1))

    assert (
        tts[0].data["message"]
        == "P1 alert at Acme on database 1. Disk over 90 percent."
    )
    _method, _url, body, _headers = aioclient_mock.mock_calls[0]
    assert body["model"] == "test-model" and body["think"] is False
    assert "num_ctx" not in body["options"] and "keep_alive" not in body  # defaults
    assert "num_gpu" not in body["options"]
    assert body["messages"][1]["content"] == _msg(1)["message"]  # raw, untouched
    assert "- Say HAProxy as HA proxy" in body["messages"][0]["content"]

    row = _history(runtime)[-1]
    assert row["spoken_source"] == "ai"
    assert row["ai_reason"] is None and row["filter_text"] == "Alert received"
    assert {
        "text_ms",
        "ai_done_ms",
        "speak_start_ms",
        "tts_call_ms",
        "tts_done_ms",
    } <= set(row["timings"])
    assert row["message_length"] == len(_msg(1)["message"])

    review = hass.states.get("sensor.push_alert_tts_ai_review")
    assert review.state == "1"
    assert review.attributes["alerts"][0]["alert"] == _msg(1)["message"]
    assert review.attributes["alerts"][0]["spoken"].startswith("P1 alert at Acme")
    last = hass.states.get("sensor.push_alert_tts_last_alert").attributes
    assert last["spoken_source"] == "ai"


async def test_unreachable_llm_falls_back_and_is_skipped(
    hass: HomeAssistant, mock_entry, no_listener, aioclient_mock
) -> None:
    _speakers(hass)
    tts = async_mock_service(hass, "tts", "speak")
    async_mock_service(hass, "media_player", "volume_set")
    aioclient_mock.post(CHAT, exc=aiohttp.ClientConnectionError("refused"))
    runtime = await _setup(hass, mock_entry, **AI)
    runtime.enabled = True

    await _alert(hass, runtime, _msg(1))
    await _alert(hass, runtime, _msg(2))

    assert [c.data["message"] for c in tts] == ["Alert received", "Alert received"]
    assert len(aioclient_mock.mock_calls) == 1  # second alert didn't wait for it
    reasons = [r["ai_reason"] for r in _history(runtime)]
    assert reasons == [llm.REASON_OFFLINE, llm.REASON_OFFLINE_RECENT]


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"exc": TimeoutError()}, llm.REASON_TIMEOUT),
        ({"status": 500, "text": "boom"}, llm.REASON_HTTP),
        ({"json": {"unexpected": True}}, llm.REASON_BAD_RESPONSE),
        ({"json": _answer("Sure, here you go")}, llm.REASON_SHAPE),
    ],
)
async def test_bad_answers_fall_back(
    hass: HomeAssistant, mock_entry, no_listener, aioclient_mock, kwargs, reason
) -> None:
    _speakers(hass)
    tts = async_mock_service(hass, "tts", "speak")
    async_mock_service(hass, "media_player", "volume_set")
    aioclient_mock.post(CHAT, **kwargs)
    runtime = await _setup(
        hass, mock_entry, **AI, ai_start_pattern=r"^(P\d alert|Alert) at "
    )
    runtime.enabled = True
    await _alert(hass, runtime, _msg(1))
    assert tts[0].data["message"] == "Alert received"
    assert _history(runtime)[-1]["ai_reason"] == reason


async def test_emergency_uses_short_timeout(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    runtime = await _setup(hass, mock_entry, **AI)
    with patch(
        "custom_components.push_alert_tts.ai_wording.ask",
        new=AsyncMock(return_value="Alert at Acme. Down."),
    ) as ask:
        await _alert(hass, runtime, _msg(1, priority=2, receipt="r1"))
        await _alert(hass, runtime, _msg(2))
    assert [c.kwargs["timeout"] for c in ask.call_args_list] == [5, 60]


async def test_ai_off_and_queued_batches_unchanged(
    hass: HomeAssistant, mock_entry, no_listener, aioclient_mock
) -> None:
    runtime = await _setup(hass, mock_entry, history_days=31)
    await _alert(hass, runtime, _msg(1))
    assert "ai_reason" not in _history(runtime)[-1]
    hass.config_entries.async_update_entry(
        mock_entry, options={**mock_entry.options, **AI}
    )
    await _alert(hass, runtime, _msg(2), _msg(3))
    assert not aioclient_mock.mock_calls
    assert _history(runtime)[-1]["ai_reason"] == llm.REASON_MULTIPLE


async def test_correction_box_and_memory_actions(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    runtime = await _setup(hass, mock_entry, **AI)
    await hass.services.async_call(
        "text",
        "set_value",
        {
            "entity_id": "text.push_alert_tts_ai_correction",
            "value": "Shop is two separate clients",
        },
        blocking=True,
    )
    state = hass.states.get("text.push_alert_tts_ai_correction")
    assert state.state == ""
    assert state.attributes["memory"] == ["Shop is two separate clients"]
    result = await hass.services.async_call(
        DOMAIN,
        "add_ai_memory",
        {"text": "Say HAProxy as HA proxy"},
        blocking=True,
        return_response=True,
    )
    assert result["memory"] == ["Shop is two separate clients", "Say HAProxy as HA proxy"]
    got = await hass.services.async_call(
        DOMAIN, "get_ai_memory", {}, blocking=True, return_response=True
    )
    assert got["memory"] == result["memory"]
    assert (
        await hass.async_add_executor_job(read_memory, runtime.memory_path)
        == result["memory"]
    )


async def test_preview_with_ai(
    hass: HomeAssistant, mock_entry, no_listener, aioclient_mock
) -> None:
    aioclient_mock.post(CHAT, json=_answer("P1 alert at Acme. Disk full."))
    await _setup(hass, mock_entry, **AI)
    result = await hass.services.async_call(
        DOMAIN,
        "preview",
        {"title": "[P1] Triggered: disk | acme.db1.prod", "message": "x"},
        blocking=True,
        return_response=True,
    )
    assert result["spoken_text"] == "P1 alert at Acme. Disk full."
    assert result["spoken_source"] == "ai" and result["filter_text"] == "Alert received"
    result = await hass.services.async_call(
        DOMAIN,
        "preview",
        {"title": "t", "use_ai": False},
        blocking=True,
        return_response=True,
    )
    assert result["spoken_source"] == "filter" and result["ai_reason"] is None


async def test_options_ai_section(hass: HomeAssistant, mock_entry, no_listener) -> None:
    runtime = await _setup(hass, mock_entry)
    base = {"message_mode": "fixed", "min_priority": "-2"}
    flow = await hass.config_entries.options.async_init(mock_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {**base, "ai_wording": {"ai_enabled": True, "ai_model": "m"}}
    )
    assert result["errors"] == {"base": "ai_url_required"}
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {
            **base,
            "ai_wording": {
                "ai_enabled": True,
                "ai_url": OLLAMA,
                "ai_model": "m",
                "ai_timeout": 60,
                "ai_memory": "Say HAProxy as HA proxy\n\nXyz servers: leave the name out",
            },
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_entry.options["ai_url"] == OLLAMA and mock_entry.options["ai_enabled"]
    assert "ai_memory" not in mock_entry.options
    assert runtime.memory == [
        "Say HAProxy as HA proxy",
        "Xyz servers: leave the name out",
    ]
    assert runtime.ai_enabled

    # Bad keep-alive is refused.
    flow = await hass.config_entries.options.async_init(mock_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {
            **base,
            "ai_wording": {
                "ai_enabled": True,
                "ai_url": OLLAMA,
                "ai_model": "m",
                "ai_keep_alive": "ten minutes",
            },
        },
    )
    assert result["errors"] == {"base": "ai_invalid_keep_alive"}

    # Saving without the section keeps the AI settings.
    flow = await hass.config_entries.options.async_init(mock_entry.entry_id)
    result = await hass.config_entries.options.async_configure(flow["flow_id"], base)
    assert mock_entry.options["ai_url"] == OLLAMA


def test_keep_alive_value():
    from custom_components.push_alert_tts.ai_wording import keep_alive_value

    assert keep_alive_value("") is None
    assert keep_alive_value(None) is None
    assert keep_alive_value(" -1 ") == -1
    assert keep_alive_value("3600") == 3600
    assert keep_alive_value("10m") == "10m"
    assert keep_alive_value("1h30m") == "1h30m"
    for bad in ("ten minutes", "5x", "-"):
        with pytest.raises(ValueError):
            keep_alive_value(bad)


async def test_ollama_model_settings_are_sent(
    hass: HomeAssistant, mock_entry, no_listener, aioclient_mock
) -> None:
    _speakers(hass)
    async_mock_service(hass, "tts", "speak")
    async_mock_service(hass, "media_player", "volume_set")
    aioclient_mock.post(CHAT, json=_answer("P1 alert at Acme. Disk full."))
    runtime = await _setup(
        hass,
        mock_entry,
        **AI,
        ai_context_size=8192,
        ai_keep_alive="-1",
        ai_gpu_layers=32,
    )
    runtime.enabled = True

    await _alert(hass, runtime, _msg(1))

    _method, _url, body, _headers = aioclient_mock.mock_calls[0]
    assert body["options"]["num_ctx"] == 8192
    assert body["options"]["num_gpu"] == 32
    assert body["keep_alive"] == -1
    assert _history(runtime)[-1]["spoken_source"] == "ai"


async def test_invalid_stored_keep_alive_is_ignored(
    hass: HomeAssistant, mock_entry, no_listener, aioclient_mock
) -> None:
    _speakers(hass)
    async_mock_service(hass, "tts", "speak")
    async_mock_service(hass, "media_player", "volume_set")
    aioclient_mock.post(CHAT, json=_answer("P1 alert at Acme. Disk full."))
    runtime = await _setup(hass, mock_entry, **AI, ai_keep_alive="soon")
    runtime.enabled = True

    await _alert(hass, runtime, _msg(1))

    _method, _url, body, _headers = aioclient_mock.mock_calls[0]
    assert "keep_alive" not in body  # bad value: server default, alert still worded
    assert _history(runtime)[-1]["spoken_source"] == "ai"


async def test_gpu_layers_zero_means_cpu_only(
    hass: HomeAssistant, mock_entry, no_listener, aioclient_mock
) -> None:
    _speakers(hass)
    async_mock_service(hass, "tts", "speak")
    async_mock_service(hass, "media_player", "volume_set")
    aioclient_mock.post(CHAT, json=_answer("P1 alert at Acme. Disk full."))
    runtime = await _setup(hass, mock_entry, **AI, ai_gpu_layers=0)
    runtime.enabled = True

    await _alert(hass, runtime, _msg(1))

    _method, _url, body, _headers = aioclient_mock.mock_calls[0]
    assert body["options"]["num_gpu"] == 0
