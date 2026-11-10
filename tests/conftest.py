"""Shared fixtures."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_EMAIL
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.push_alert_tts import coordinator
from custom_components.push_alert_tts.const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_FALLBACK_NOTIFY,
    CONF_FIXED_MESSAGE,
    CONF_MESSAGE_MODE,
    CONF_SECRET,
    CONF_SPEAKERS,
    CONF_STORE_PASSWORD,
    CONF_TTS_ENTITY,
    CONF_USER_KEY,
    DOMAIN,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading custom_components."""
    yield


@pytest.fixture(autouse=True)
def fast_timings():
    """No start-up settle delay and no waiting for playback in tests."""
    with (
        patch("custom_components.push_alert_tts.coordinator.SPEAKER_SETTLE", 0),
        patch("custom_components.push_alert_tts.coordinator.PLAYBACK_START_TIMEOUT", 0),
        patch("custom_components.push_alert_tts.coordinator.PLAYBACK_END_GRACE", 0),
        patch("custom_components.push_alert_tts.coordinator.SHORT_PLAY_MIN", 0),
        patch("custom_components.push_alert_tts.coordinator.RETRY_PAUSE", 0),
        # Tests that need these set the option explicitly.
        patch("custom_components.push_alert_tts.coordinator.DEFAULT_WAKE_WAIT", 0),
        patch(
            "custom_components.push_alert_tts.coordinator.DEFAULT_ANNOUNCE_RETRIES", 0
        ),
    ):
        yield


def fake_media_id(engine: str, text: str, language: str | None) -> str:
    """What the fake voice returns: enough to tell which voice said what."""
    return f"test-media://{engine}|{language or ''}|{text}"


async def fake_generate(hass, engine, text, language):
    """Stand-in for audio.generate: makes no audio, always works."""
    return fake_media_id(engine, text, language), b"audio", "mp3"


async def fake_play_media(self, players, media, mark):
    """Stand-in for AlertTTS._play_media: plays through a tts.speak service.

    Most tests mock tts.speak (as the integration called it before 0.11.0) to
    see what was said where; this keeps those tests meaningful.
    """
    engine, language, text = media.removeprefix("test-media://").split("|", 2)
    data = {"media_player_entity_id": players, "message": text, "cache": True}
    if language:
        data["language"] = language
    mark("tts_call_ms")
    async with asyncio.timeout(coordinator.PLAY_CALL_TIMEOUT):
        await self.hass.services.async_call(
            "tts", "speak", data, target={"entity_id": engine}, blocking=True
        )
    mark("tts_done_ms")


@pytest.fixture(autouse=True)
def fake_voice(request):
    """No real text-to-speech in tests unless marked real_voice."""
    if request.node.get_closest_marker("real_voice"):
        yield
        return
    with (
        patch("custom_components.push_alert_tts.audio.generate", new=fake_generate),
        patch(
            "custom_components.push_alert_tts.coordinator.AlertTTS._play_media",
            new=fake_play_media,
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def fake_ping(request):
    """The AI-server check answers 'reachable' unless a test needs the real one."""
    if request.node.get_closest_marker("real_ping"):
        yield
        return
    with patch(
        "custom_components.push_alert_tts.ai_wording.ping",
        new=AsyncMock(return_value=True),
    ):
        yield


@pytest.fixture
def mock_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="me@example.com",
        data={
            CONF_EMAIL: "me@example.com",
            CONF_SECRET: "secret123",
            CONF_DEVICE_ID: "dev123",
            CONF_DEVICE_NAME: "ha-alert-tts",
            CONF_USER_KEY: "ukey",
            CONF_STORE_PASSWORD: False,
        },
        options={
            CONF_SPEAKERS: ["media_player.bedroom", "media_player.kitchen"],
            CONF_TTS_ENTITY: "tts.test",
            CONF_MESSAGE_MODE: "fixed",
            CONF_FIXED_MESSAGE: "Alert received",
            CONF_FALLBACK_NOTIFY: "notify.mobile_app_phone",
        },
    )


@pytest.fixture
def no_listener():
    """Don't open a real websocket."""
    with patch(
        "custom_components.push_alert_tts.client.PushoverListener.run",
        new=AsyncMock(return_value=None),
    ):
        yield
