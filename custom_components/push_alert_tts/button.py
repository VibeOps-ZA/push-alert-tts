"""Momentary buttons: acknowledge emergencies, and test the announcement."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AlertTTSConfigEntry
from .const import (
    AI_BACKFILL_DEFAULT_DAYS,
    AI_BACKFILL_MAX,
    CONF_FIXED_MESSAGE,
    DEFAULT_FIXED_MESSAGE,
    DOMAIN,
)
from .entity import AlertTTSEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlertTTSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([AcknowledgeButton(entry), TestButton(entry), ReworkButton(entry)])


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


class ReworkButton(AlertTTSEntity, ButtonEntity):
    """Re-word missed alerts with the AI (reprocess_ai for 3 days). Nothing is spoken."""

    def __init__(self, entry: AlertTTSConfigEntry) -> None:
        super().__init__(entry, "reword_missed")

    @property
    def available(self) -> bool:
        return self.runtime.ai_enabled

    async def async_press(self) -> None:
        runtime = self.runtime
        runtime.entry.async_create_background_task(
            self.hass,
            runtime.async_reprocess_ai_quietly(
                AI_BACKFILL_DEFAULT_DAYS, AI_BACKFILL_MAX
            ),
            f"{DOMAIN}_reword_button",
        )
