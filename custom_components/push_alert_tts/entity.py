"""Base entity for Push Alert TTS."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import CONF_DEVICE_NAME, DOMAIN, SIGNAL_UPDATE, VERSION

if TYPE_CHECKING:
    from . import AlertTTSConfigEntry


class AlertTTSEntity(Entity):
    """Common device info and update wiring."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: AlertTTSConfigEntry, key: str) -> None:
        self.runtime = entry.runtime_data
        self._entry_id = entry.entry_id
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Push Alert TTS",
            manufacturer="Unofficial Pushover Open Client",
            model=f"Pushover device: {entry.data.get(CONF_DEVICE_NAME)}",
            sw_version=VERSION,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_UPDATE}_{self._entry_id}",
                self.async_write_ha_state,
            )
        )
