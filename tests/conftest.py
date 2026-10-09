"""Shared fixtures."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_EMAIL
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
