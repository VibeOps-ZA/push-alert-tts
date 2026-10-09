"""Error classification: only real Pushover rejections count as login problems."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.push_alert_tts import api
from custom_components.push_alert_tts.const import LOGIN_URL, MESSAGES_URL


async def test_proxy_403_is_transient(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(MESSAGES_URL, status=403, text="<html>Forbidden</html>")
    with pytest.raises(api.PushoverError) as err:
        await api.async_fetch_messages(async_get_clientsession(hass), "s", "d")
    assert not isinstance(err.value, api.SessionInvalid)


async def test_pushover_rejection_is_session_invalid(
    hass: HomeAssistant, aioclient_mock
) -> None:
    aioclient_mock.get(
        MESSAGES_URL, status=400, json={"status": 0, "errors": ["secret is invalid"]}
    )
    with pytest.raises(api.SessionInvalid):
        await api.async_fetch_messages(async_get_clientsession(hass), "s", "d")


async def test_login_outage_is_not_auth_error(
    hass: HomeAssistant, aioclient_mock
) -> None:
    aioclient_mock.post(LOGIN_URL, status=502, text="Bad gateway")
    with pytest.raises(api.PushoverError) as err:
        await api.async_login(async_get_clientsession(hass), "e", "p")
    assert not isinstance(err.value, api.AuthError)


async def test_login_rejected(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(
        LOGIN_URL, status=400, json={"status": 0, "errors": ["invalid"]}
    )
    with pytest.raises(api.AuthError):
        await api.async_login(async_get_clientsession(hass), "e", "p")
