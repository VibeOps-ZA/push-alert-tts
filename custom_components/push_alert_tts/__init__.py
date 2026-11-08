"""Push Alert TTS - speak Pushover alerts on Home Assistant speakers.

An unofficial Pushover Open Client. Home Assistant registers as its own
Pushover device, so phones and computers keep receiving alerts as normal.
Not made, endorsed or supported by Pushover, LLC.
"""

from __future__ import annotations

import os

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import as_int
from .const import (
    AI_BACKFILL_DEFAULT_DAYS,
    AI_BACKFILL_MAX,
    DOMAIN,
    MAX_HISTORY_DAYS,
)
from .coordinator import AlertTTS

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_ACK = "acknowledge"
SERVICE_SPEAK = "speak"
SERVICE_HISTORY = "get_history"
SERVICE_PREVIEW = "preview"
SERVICE_ADD_MEMORY = "add_ai_memory"
SERVICE_GET_MEMORY = "get_ai_memory"
SERVICE_REPROCESS = "reprocess_ai"
REPROCESS_SCHEMA = vol.Schema(
    {
        vol.Optional("days", default=AI_BACKFILL_DEFAULT_DAYS): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_HISTORY_DAYS)
        ),
        vol.Optional("limit", default=100): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=AI_BACKFILL_MAX)
        ),
    }
)
ADD_MEMORY_SCHEMA = vol.Schema({vol.Required("text"): cv.string})
SPEAK_SCHEMA = vol.Schema({vol.Required("message"): cv.string})
HISTORY_SCHEMA = vol.Schema(
    {
        vol.Optional("days"): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_HISTORY_DAYS)
        ),
        vol.Optional("limit", default=50): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=1000)
        ),
        vol.Optional("search"): cv.string,
    }
)
PREVIEW_SCHEMA = vol.Schema(
    {
        vol.Optional("last_alert", default=False): cv.boolean,
        vol.Optional("title"): cv.string,
        vol.Optional("message"): cv.string,
        vol.Optional("app"): cv.string,
        vol.Optional("priority"): vol.All(vol.Coerce(int), vol.Range(min=-2, max=2)),
        vol.Optional("speak", default=False): cv.boolean,
        vol.Optional("use_ai", default=True): cv.boolean,
    }
)

type AlertTTSConfigEntry = ConfigEntry[AlertTTS]


def _runtime(hass: HomeAssistant) -> AlertTTS:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data
    raise HomeAssistantError("Push Alert TTS is not set up")


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the integration's actions."""

    async def _ack(call: ServiceCall) -> None:
        await _runtime(hass).acknowledge()

    async def _speak(call: ServiceCall) -> None:
        await _runtime(hass).speak(call.data["message"])

    async def _history(call: ServiceCall) -> ServiceResponse:
        runtime = _runtime(hass)
        rows = await runtime.get_history(
            call.data.get("days"), call.data["limit"], call.data.get("search")
        )
        return {"history_days": runtime.history_days, "alerts": rows}

    async def _preview(call: ServiceCall) -> ServiceResponse:
        runtime = _runtime(hass)
        alert: dict = {}
        if call.data["last_alert"]:
            alert = await runtime.last_raw_alert() or {}
            if not alert:
                raise ServiceValidationError(
                    "No alert has been received yet",
                    translation_domain=DOMAIN,
                    translation_key="no_last_alert",
                )
        for key in ("title", "message", "app", "priority"):
            if key in call.data:
                alert[key] = call.data[key]
        if not alert:
            raise ServiceValidationError(
                "Give a title and/or message, or turn on last_alert",
                translation_domain=DOMAIN,
                translation_key="preview_nothing",
            )
        spoken = await runtime.compute_spoken([alert])
        ai = None
        if call.data["use_ai"]:
            ai = await runtime.ai_wording(
                [alert], spoken, as_int(alert.get("priority")) >= 2
            )
        text = ai["text"] if ai and ai["text"] else spoken["text"]
        if call.data["speak"]:
            runtime.entry.async_create_background_task(
                hass, runtime.speak(text), f"{DOMAIN}_preview_speak"
            )
        return {
            "spoken_text": text,
            "spoken_source": "ai" if ai and ai["text"] else "filter",
            "filter_text": spoken["text"],
            "ai_text": ai["text"] if ai else None,
            "ai_answer": ai["answer"] if ai else None,
            "ai_reason": ai["reason"] if ai else None,
            "ai_seconds": ai["seconds"] if ai else None,
            "outcome": spoken["outcome"],
            "groups": spoken["groups"],
            "alert": {
                "title": alert.get("title"),
                "message": str(alert.get("message") or "")[:500],
                "app": alert.get("app"),
                "priority": alert.get("priority"),
            },
            "spoken": bool(call.data["speak"]),
        }

    async def _add_memory(call: ServiceCall) -> ServiceResponse:
        runtime = _runtime(hass)
        added = await runtime.async_add_memory(call.data["text"])
        return {"added": added, "memory": list(runtime.memory)}

    async def _reprocess(call: ServiceCall) -> ServiceResponse:
        return await _runtime(hass).async_reprocess_ai(
            call.data["days"], call.data["limit"]
        )

    async def _get_memory(call: ServiceCall) -> ServiceResponse:
        runtime = _runtime(hass)
        return {"memory": list(runtime.memory), "path": runtime.memory_path}

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_MEMORY,
        _add_memory,
        schema=ADD_MEMORY_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_MEMORY,
        _get_memory,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REPROCESS,
        _reprocess,
        schema=REPROCESS_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(DOMAIN, SERVICE_ACK, _ack)
    hass.services.async_register(DOMAIN, SERVICE_SPEAK, _speak, schema=SPEAK_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_HISTORY,
        _history,
        schema=HISTORY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PREVIEW,
        _preview,
        schema=PREVIEW_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AlertTTSConfigEntry) -> bool:
    runtime = AlertTTS(hass, entry)
    await runtime.async_load()
    entry.runtime_data = runtime
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    runtime.async_start()
    entry.async_on_unload(runtime.async_stop)
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    return True


async def _options_updated(hass: HomeAssistant, entry: AlertTTSConfigEntry) -> None:
    # Options are read live; no reload, so the Pushover connection, pending
    # emergencies and any running announcement are not interrupted.
    entry.runtime_data.async_options_changed()


async def async_unload_entry(hass: HomeAssistant, entry: AlertTTSConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: AlertTTSConfigEntry) -> None:
    """Delete the saved alert history and AI memory with the integration.

    Earlier copies of the AI memory (ai_memory_versions) are kept on purpose.
    """
    path = hass.config.path(DOMAIN, f"history_{entry.entry_id}.jsonl")
    memory = hass.config.path(DOMAIN, f"ai_memory_{entry.entry_id}.txt")

    def _remove() -> None:
        for name in (path, f"{path}.tmp", memory, f"{memory}.tmp"):
            if os.path.exists(name):
                os.remove(name)

    await hass.async_add_executor_job(_remove)
