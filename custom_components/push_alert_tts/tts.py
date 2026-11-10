"""A text-to-speech voice with a backup: the main voice, else the backup voice.

Uses the voices chosen in Push Alert TTS's options, with the same tries and
time limits as the announcements, so any automation can speak with a voice
that keeps working when the internet voice doesn't.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.tts import TextToSpeechEntity, TtsAudioType
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AlertTTSConfigEntry
from .const import CONF_TTS_ENTITY
from .entity import AlertTTSEntity

FALLBACK_LANGUAGE = "en"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlertTTSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([AlertVoice(entry)])


class AlertVoice(AlertTTSEntity, TextToSpeechEntity):
    """Speaks with the main voice; falls back to the backup voice."""

    def __init__(self, entry: AlertTTSConfigEntry) -> None:
        super().__init__(entry, "voice")

    def _main(self) -> Any:
        """The main voice's engine, if it is loaded (for its languages)."""
        engine = self.runtime.options.get(CONF_TTS_ENTITY)
        if not engine or engine == self.entity_id or self.hass is None:
            return None
        try:
            from homeassistant.components.tts import (  # noqa: PLC0415
                get_engine_instance,
            )

            return get_engine_instance(self.hass, engine)
        except Exception:  # noqa: BLE001 - not loaded yet
            return None

    @property
    def default_language(self) -> str:
        main = self._main()
        language = getattr(main, "default_language", None) if main else None
        if language:
            return language
        if self.hass is not None and self.hass.config.language:
            return self.hass.config.language
        return FALLBACK_LANGUAGE

    @property
    def supported_languages(self) -> list[str]:
        main = self._main()
        languages = list(getattr(main, "supported_languages", None) or [])
        default = self.default_language
        if default not in languages:
            languages.append(default)
        return languages

    async def async_get_tts_audio(
        self, message: str, language: str, options: dict[str, Any]
    ) -> TtsAudioType:
        data, extension = await self.runtime.async_voice_audio(
            message, language, self.entity_id
        )
        return extension, data
