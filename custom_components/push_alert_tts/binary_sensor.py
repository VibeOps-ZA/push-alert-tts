"""Pushover connection status."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AlertTTSConfigEntry
from .entity import AlertTTSEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlertTTSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ConnectedSensor(entry), AIReachableSensor(entry)])


class ConnectedSensor(AlertTTSEntity, BinarySensorEntity):
    """On while the Pushover websocket is connected."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: AlertTTSConfigEntry) -> None:
        super().__init__(entry, "connected")

    @property
    def is_on(self) -> bool:
        return self.runtime.listener.connected

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        listener = self.runtime.listener
        return {
            "status": listener.status,
            "last_error": listener.last_error,
            "drops": listener.drops,
            "last_drop": listener.last_drop,
            "last_drop_reason": listener.last_drop_reason,
            "polled_alerts": listener.polled_alerts,
            "last_poll": listener.last_poll,
            "keepalive_interval_s": listener.keepalive_interval,
            "dead_after_s": listener.keepalive_timeout,
        }


class AIReachableSensor(AlertTTSEntity, BinarySensorEntity):
    """On while the AI (LLM) server answers; unknown until first checked."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, entry: AlertTTSConfigEntry) -> None:
        super().__init__(entry, "ai_reachable")

    @property
    def available(self) -> bool:
        return self.runtime.ai_enabled

    @property
    def is_on(self) -> bool | None:
        if not self.runtime.ai_checked:
            return None
        return self.runtime.ai_down_since is None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        runtime = self.runtime
        since = runtime.ai_down_since
        return {
            "unreachable_since": since.isoformat(timespec="seconds") if since else None,
            "last_answer_from": runtime.last_server,
            "backup_set": runtime.ai_backup_configured,
            "backup_allowed_now": runtime.ai_backup_allowed,
        }
