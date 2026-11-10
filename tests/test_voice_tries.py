"""Main voice tries before the backup; backup voice name; the voice-with-backup entity."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.push_alert_tts import audio
from custom_components.push_alert_tts.const import (
    CONF_TTS_BACKUP,
    CONF_TTS_BACKUP_VOICE,
    CONF_TTS_RETRIES,
)
from custom_components.push_alert_tts.coordinator import _Marks, _Voices

C = "custom_components.push_alert_tts.coordinator"


@pytest.fixture(autouse=True)
def quick():
    with (
        patch(f"{C}.GENERATE_TIMEOUT", 0.2),
        patch(f"{C}.BACKUP_GENERATE_TIMEOUT", 0.5),
        patch(f"{C}.BACKUP_HEAD_START", 0.05),
        patch(f"{C}.VOICE_RETRY_PAUSE", 0),
    ):
        yield


def _voice(fail_main: int = 0, backup_ok: bool = True):
    """Main voice fails its first `fail_main` tries."""
    made: list[tuple[str, dict | None]] = []

    async def generate(hass, engine, text, language, options=None):
        made.append((engine, options))
        if engine == "tts.test":
            if sum(1 for e, _ in made if e == "tts.test") <= fail_main:
                raise RuntimeError("internet down")
        elif not backup_ok:
            raise RuntimeError("backup down")
        return f"m://{engine}", f"{engine}:{text}".encode(), "mp3"

    return generate, made


async def _setup(hass, entry, **options):
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry.runtime_data


async def test_main_voice_retried_before_backup_is_used(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    runtime = await _setup(hass, mock_entry, **{CONF_TTS_BACKUP: "tts.local"})
    generate, made = _voice(fail_main=2)
    timings: dict = {}
    with patch.object(audio, "generate", new=generate):
        voices = _Voices(runtime, "hello", "tts.test", _Marks(timings, 0.0))
        voices.start()
        media, voice = await voices.first()
        voices.stop()
    assert (media, voice) == ("m://tts.test", "main")  # third try worked
    assert [e for e, _ in made].count("tts.test") == 3
    assert "tts.local" in [e for e, _ in made]  # made in case, but not used
    assert timings["main_voice_tries"] == 3


async def test_backup_used_after_all_tries(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    runtime = await _setup(
        hass,
        mock_entry,
        **{
            CONF_TTS_BACKUP: "tts.local",
            CONF_TTS_RETRIES: 3,
            CONF_TTS_BACKUP_VOICE: "en_GB-cori-high",
        },
    )
    generate, made = _voice(fail_main=99)
    with patch.object(audio, "generate", new=generate):
        voices = _Voices(runtime, "hello", "tts.test", _Marks(None, None))
        voices.start()
        media, voice = await voices.first()
        voices.stop()
    assert voice == "backup"
    assert [e for e, _ in made].count("tts.test") == 4  # 1 + 3 retries
    assert ("tts.local", {"voice": "en_GB-cori-high"}) in made
    assert voices.data["backup"] == (b"tts.local:hello", "mp3")


async def test_slow_main_starts_backup_early_but_prefers_main(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    runtime = await _setup(hass, mock_entry, **{CONF_TTS_BACKUP: "tts.local"})
    made: list[str] = []

    async def generate(hass, engine, text, language, options=None):
        made.append(engine)
        if engine == "tts.test":
            await asyncio.sleep(0.12)  # slow, but within its time
        return f"m://{engine}", b"x", "mp3"

    with patch.object(audio, "generate", new=generate):
        voices = _Voices(runtime, "hello", "tts.test", _Marks(None, None))
        voices.start()
        _media, voice = await voices.first()
        voices.stop()
    assert voice == "main"
    assert "tts.local" in made  # ready in case


async def test_voice_audio_falls_back_and_never_calls_itself(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    runtime = await _setup(hass, mock_entry, **{CONF_TTS_BACKUP: "tts.local"})
    generate, made = _voice(fail_main=99)
    with patch.object(audio, "generate", new=generate):
        data, ext = await runtime.async_voice_audio("hi", "en", "tts.self")
        assert (data, ext) == (b"tts.local:hi", "mp3")
        # The entity chosen as its own main voice is skipped.
        made.clear()
        data, _ = await runtime.async_voice_audio("hi", "en", "tts.test")
        assert "tts.test" not in [e for e, _ in made]
        assert data == b"tts.local:hi"


async def test_voice_audio_raises_when_nothing_works(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    runtime = await _setup(hass, mock_entry, **{CONF_TTS_BACKUP: "tts.local"})
    generate, _made = _voice(fail_main=99, backup_ok=False)
    with (
        patch.object(audio, "generate", new=generate),
        pytest.raises(HomeAssistantError),
    ):
        await runtime.async_voice_audio("hi", "en", None)


@pytest.mark.tts_platform
async def test_voice_entity_is_created(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    await _setup(hass, mock_entry)
    states = [s.entity_id for s in hass.states.async_all("tts")]
    assert any(e.startswith("tts.push_alert_tts") for e in states), states
