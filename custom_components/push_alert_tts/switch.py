"""Switches: Push Alert TTS on/off, and repeat emergencies until acknowledged."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import AlertTTSConfigEntry
from .entity import AlertTTSEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlertTTSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([EnabledSwitch(entry), RepeatSwitch(entry)])


class EnabledSwitch(AlertTTSEntity, SwitchEntity, RestoreEntity):
    """Main on/off switch. Schedule it like any other switch in HA."""

    _attr_name = None  # use the device name: "Push Alert TTS"

    def __init__(self, entry: AlertTTSConfigEntry) -> None:
        super().__init__(entry, "enabled")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self.runtime.enabled = last.state == STATE_ON

    @property
    def is_on(self) -> bool:
        return self.runtime.enabled

    @property
    def icon(self) -> str:
        return "mdi:bell-ring" if self.is_on else "mdi:bell-off"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.runtime.async_enabled_changed(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.runtime.async_enabled_changed(False)


class RepeatSwitch(AlertTTSEntity, SwitchEntity, RestoreEntity):
    """Repeat emergency-priority alerts until acknowledged."""

    def __init__(self, entry: AlertTTSConfigEntry) -> None:
        super().__init__(entry, "repeat_until_ack")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self.runtime.repeat_until_ack = last.state == STATE_ON

    @property
    def is_on(self) -> bool:
        return self.runtime.repeat_until_ack

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.runtime.repeat_until_ack = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.runtime.repeat_until_ack = False
        self.async_write_ha_state()
