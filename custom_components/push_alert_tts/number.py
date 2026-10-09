"""Announcement volume."""

from __future__ import annotations

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AlertTTSConfigEntry
from .const import DEFAULT_VOLUME
from .entity import AlertTTSEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlertTTSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([VolumeNumber(entry)])


class VolumeNumber(AlertTTSEntity, RestoreNumber):
    """Volume the speakers are set to while announcing (restored afterwards)."""

    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 5
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: AlertTTSConfigEntry) -> None:
        super().__init__(entry, "volume")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self.runtime.volume = last.native_value
        elif not self.runtime.volume:
            self.runtime.volume = DEFAULT_VOLUME

    @property
    def native_value(self) -> float:
        return self.runtime.volume

    async def async_set_native_value(self, value: float) -> None:
        self.runtime.volume = value
        self.async_write_ha_state()
