"""Config and options flows."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.push_alert_tts import api
from custom_components.push_alert_tts.const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_SECRET,
    CONF_STORE_PASSWORD,
    DOMAIN,
)

API = "custom_components.push_alert_tts.config_flow.api"
USER = {
    CONF_EMAIL: "me@example.com",
    CONF_PASSWORD: "pw",
    CONF_DEVICE_NAME: "ha-alert-tts",
}


def _patches(login=None):
    return (
        patch(
            f"{API}.async_login",
            new=login or AsyncMock(return_value={"secret": "s1", "id": "u1"}),
        ),
        patch(f"{API}.async_register_device", new=AsyncMock(return_value="d1")),
        patch(
            f"{API}.async_fetch_messages", new=AsyncMock(return_value=[{"id_str": "5"}])
        ),
        patch(f"{API}.async_delete_through", new=AsyncMock()),
        patch(
            "custom_components.push_alert_tts.async_setup_entry",
            new=AsyncMock(return_value=True),
        ),
    )


async def _start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_user_flow_without_saved_password(hass: HomeAssistant) -> None:
    p = _patches()
    with p[0], p[1], p[2], p[3] as delete, p[4]:
        result = await _start(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SECRET] == "s1"
    assert result["data"][CONF_DEVICE_ID] == "d1"
    assert CONF_PASSWORD not in result["data"]
    delete.assert_awaited_once()  # welcome message cleared


async def test_user_flow_saved_password(hass: HomeAssistant) -> None:
    p = _patches()
    with p[0], p[1], p[2], p[3], p[4]:
        result = await _start(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**USER, CONF_STORE_PASSWORD: True}
        )
    assert result["data"][CONF_PASSWORD] == "pw"


async def test_two_factor(hass: HomeAssistant) -> None:
    login = AsyncMock(
        side_effect=[api.TwoFactorRequired("2fa", 412), {"secret": "s2", "id": "u"}]
    )
    p = _patches(login)
    with p[0], p[1], p[2], p[3], p[4]:
        result = await _start(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER)
        assert result["step_id"] == "twofa"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"twofa": "123456"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert login.await_args.args[3] == "123456"


async def test_bad_login(hass: HomeAssistant) -> None:
    p = _patches(AsyncMock(side_effect=api.AuthError("no", 400)))
    with p[0], p[1], p[2], p[3], p[4]:
        result = await _start(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER)
    assert result["errors"] == {"base": "invalid_auth"}


async def test_bad_device_name(hass: HomeAssistant) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER, CONF_DEVICE_NAME: "bad name!"}
    )
    assert result["errors"] == {CONF_DEVICE_NAME: "invalid_name"}


async def test_reauth_keeps_device(hass: HomeAssistant, mock_entry) -> None:
    mock_entry.add_to_hass(hass)
    p = _patches(AsyncMock(return_value={"secret": "new", "id": "u"}))
    with p[0], p[1] as register, p[2], p[3], p[4]:
        result = await mock_entry.start_reauth_flow(hass)
        assert result["step_id"] == "reauth_confirm"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_EMAIL: "me@example.com", CONF_PASSWORD: "pw"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_entry.data[CONF_SECRET] == "new"
    assert mock_entry.data[CONF_DEVICE_ID] == "dev123"
    register.assert_not_awaited()


async def test_options_regex_validation(hass: HomeAssistant, mock_entry) -> None:
    mock_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    base = {"message_mode": "regex", "min_priority": "-2"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**base, "regex": "([unclosed"}
    )
    assert result["errors"] == {"regex": "invalid_regex"}
    with patch(
        "custom_components.push_alert_tts.async_setup_entry",
        new=AsyncMock(return_value=True),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**base, "regex": r"^(?P<say>[^\n]+)"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_entry.options["regex"] == r"^(?P<say>[^\n]+)"


async def test_reconfigure_turns_off_saved_password(
    hass: HomeAssistant, mock_entry
) -> None:
    mock_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_entry,
        data={**mock_entry.data, CONF_PASSWORD: "old", CONF_STORE_PASSWORD: True},
    )
    p = _patches(AsyncMock(return_value={"secret": "s9", "id": "u"}))
    with p[0], p[1], p[2], p[3], p[4]:
        result = await mock_entry.start_reconfigure_flow(hass)
        assert result["step_id"] == "reconfigure"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_EMAIL: "me@example.com",
                CONF_PASSWORD: "pw",
                CONF_STORE_PASSWORD: False,
            },
        )
    assert result["reason"] == "reconfigure_successful"
    assert CONF_PASSWORD not in mock_entry.data
    assert mock_entry.data[CONF_SECRET] == "s9"


async def test_reauth_wrong_account(hass: HomeAssistant, mock_entry) -> None:
    mock_entry.add_to_hass(hass)
    p = _patches(AsyncMock(return_value={"secret": "new", "id": "u"}))
    with p[0], p[1], p[2], p[3], p[4]:
        result = await mock_entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_EMAIL: "someone@else.com", CONF_PASSWORD: "pw"}
        )
    assert result["reason"] == "wrong_account"
    assert mock_entry.data[CONF_SECRET] == "secret123"


async def test_reauth_outage_keeps_device(hass: HomeAssistant, mock_entry) -> None:
    mock_entry.add_to_hass(hass)
    p = _patches(AsyncMock(return_value={"secret": "new", "id": "u"}))
    with (
        p[0],
        p[1] as register,
        patch(
            f"{API}.async_fetch_messages",
            new=AsyncMock(side_effect=api.PushoverError("503", 503)),
        ),
        p[3],
        p[4],
    ):
        result = await mock_entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_EMAIL: "me@example.com", CONF_PASSWORD: "pw"}
        )
    assert result["errors"] == {"base": "cannot_connect"}
    register.assert_not_awaited()
