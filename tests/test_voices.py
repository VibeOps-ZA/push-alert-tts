"""Audio made before playing; backup voice; the recorded phrase; never silent."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.push_alert_tts import audio
from custom_components.push_alert_tts.const import (
    CONF_ANNOUNCE_RETRIES,
    CONF_TTS_BACKUP,
)

from .conftest import fake_media_id
from .test_playback import CUT, GOOD, GROUP, MEMBERS, TEXT, _setup, _states, _tts

C = "custom_components.push_alert_tts.coordinator"
A = "custom_components.push_alert_tts.audio"


@pytest.fixture(autouse=True)
def quick_voices():
    with (
        patch(f"{C}.GENERATE_TIMEOUT", 0.3),
        patch(f"{C}.BACKUP_GENERATE_TIMEOUT", 0.5),
        patch(f"{C}.BACKUP_HEAD_START", 0.1),
        patch(f"{C}.VOICE_RETRY_PAUSE", 0),
        patch(f"{C}.GROUP_START_TIMEOUT", 1),
        patch(f"{C}.PLAYBACK_END_GRACE", 0.6),
        patch(f"{C}.SHORT_PLAY_MIN", 1.0),
        patch(f"{C}.SPEECH_CHARS_PER_SECOND", 1000),
    ):
        yield


def _voices(slow=(), broken=()):
    """A stand-in audio.generate where some voices hang or fail."""
    made: list[str] = []

    async def generate(hass, engine, text, language, options=None):
        made.append(engine)
        if engine in slow:
            await asyncio.sleep(5)
        if engine in broken:
            raise RuntimeError("voice service down")
        return fake_media_id(engine, text, language), b"audio", "mp3"

    return generate, made


class _FakeTTS:
    """Stands in for homeassistant.components.tts (its audio libraries aren't
    installed for tests)."""

    def __init__(self, stream):
        self.stream = stream

    def async_create_stream(self, hass, engine, language=None):
        return self.stream


def _engines(calls: list[ServiceCall]) -> list[str]:
    return [c.data["entity_id"] for c in calls]


async def test_slow_main_voice_uses_backup_and_plays_once(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    """Tonight's failure: the internet voice hangs. Speak once with the backup."""
    _states(hass)
    calls = _tts(hass, [GOOD])
    async_mock_service(hass, "media_player", "volume_set")
    notify = async_mock_service(hass, "notify", "mobile_app_phone")
    generate, _made = _voices(slow={"tts.test"})
    runtime = await _setup(
        hass, mock_entry, **{CONF_TTS_BACKUP: "tts.local", CONF_ANNOUNCE_RETRIES: 5}
    )
    timings: dict = {}
    with patch(f"{A}.generate", new=generate):
        await runtime.speak(TEXT, timings=timings, t0=time.monotonic())
    assert _engines(calls) == ["tts.local"]  # one play: one wake-up sound
    assert timings["voice"] == "backup"
    assert timings["outcome"] == "ok"
    assert timings["attempts"] == 1
    assert "audio_ready_ms" in timings
    assert not notify


async def test_broken_main_voice_uses_backup(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _states(hass)
    calls = _tts(hass, [GOOD])
    async_mock_service(hass, "media_player", "volume_set")
    generate, _made = _voices(broken={"tts.test"})
    runtime = await _setup(hass, mock_entry, **{CONF_TTS_BACKUP: "tts.local"})
    timings: dict = {}
    with patch(f"{A}.generate", new=generate):
        await runtime.speak(TEXT, timings=timings, t0=time.monotonic())
    assert _engines(calls) == ["tts.local"]
    assert timings["voice_failed"] == ["main"]


async def test_fast_main_voice_never_starts_backup(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _states(hass)
    calls = _tts(hass, [GOOD])
    async_mock_service(hass, "media_player", "volume_set")
    generate, made = _voices()
    runtime = await _setup(hass, mock_entry, **{CONF_TTS_BACKUP: "tts.local"})
    with patch(f"{A}.generate", new=generate):
        await runtime.speak(TEXT)
    assert _engines(calls) == ["tts.test"]
    assert "tts.local" not in made[-1:]  # the backup was never asked


async def test_no_voice_plays_recorded_phrase_and_sends_details(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _states(hass)
    calls = _tts(hass, [GOOD])
    async_mock_service(hass, "media_player", "volume_set")
    notify = async_mock_service(hass, "notify", "mobile_app_phone")
    generate, _made = _voices(broken={"tts.test", "tts.local"})
    runtime = await _setup(hass, mock_entry, **{CONF_TTS_BACKUP: "tts.local"})
    runtime.clip = {"engine": "tts.test", "text": "Alert received", "path": "/x.mp3"}
    timings: dict = {}
    with (
        patch(f"{A}.generate", new=generate),
        patch(
            f"{A}.clip_media_id",
            return_value=fake_media_id("tts.clip", "Alert received", None),
        ),
    ):
        await runtime.speak(TEXT, timings=timings, t0=time.monotonic())
    assert [c.data["message"] for c in calls] == ["Alert received"]
    assert timings["voice"] == "clip"
    assert len(notify) == 1
    assert TEXT in notify[0].data["message"]
    assert "recorded phrase was played" in notify[0].data["message"]


async def test_nothing_to_play_warns_without_waking_group(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _states(hass)
    calls = _tts(hass, [GOOD])
    async_mock_service(hass, "media_player", "volume_set")
    notify = async_mock_service(hass, "notify", "mobile_app_phone")
    generate, _made = _voices(broken={"tts.test"})
    runtime = await _setup(hass, mock_entry)
    timings: dict = {}
    with patch(f"{A}.generate", new=generate):
        await runtime.speak(TEXT, timings=timings, t0=time.monotonic())
    assert not calls  # nothing to play: speakers aren't asked to play
    assert timings["outcome"] == "no_audio"
    assert "nothing was spoken" in notify[0].data["message"]


async def test_retries_switch_route_only_when_the_group_fails(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    """Group fails -> each speaker; cut short -> same route again."""
    _states(hass)
    calls: list[ServiceCall] = []

    async def speak(call: ServiceCall) -> None:
        calls.append(call)
        players = call.data["media_player_entity_id"]
        if players == [GROUP] and len(calls) == 1:
            raise RuntimeError("group gone")
        if players == MEMBERS and len(calls) == 2:
            for delay, state in CUT:  # starts, then stops at once
                hass.loop.call_later(
                    delay,
                    lambda st=state: hass.states.async_set(
                        "media_player.bedroom", st, {"media_content_id": "x2"}
                    ),
                )
            return
        hass.states.async_set(
            "media_player.bedroom", "playing", {"media_content_id": f"x{len(calls)}"}
        )
        hass.loop.call_later(
            1.5, lambda: hass.states.async_set("media_player.bedroom", "idle", {})
        )

    hass.services.async_register("tts", "speak", speak)
    async_mock_service(hass, "media_player", "volume_set")
    with patch(f"{C}.PLAYBACK_START_TIMEOUT", 1):
        runtime = await _setup(hass, mock_entry, **{CONF_ANNOUNCE_RETRIES: 5})
        timings: dict = {}
        await runtime.speak(TEXT, timings=timings, t0=time.monotonic())
    targets = [c.data["media_player_entity_id"] for c in calls]
    assert targets == [[GROUP], MEMBERS, MEMBERS]
    assert timings["outcome"] == "ok"
    assert timings["attempts"] == 3


async def test_five_retries_then_one_warning(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    _states(hass)
    calls = _tts(hass, [CUT])
    async_mock_service(hass, "media_player", "volume_set")
    notify = async_mock_service(hass, "notify", "mobile_app_phone")
    runtime = await _setup(hass, mock_entry, **{CONF_ANNOUNCE_RETRIES: 5})
    timings: dict = {}
    await runtime.speak(TEXT, timings=timings, t0=time.monotonic())
    assert len(calls) == 6
    assert timings["attempts"] == 6
    assert len(notify) == 1


async def test_recorded_phrase_is_made_once_and_remade_on_change(
    hass: HomeAssistant, mock_entry, no_listener, tmp_path
) -> None:
    generate, made = _voices(broken={"tts.test"})
    runtime = await _setup(hass, mock_entry, **{CONF_TTS_BACKUP: "tts.local"})
    runtime.clip_folder = str(tmp_path)
    runtime.clip = None
    with patch(f"{A}.generate", new=generate):
        made.clear()
        await runtime.async_refresh_clip()
        assert runtime.clip["engine"] == "tts.local"  # the main voice failed
        assert runtime.clip["text"] == "Alert received"
        assert (tmp_path / f"{runtime.clip_name}.mp3").read_bytes() == b"audio"
        made.clear()
        await runtime.async_refresh_clip()
        assert made == []  # unchanged: not made again
        hass.config_entries.async_update_entry(
            mock_entry, options={**mock_entry.options, "fixed_message": "Check now"}
        )
        await hass.async_block_till_done()
        made.clear()
        await runtime.async_refresh_clip()
        assert runtime.clip["text"] == "Check now"
    loaded = await hass.async_add_executor_job(
        audio.load_clip, str(tmp_path), runtime.clip_name
    )
    assert loaded["text"] == "Check now"


async def test_failed_recording_keeps_the_old_one(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    generate, _made = _voices(broken={"tts.test"})
    runtime = await _setup(hass, mock_entry)
    old = {"engine": "tts.test", "text": "Old phrase", "path": "/old.mp3"}
    runtime.clip = dict(old)
    with patch(f"{A}.generate", new=generate):
        await runtime.async_refresh_clip()
    assert runtime.clip == old


@pytest.mark.real_voice
async def test_audio_is_made_before_the_speaker_is_asked(
    hass: HomeAssistant, mock_entry, no_listener
) -> None:
    """The real path: generate the whole audio, then media_player.play_media."""
    order: list[str] = []

    class Stream:
        media_source_id = "media-source://tts/-stream-/abc"
        extension = "mp3"

        def async_set_message(self, message):
            order.append(f"message:{message}")

        async def async_stream_result(self):
            order.append("generated")
            yield b"audio"

    _states(hass)
    async_mock_service(hass, "media_player", "volume_set")

    async def play_media(call: ServiceCall) -> None:
        order.append(f"play:{call.data['media_content_id']}")
        hass.states.async_set(GROUP, "playing", {"media_content_id": "abc"})
        hass.loop.call_later(1.5, lambda: hass.states.async_set(GROUP, "idle", {}))

    hass.services.async_register("media_player", "play_media", play_media)
    with patch(f"{A}._tts", return_value=_FakeTTS(Stream())):
        runtime = await _setup(hass, mock_entry)
        timings: dict = {}
        await runtime.speak(TEXT, timings=timings, t0=time.monotonic())
    plays = [o for o in order if o.startswith("play:")]
    assert plays == ["play:media-source://tts/-stream-/abc"]
    assert order.index("generated") < order.index(plays[0])
    assert timings["outcome"] == "ok"


@pytest.mark.real_voice
async def test_generate_rejects_empty_audio(hass: HomeAssistant) -> None:
    class Empty:
        media_source_id = "x"
        extension = "mp3"

        def async_set_message(self, message):
            pass

        async def async_stream_result(self):
            if False:
                yield b""

    with (
        patch(f"{A}._tts", return_value=_FakeTTS(Empty())),
        pytest.raises(Exception, match="no audio"),
    ):
        await audio.generate(hass, "tts.x", "hello", None)
