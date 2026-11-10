"""Make the spoken audio before any speaker is asked to play it.

Generating first (and only then telling the speakers to play) means a slow or
unreachable voice service can't leave a speaker waiting and timing out: if the
audio can't be made in time, another voice (or the recorded clip) is used
before any speaker is touched.

Combined announcements are joined into one file with ffmpeg, with exact
pauses between the parts, so the speakers get one thing to play.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

STITCH_RATE = 24000  # Hz: plenty for speech, and what most voices make anyway


def _tts() -> Any:
    """Home Assistant's text-to-speech component (imported when first used)."""
    from homeassistant.components import tts  # noqa: PLC0415

    return tts


async def generate(
    hass: HomeAssistant,
    engine: str,
    text: str,
    language: str | None,
    options: dict[str, Any] | None = None,
) -> tuple[str, bytes, str]:
    """Generate `text` with `engine`; return (media source id, audio, extension).

    The audio stays in Home Assistant's text-to-speech cache, so a speaker
    playing the media source id gets it at once. Raises if nothing came back.
    ``options`` are the engine's own options (for example a voice name).
    """
    kwargs: dict[str, Any] = {"language": language}
    if options:
        kwargs["options"] = options
    stream = _tts().async_create_stream(hass, engine, **kwargs)
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


def ffmpeg_binary() -> str | None:
    """The ffmpeg program, if there is one (Home Assistant OS includes it)."""
    return shutil.which("ffmpeg")


def stitch_args(binary: str, inputs: list[str | float], out_path: str) -> list[str]:
    """ffmpeg arguments joining audio files and silences (seconds) into one MP3."""
    args = [binary, "-hide_banner", "-loglevel", "error", "-y"]
    for item in inputs:
        if isinstance(item, str):
            args += ["-i", item]
        else:
            args += [
                "-f",
                "lavfi",
                "-t",
                f"{float(item):.2f}",
                "-i",
                f"anullsrc=r={STITCH_RATE}:cl=mono",
            ]
    chains = "".join(
        f"[{i}:a]aresample={STITCH_RATE},"
        f"aformat=sample_fmts=s16:channel_layouts=mono[a{i}];"
        for i in range(len(inputs))
    )
    joined = "".join(f"[a{i}]" for i in range(len(inputs)))
    graph = f"{chains}{joined}concat=n={len(inputs)}:v=0:a=1[out]"
    return [
        *args,
        "-filter_complex",
        graph,
        "-map",
        "[out]",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "64k",
        out_path,
    ]


def _write_parts(
    parts: list[tuple[bytes, str] | float], folder: str
) -> tuple[str, list[str | float]]:
    """Write the audio parts to a new work folder (executor)."""
    os.makedirs(folder, exist_ok=True)
    work = tempfile.mkdtemp(prefix="join-", dir=folder)
    inputs: list[str | float] = []
    for index, part in enumerate(parts):
        if isinstance(part, float | int):
            if part > 0:
                inputs.append(float(part))
            continue
        data, extension = part
        path = os.path.join(work, f"part{index}.{extension or 'mp3'}")
        with open(path, "wb") as handle:
            handle.write(data)
        inputs.append(path)
    return work, inputs


def _finish(work: str, tmp: str, out_path: str, ok: bool) -> bool:
    """Move the joined file into place (if made) and remove the work folder."""
    made = ok and os.path.exists(tmp) and os.path.getsize(tmp) > 0
    if made:
        os.replace(tmp, out_path)
    shutil.rmtree(work, ignore_errors=True)
    return made


async def stitch(
    hass: HomeAssistant,
    parts: list[tuple[bytes, str] | float],
    out_path: str,
    timeout: float,
) -> str:
    """Join audio parts ((data, extension)) and pauses (seconds) into one MP3.

    Returns ``out_path``. Raises if ffmpeg is missing, fails or is too slow.
    """
    binary = await hass.async_add_executor_job(ffmpeg_binary)
    if not binary:
        raise HomeAssistantError("ffmpeg is not installed")
    if all(isinstance(p, float | int) for p in parts):
        raise HomeAssistantError("nothing to join")
    work, inputs = await hass.async_add_executor_job(
        _write_parts, parts, os.path.dirname(out_path)
    )
    tmp = os.path.join(work, "joined.mp3")
    ok = False
    err = b""
    try:
        proc = await asyncio.create_subprocess_exec(
            *stitch_args(binary, inputs, tmp),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            async with asyncio.timeout(timeout):
                _out, err = await proc.communicate()
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise
        ok = proc.returncode == 0
    finally:
        made = await hass.async_add_executor_job(_finish, work, tmp, out_path, ok)
    if not made:
        raise HomeAssistantError(
            f"ffmpeg could not join the audio: {err.decode(errors='replace')[:300]}"
        )
    return out_path
