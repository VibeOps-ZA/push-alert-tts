"""Login recovery in the listener."""

from __future__ import annotations

import asyncio
import contextlib
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant

from custom_components.push_alert_tts import api
from custom_components.push_alert_tts.client import (
    DeviceStopped,
    LoginRequired,
    PushoverListener,
    _Reconnect,
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


async def test_keepalive_timeout_learns_from_gaps(hass: HomeAssistant, mock_entry) -> None:
    listener = _listener(hass, mock_entry)
    assert listener.keepalive_timeout == 120  # unknown yet: the full wait
    assert listener.keepalive_interval is None
    listener._gaps.extend([30.0, 29.5, 31.0])
    assert listener.keepalive_timeout == 77.5  # 2.5 x the longest gap
    assert listener.keepalive_interval == 31.0
    listener._gaps.clear()
    listener._gaps.extend([5.0, 5.0, 5.0])
    assert listener.keepalive_timeout == 45  # never sooner than the minimum
    listener._gaps.clear()
    listener._gaps.extend([30.0, 30.0, 90.0])
    assert listener.keepalive_timeout == 120  # never longer than the maximum


async def _run_one_drop(listener, error):
    """Run the loop for one connection that works, then fails with `error`."""
    delays = []

    async def listen_once():
        if delays:
            raise asyncio.CancelledError
        listener._set_status("connected")
        raise error

    async def fake_sleep(delay):
        delays.append(delay)

    with (
        patch.object(listener, "_listen_once", side_effect=listen_once),
        patch("custom_components.push_alert_tts.client.asyncio.sleep", fake_sleep),
        pytest.raises(asyncio.CancelledError),
    ):
        await listener._run()
    return delays


async def test_silent_connection_retries_sooner(
    hass: HomeAssistant, mock_entry
) -> None:
    listener = _listener(hass, mock_entry)
    delays = await _run_one_drop(listener, TimeoutError())
    assert delays == [5]
    assert listener.drops == 1
    assert listener.last_drop is not None
    assert "keep-alive" in listener.last_drop_reason


async def test_server_drop_waits_before_reconnecting(
    hass: HomeAssistant, mock_entry
) -> None:
    listener = _listener(hass, mock_entry)
    delays = await _run_one_drop(listener, _Reconnect("reload requested by Pushover"))
    assert delays == [15]
    assert listener.drops == 1
    assert listener.last_drop_reason == "reload requested by Pushover"


async def test_polls_for_alerts_while_disconnected(
    hass: HomeAssistant, mock_entry
) -> None:
    mock_entry.add_to_hass(hass)
    on_alerts = AsyncMock()
    listener = PushoverListener(hass, mock_entry, on_alerts, MagicMock())
    listener.status = "reconnecting"
    fetch = AsyncMock(return_value=[{"id_str": "9", "date": int(time.time())}])
    with (
        patch("custom_components.push_alert_tts.client.POLL_INTERVAL", 0.01),
        patch("custom_components.push_alert_tts.client.api.async_fetch_messages", fetch),
        patch(
            "custom_components.push_alert_tts.client.api.async_delete_through",
            new=AsyncMock(),
        ),
    ):
        task = asyncio.create_task(listener._poll_while_down())
        await asyncio.sleep(0.05)
        listener.status = "connected"  # back online: polling stops
        calls = fetch.await_count
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    assert calls >= 1
    assert fetch.await_count == calls
    assert listener.polled_alerts == 1  # the same alert isn't handed over twice
    on_alerts.assert_awaited_once()
    assert on_alerts.await_args.args[1] is False  # fresh, not queued
    assert listener.last_poll is not None


async def test_polling_never_logs_in_again(hass: HomeAssistant, mock_entry) -> None:
    mock_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_entry, data={**mock_entry.data, CONF_PASSWORD: "pw"}
    )
    listener = PushoverListener(hass, mock_entry, AsyncMock(), MagicMock())
    login = AsyncMock(return_value={"secret": "fresh"})
    with (
        patch(
            "custom_components.push_alert_tts.client.api.async_fetch_messages",
            new=AsyncMock(side_effect=api.SessionInvalid("no", 401)),
        ),
        patch("custom_components.push_alert_tts.client.api.async_login", login),
        pytest.raises(api.SessionInvalid),
    ):
        await listener.sync(startup=False, relogin=False)
    login.assert_not_awaited()
