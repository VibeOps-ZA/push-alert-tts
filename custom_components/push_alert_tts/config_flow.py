"""Config, re-auth and options flows for Push Alert TTS."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import api
from .const import (
    CONF_APP_FILTER,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_EMERGENCY_MESSAGE,
    CONF_FALLBACK_NOTIFY,
    CONF_FIXED_MESSAGE,
    CONF_MAX_LENGTH,
    CONF_MESSAGE_MODE,
    CONF_MIN_PRIORITY,
    CONF_MULTIPLE_MESSAGE,
    CONF_OFFLINE_ALERT_DELAY,
    CONF_REGEX,
    CONF_REPEAT_INTERVAL,
    CONF_REPEAT_MAX,
    CONF_SECRET,
    CONF_SPEAKERS,
    CONF_STORE_PASSWORD,
    CONF_TTS_ENTITY,
    CONF_TTS_LANGUAGE,
    CONF_TWOFA,
    CONF_USER_KEY,
    DEFAULT_DEVICE_NAME,
    DEFAULT_EMERGENCY_MESSAGE,
    DEFAULT_FIXED_MESSAGE,
    DEFAULT_MAX_LENGTH,
    DEFAULT_MIN_PRIORITY,
    DEFAULT_MULTIPLE_MESSAGE,
    DEFAULT_OFFLINE_ALERT_DELAY,
    DEFAULT_REPEAT_INTERVAL,
    DEFAULT_REPEAT_MAX,
    DOMAIN,
    MESSAGE_MODES,
    MODE_FIXED,
    MODE_REGEX,
    PRIORITIES,
)
from .text import REGEX_FLAGS

_LOGGER = logging.getLogger(__name__)
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,25}$")
PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


class PushAlertTTSConfigFlow(ConfigFlow, domain=DOMAIN):
    """Log in, register an Open Client device, optionally keep the password."""

    VERSION = 1

    def __init__(self) -> None:
        self._email = ""
        self._password = ""
        self._device_name = DEFAULT_DEVICE_NAME
        self._store_password = False

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return PushAlertTTSOptionsFlow()

    # -- initial setup ---------------------------------------------------------
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL].strip()
            self._password = user_input[CONF_PASSWORD]
            self._device_name = user_input[CONF_DEVICE_NAME].strip()
            self._store_password = user_input.get(CONF_STORE_PASSWORD, False)
            if not NAME_RE.match(self._device_name):
                errors[CONF_DEVICE_NAME] = "invalid_name"
            else:
                await self.async_set_unique_id(self._email.lower())
                self._abort_if_unique_id_configured()
                if (result := await self._login(None, errors)) is not None:
                    return result
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL, default=self._email): str,
                    vol.Required(CONF_PASSWORD): PASSWORD,
                    vol.Required(CONF_DEVICE_NAME, default=self._device_name): str,
                    vol.Optional(
                        CONF_STORE_PASSWORD, default=self._store_password
                    ): BooleanSelector(),
                }
            ),
            errors=errors,
        )

    async def async_step_twofa(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if (
                result := await self._login(user_input[CONF_TWOFA].strip(), errors)
            ) is not None:
                return result
        return self.async_show_form(
            step_id="twofa",
            data_schema=vol.Schema({vol.Required(CONF_TWOFA): str}),
            errors=errors,
        )

    # -- re-authentication -----------------------------------------------------
    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        self._email = entry_data.get(CONF_EMAIL, "")
        self._device_name = entry_data.get(CONF_DEVICE_NAME, DEFAULT_DEVICE_NAME)
        self._store_password = bool(entry_data.get(CONF_STORE_PASSWORD))
        return await self.async_step_reauth_confirm()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Log in again on demand, e.g. to turn the saved password on or off."""
        if user_input is None:
            data = self._get_reconfigure_entry().data
            self._email = data.get(CONF_EMAIL, "")
            self._device_name = data.get(CONF_DEVICE_NAME, DEFAULT_DEVICE_NAME)
            self._store_password = bool(data.get(CONF_STORE_PASSWORD))
        return await self.async_step_reauth_confirm(user_input, step_id="reconfigure")

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
        step_id: str = "reauth_confirm",
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL].strip()
            self._password = user_input[CONF_PASSWORD]
            self._store_password = user_input.get(CONF_STORE_PASSWORD, False)
            if (result := await self._login(None, errors)) is not None:
                return result
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL, default=self._email): str,
                    vol.Required(CONF_PASSWORD): PASSWORD,
                    vol.Optional(
                        CONF_STORE_PASSWORD, default=self._store_password
                    ): BooleanSelector(),
                }
            ),
            errors=errors,
        )

    def _existing_entry(self) -> ConfigEntry | None:
        if self.source == SOURCE_REAUTH:
            return self._get_reauth_entry()
        if self.source == SOURCE_RECONFIGURE:
            return self._get_reconfigure_entry()
        return None

    # -- shared login ----------------------------------------------------------
    async def _login(
        self, twofa: str | None, errors: dict[str, str]
    ) -> ConfigFlowResult | None:
        session = async_get_clientsession(self.hass)
        try:
            login = await api.async_login(session, self._email, self._password, twofa)
        except api.TwoFactorRequired:
            if twofa:
                errors["base"] = "invalid_twofa"
                return None
            return await self.async_step_twofa()
        except api.AuthError:
            errors["base"] = "invalid_twofa" if twofa else "invalid_auth"
            return None
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Pushover login failed")
            errors["base"] = "cannot_connect"
            return None

        secret = login["secret"]
        device_id: str | None = None
        existing_entry = self._existing_entry()
        if existing_entry is not None:
            # Must be the same Pushover account as before.
            await self.async_set_unique_id(self._email.lower())
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            existing = existing_entry.data.get(CONF_DEVICE_ID)
            try:  # keep the existing device if Pushover still has it
                await api.async_fetch_messages(session, secret, existing)
                device_id = existing
            except api.SessionInvalid:
                device_id = None  # device was removed; register a new one
            except Exception:  # noqa: BLE001 - outage; don't abandon the device
                _LOGGER.warning("Could not check the existing Pushover device")
                errors["base"] = "cannot_connect"
                return None

        if device_id is None:
            try:
                device_id = await api.async_register_device(
                    session, secret, self._device_name
                )
            except api.PushoverError as err:
                errors["base"] = (
                    "name_taken" if "name" in (err.errors or {}) else "register_failed"
                )
                _LOGGER.warning("Pushover device registration failed: %s", err.errors)
                return None
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Pushover device registration failed")
                errors["base"] = "cannot_connect"
                return None
            # New device: discard the welcome message and anything waiting.
            try:
                msgs = await api.async_fetch_messages(session, secret, device_id)
                if msgs:
                    await api.async_delete_through(
                        session, secret, device_id, max(api.message_id(m) for m in msgs)
                    )
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "Could not clear initial Pushover messages", exc_info=True
                )

        data = {
            CONF_EMAIL: self._email,
            CONF_SECRET: secret,
            CONF_DEVICE_ID: device_id,
            CONF_DEVICE_NAME: self._device_name,
            CONF_USER_KEY: login.get("id"),
            CONF_STORE_PASSWORD: self._store_password,
        }
        if self._store_password:
            data[CONF_PASSWORD] = self._password
        self._password = ""

        if existing_entry is not None:
            return self.async_update_reload_and_abort(existing_entry, data=data)
        return self.async_create_entry(
            title=f"Push Alert TTS ({self._email})",
            data=data,
            options={
                CONF_MESSAGE_MODE: MODE_FIXED,
                CONF_FIXED_MESSAGE: DEFAULT_FIXED_MESSAGE,
                CONF_MULTIPLE_MESSAGE: DEFAULT_MULTIPLE_MESSAGE,
                CONF_EMERGENCY_MESSAGE: DEFAULT_EMERGENCY_MESSAGE,
                CONF_MAX_LENGTH: DEFAULT_MAX_LENGTH,
                CONF_MIN_PRIORITY: str(DEFAULT_MIN_PRIORITY),
                CONF_REPEAT_INTERVAL: DEFAULT_REPEAT_INTERVAL,
                CONF_REPEAT_MAX: DEFAULT_REPEAT_MAX,
                CONF_OFFLINE_ALERT_DELAY: DEFAULT_OFFLINE_ALERT_DELAY,
            },
        )


class PushAlertTTSOptionsFlow(OptionsFlow):
    """Speakers, voice, what to say, filters and fallbacks."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current: dict[str, Any] = dict(self.config_entry.options)
        if user_input is not None:
            current = user_input
            if current.get(CONF_MESSAGE_MODE) == MODE_REGEX:
                if not current.get(CONF_REGEX):
                    errors[CONF_REGEX] = "regex_required"
                else:
                    try:
                        re.compile(current[CONF_REGEX], REGEX_FLAGS)
                    except re.error:
                        errors[CONF_REGEX] = "invalid_regex"
            notify = (current.get(CONF_FALLBACK_NOTIFY) or "").strip()
            if notify and not re.match(r"^notify\.[a-z0-9_]+$", notify):
                errors[CONF_FALLBACK_NOTIFY] = "invalid_notify"
            if not errors:
                return self.async_create_entry(data=current)

        notify_services = sorted(
            f"notify.{name}"
            for name in self.hass.services.async_services_for_domain("notify")
            if name not in ("send_message", "persistent_notification")
        )

        def opt(key: str, default: Any) -> Any:
            value = current.get(key)
            return default if value in (None, "") else value

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SPEAKERS, default=opt(CONF_SPEAKERS, [])
                ): EntitySelector(
                    EntitySelectorConfig(domain="media_player", multiple=True)
                ),
                vol.Optional(
                    CONF_TTS_ENTITY,
                    description={"suggested_value": current.get(CONF_TTS_ENTITY)},
                ): EntitySelector(EntitySelectorConfig(domain="tts")),
                vol.Optional(
                    CONF_TTS_LANGUAGE,
                    description={"suggested_value": current.get(CONF_TTS_LANGUAGE)},
                ): str,
                vol.Required(
                    CONF_MESSAGE_MODE, default=opt(CONF_MESSAGE_MODE, MODE_FIXED)
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=MESSAGE_MODES,
                        translation_key=CONF_MESSAGE_MODE,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(
                    CONF_FIXED_MESSAGE,
                    default=opt(CONF_FIXED_MESSAGE, DEFAULT_FIXED_MESSAGE),
                ): str,
                vol.Optional(
                    CONF_REGEX,
                    description={"suggested_value": current.get(CONF_REGEX)},
                ): TextSelector(TextSelectorConfig(multiline=False)),
                vol.Optional(
                    CONF_MAX_LENGTH, default=opt(CONF_MAX_LENGTH, DEFAULT_MAX_LENGTH)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=2000, step=10, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_MULTIPLE_MESSAGE,
                    default=opt(CONF_MULTIPLE_MESSAGE, DEFAULT_MULTIPLE_MESSAGE),
                ): str,
                vol.Optional(
                    CONF_EMERGENCY_MESSAGE,
                    default=opt(CONF_EMERGENCY_MESSAGE, DEFAULT_EMERGENCY_MESSAGE),
                ): str,
                vol.Optional(
                    CONF_APP_FILTER,
                    description={"suggested_value": current.get(CONF_APP_FILTER)},
                ): str,
                vol.Required(
                    CONF_MIN_PRIORITY,
                    default=str(opt(CONF_MIN_PRIORITY, DEFAULT_MIN_PRIORITY)),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            {"value": k, "label": v} for k, v in PRIORITIES.items()
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_FALLBACK_NOTIFY,
                    description={"suggested_value": current.get(CONF_FALLBACK_NOTIFY)},
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=notify_services,
                        custom_value=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_REPEAT_INTERVAL,
                    default=opt(CONF_REPEAT_INTERVAL, DEFAULT_REPEAT_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=15,
                        max=3600,
                        step=5,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_REPEAT_MAX, default=opt(CONF_REPEAT_MAX, DEFAULT_REPEAT_MAX)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=100, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_OFFLINE_ALERT_DELAY,
                    default=opt(CONF_OFFLINE_ALERT_DELAY, DEFAULT_OFFLINE_ALERT_DELAY),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=15,
                        max=3600,
                        step=5,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
