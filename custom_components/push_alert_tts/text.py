"""AI correction box: type a plain-language correction and it is remembered."""

from __future__ import annotations

from typing import Any

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AlertTTSConfigEntry
from .entity import AlertTTSEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlertTTSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([AICorrectionText(entry)])


class AICorrectionText(AlertTTSEntity, TextEntity):
    """Whatever is typed here is added to the AI memory, then the box clears.

    The current memory is shown in the ``memory`` attribute.
    """

    _attr_mode = TextMode.TEXT
    _attr_native_max = 255
    _attr_native_value = ""

    def __init__(self, entry: AlertTTSConfigEntry) -> None:
        super().__init__(entry, "ai_correction")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "memory": list(self.runtime.memory),
            "last_added": self._last_added,
        }

    _last_added: str | None = None

    async def async_set_value(self, value: str) -> None:
        value = (value or "").strip()
        if value:
            await self.runtime.async_add_memory(value)
            self._last_added = value
        self._attr_native_value = ""
        self.async_write_ha_state()
