"""Make the spoken audio before any speaker is asked to play it.

Generating first (and only then telling the speakers to play) means a slow or
unreachable voice service can't leave a speaker waiting and timing out: if the
audio can't be made in time, another voice (or the recorded clip) is used
before any speaker is touched.
"""

from __future__ import annotations

import json
import os
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError


def _tts() -> Any:
    """Home Assistant's text-to-speech component (imported when first used)."""
    from homeassistant.components import tts  # noqa: PLC0415

    return tts


async def generate(
    hass: HomeAssistant, engine: str, text: str, language: str | None
) -> tuple[str, bytes, str]:
    """Generate `text` with `engine`; return (media source id, audio, extension).

    The audio stays in Home Assistant's text-to-speech cache, so a speaker
    playing the media source id gets it at once. Raises if nothing came back.
    """
    stream = _tts().async_create_stream(hass, engine, language=language)
    stream.async_set_message(text)
    data = b"".join([chunk async for chunk in stream.async_stream_result()])
    if not data:
        raise HomeAssistantError(f"{engine} returned no audio")
    return stream.media_source_id, data, stream.extension


def clip_media_id(hass: HomeAssistant, engine: str, path: str) -> str:
    """A media source id that plays a saved audio file (no voice service used)."""
    stream = _tts().async_create_stream(hass, engine)
    stream.async_override_result(path)
    return stream.media_source_id


def save_clip(folder: str, name: str, data: bytes, extension: str, meta: dict) -> str:
    """Save the recorded clip and a note of how it was made (executor)."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{name}.{extension}")
    tmp = f"{path}.tmp"
    with open(tmp, "wb") as handle:
        handle.write(data)
    os.replace(tmp, path)
    with open(os.path.join(folder, f"{name}.json"), "w", encoding="utf-8") as handle:
        json.dump({**meta, "path": path}, handle)
    return path


def load_clip(folder: str, name: str) -> dict[str, Any] | None:
    """The saved clip's note, if the clip file is still there (executor)."""
    try:
        with open(os.path.join(folder, f"{name}.json"), encoding="utf-8") as handle:
            meta = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(meta, dict) or not os.path.exists(str(meta.get("path"))):
        return None
    return meta
