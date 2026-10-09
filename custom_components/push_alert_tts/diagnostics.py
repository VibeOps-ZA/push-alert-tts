"""Diagnostics download (secrets redacted)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from . import AlertTTSConfigEntry
from .const import CONF_DEVICE_ID, CONF_SECRET, CONF_USER_KEY

TO_REDACT = {CONF_EMAIL, CONF_PASSWORD, CONF_SECRET, CONF_DEVICE_ID, CONF_USER_KEY}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AlertTTSConfigEntry
) -> dict[str, Any]:
    runtime = entry.runtime_data
    return {
        "data": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "status": runtime.listener.status,
        "last_error": runtime.listener.last_error,
        "stop_reason": runtime.listener.stop_reason,
        "enabled": runtime.enabled,
        "repeat_until_ack": runtime.repeat_until_ack,
        "volume": runtime.volume,
        "pending_emergencies": len(runtime.pending_receipts),
        "last_alert": runtime.last_alert,
        "last_spoken": runtime.last_spoken,
    }
