"""Push Alert TTS - speak Pushover alerts on Home Assistant speakers.

An unofficial Pushover Open Client. Home Assistant registers as its own
Pushover device, so phones and computers keep receiving alerts as normal.
Not made, endorsed or supported by Pushover, LLC.
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import AlertTTS

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_ACK = "acknowledge"
SERVICE_SPEAK = "speak"
SPEAK_SCHEMA = vol.Schema({vol.Required("message"): cv.string})

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

    hass.services.async_register(DOMAIN, SERVICE_ACK, _ack)
    hass.services.async_register(DOMAIN, SERVICE_SPEAK, _speak, schema=SPEAK_SCHEMA)
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
