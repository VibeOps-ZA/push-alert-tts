"""Momentary buttons: acknowledge emergencies, and test the announcement."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AlertTTSConfigEntry
from .const import CONF_FIXED_MESSAGE, DEFAULT_FIXED_MESSAGE
from .entity import AlertTTSEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlertTTSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([AcknowledgeButton(entry), TestButton(entry)])


class AcknowledgeButton(AlertTTSEntity, ButtonEntity):
    """Acknowledge pending emergency alerts on Pushover and stop repeats.

    Acknowledging an emergency-priority receipt stops Pushover re-alerting on
    every device on the account (phone, computer and Home Assistant).
    """

    def __init__(self, entry: AlertTTSConfigEntry) -> None:
        super().__init__(entry, "acknowledge")

    async def async_press(self) -> None:
        await self.runtime.acknowledge()


class TestButton(AlertTTSEntity, ButtonEntity):
    """Speak the normal announcement on the selected speakers now."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: AlertTTSConfigEntry) -> None:
        super().__init__(entry, "test")

    async def async_press(self) -> None:
        await self.runtime.speak(
            self.runtime.options.get(CONF_FIXED_MESSAGE) or DEFAULT_FIXED_MESSAGE
        )
