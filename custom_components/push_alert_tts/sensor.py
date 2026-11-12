"""Last alert received, and the AI review list."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import AlertTTSConfigEntry
from .const import (
    AI_BACKUP,
    AI_EMERGENCY,
    AI_MAIN,
    AI_REVIEW_DAYS,
    AI_SOURCE_TEMPLATE,
    AI_SOURCES,
)
from .entity import AlertTTSEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlertTTSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        [LastAlertSensor(entry), AIReviewSensor(entry), AIWordingSourceSensor(entry)]
    )


class LastAlertSensor(AlertTTSEntity, SensorEntity):
    """Time of the last alert; details in the attributes."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, entry: AlertTTSConfigEntry) -> None:
        super().__init__(entry, "last_alert")

    @property
    def native_value(self) -> datetime | None:
        return self.runtime.last_alert_time

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = dict(self.runtime.last_alert or {})
        attrs["pending_emergencies"] = len(self.runtime.pending_receipts)
        return attrs


class AIReviewSensor(AlertTTSEntity, SensorEntity):
    """Alerts the AI worded recently: the alert as received and what was spoken.

    State: how many. The list is in the ``alerts`` attribute (newest first),
    which is not saved in the recorder database (it can be large).
    """

    _attr_native_unit_of_measurement = "alerts"
    _unrecorded_attributes = frozenset({"alerts"})

    def __init__(self, entry: AlertTTSConfigEntry) -> None:
        super().__init__(entry, "ai_review")

    def _rows(self) -> list[dict[str, Any]]:
        cutoff = dt_util.utcnow() - timedelta(days=AI_REVIEW_DAYS)
        rows = []
        for row in reversed(self.runtime.review):
            when = dt_util.parse_datetime(str(row.get("received") or ""))
            if when is None or when >= cutoff:
                rows.append(row)
        return rows

    @property
    def native_value(self) -> int:
        return len(self._rows())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "days": AI_REVIEW_DAYS,
            "ai_enabled": self.runtime.ai_enabled,
            "last_ai_attempt": self.runtime.last_ai,
            "alerts": self._rows(),
        }


class AIWordingSourceSensor(AlertTTSEntity, SensorEntity):
    """Who worded the last alert: the main, backup or emergency AI server, or
    nobody (template = the normal text). Unknown until the first alert."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = AI_SOURCES

    def __init__(self, entry: AlertTTSConfigEntry) -> None:
        super().__init__(entry, "ai_wording_source")

    @property
    def available(self) -> bool:
        return self.runtime.ai_enabled

    @property
    def native_value(self) -> str | None:
        last = self.runtime.last_ai
        if not last:
            return None
        if last.get("text") and last.get("server") in AI_SOURCES:
            return str(last["server"])
        return AI_SOURCE_TEMPLATE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        runtime = self.runtime
        last = runtime.last_ai or {}
        none_since = runtime.ai_none_since
        up = runtime.ai_server_up
        return {
            "last_attempt": last.get("time"),
            "reason": last.get("reason"),
            "seconds": last.get("seconds"),
            "main_reachable": up.get(AI_MAIN),
            "backup_reachable": up.get(AI_BACKUP)
            if runtime.ai_backup_configured
            else None,
            "emergency_reachable": up.get(AI_EMERGENCY)
            if runtime.ai_emergency_configured
            else None,
            "any_ai_usable": runtime.ai_usable,
            "no_ai_since": none_since.isoformat(timespec="seconds")
            if none_since
            else None,
            "addresses_in_use": dict(runtime.ai_url_in_use),
        }
