"""Last alert received, and the AI review list."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import AlertTTSConfigEntry
from .const import AI_REVIEW_DAYS
from .entity import AlertTTSEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlertTTSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([LastAlertSensor(entry), AIReviewSensor(entry)])


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
