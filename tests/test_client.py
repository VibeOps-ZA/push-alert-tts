"""Login recovery in the listener."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant

from custom_components.push_alert_tts import api
from custom_components.push_alert_tts.client import (
    DeviceStopped,
    LoginRequired,
    PushoverListener,
)
from custom_components.push_alert_tts.const import CONF_SECRET


def _listener(hass, entry):
    entry.add_to_hass(hass)
    return PushoverListener(hass, entry, AsyncMock(), MagicMock())


async def test_no_saved_password_requires_login(
    hass: HomeAssistant, mock_entry
) -> None:
    listener = _listener(hass, mock_entry)
    with pytest.raises(LoginRequired):
        await listener._handle_session_error("x")


async def test_saved_password_relogs(hass: HomeAssistant, mock_entry) -> None:
    mock_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_entry, data={**mock_entry.data, CONF_PASSWORD: "pw"}
    )
    listener = PushoverListener(hass, mock_entry, AsyncMock(), MagicMock())
    with patch(
        "custom_components.push_alert_tts.client.api.async_login",
        new=AsyncMock(return_value={"secret": "fresh"}),
    ):
        await listener._handle_session_error("x")
    assert mock_entry.data[CONF_SECRET] == "fresh"
    # A second failure soon after means the problem isn't the session.
    with pytest.raises(DeviceStopped):
        await listener._handle_session_error("x")


async def test_saved_password_with_2fa(hass: HomeAssistant, mock_entry) -> None:
    mock_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_entry, data={**mock_entry.data, CONF_PASSWORD: "pw"}
    )
    listener = PushoverListener(hass, mock_entry, AsyncMock(), MagicMock())
    with (
        patch(
            "custom_components.push_alert_tts.client.api.async_login",
            new=AsyncMock(side_effect=api.TwoFactorRequired("2fa", 412)),
        ),
        pytest.raises(LoginRequired),
    ):
        await listener._handle_session_error("x")


async def test_sync_deletes_after_callback(hass: HomeAssistant, mock_entry) -> None:
    mock_entry.add_to_hass(hass)
    order = []
    on_alerts = AsyncMock(side_effect=lambda *a: order.append("callback"))
    listener = PushoverListener(hass, mock_entry, on_alerts, MagicMock())
    msgs = [{"id_str": "7", "date": 0}, {"id_str": "6", "date": 0}]
    with (
        patch(
            "custom_components.push_alert_tts.client.api.async_fetch_messages",
            new=AsyncMock(return_value=msgs),
        ),
        patch(
            "custom_components.push_alert_tts.client.api.async_delete_through",
            new=AsyncMock(side_effect=lambda *a: order.append(("delete", a[3]))),
        ),
    ):
        await listener.sync(startup=True)
    assert order == ["callback", ("delete", 7)]
    assert on_alerts.await_args.args[1] is True  # queued


async def test_network_error_during_relogin_is_retried(
    hass: HomeAssistant, mock_entry
) -> None:
    mock_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_entry, data={**mock_entry.data, CONF_PASSWORD: "pw"}
    )
    listener = PushoverListener(hass, mock_entry, AsyncMock(), MagicMock())
    with (
        patch(
            "custom_components.push_alert_tts.client.api.async_login",
            new=AsyncMock(side_effect=api.PushoverError("dns", None)),
        ),
        pytest.raises(api.PushoverError),
    ):
        await listener._handle_session_error("x")
    # Not counted as a re-login, so the next attempt really logs in.
    with patch(
        "custom_components.push_alert_tts.client.api.async_login",
        new=AsyncMock(return_value={"secret": "fresh"}),
    ):
        await listener._handle_session_error("x")
    assert mock_entry.data[CONF_SECRET] == "fresh"
