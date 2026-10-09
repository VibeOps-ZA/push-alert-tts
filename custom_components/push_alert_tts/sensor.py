"""Last alert received."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AlertTTSConfigEntry
from .entity import AlertTTSEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlertTTSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([LastAlertSensor(entry)])


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
