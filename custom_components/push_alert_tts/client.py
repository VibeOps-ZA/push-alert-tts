"""Pushover Open Client connection: websocket listener, sync, login recovery."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import api
from .const import (
    CONF_DEVICE_ID,
    CONF_SECRET,
    KEEPALIVE_TIMEOUT,
    QUEUED_AGE,
    RETRY_MAX,
    RETRY_MIN,
    WS_URL,
)

_LOGGER = logging.getLogger(__name__)

STATUS_CONNECTING = "connecting"
STATUS_CONNECTED = "connected"
STATUS_RECONNECTING = "reconnecting"
STATUS_LOGIN_REQUIRED = "login_required"
STATUS_STOPPED = "stopped"

RELOGIN_COOLDOWN = 600


class _Reconnect(Exception):
    """Drop the websocket and reconnect."""


class LoginRequired(Exception):
    """The session is rejected and could not be renewed automatically."""


class DeviceStopped(Exception):
    """Pushover refuses this device (licence, device removed, elsewhere)."""

    def __init__(self, message: str, final: bool = False) -> None:
        super().__init__(message)
        self.final = final  # True = Pushover says never reconnect on our own


AlertCallback = Callable[[list[dict], bool], Awaitable[None]]
StatusCallback = Callable[[], None]


class PushoverListener:
    """Keeps the Pushover websocket open and hands new alerts to a callback.

    It never gives up on its own except when Pushover says this device logged
    in elsewhere (their guidelines forbid reconnecting then). Login problems
    and refusals are reported through the status, and retried slowly so a
    false alarm (proxy error, outage) heals itself.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        on_alerts: AlertCallback,
        on_status: StatusCallback,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.session = async_get_clientsession(hass)
        self._on_alerts = on_alerts
        self._on_status = on_status
        self.status = STATUS_CONNECTING
        self.last_error: str | None = None
        self.stop_reason: str | None = None
        self._highest_handled = 0
        self._sync_lock = asyncio.Lock()
        self._last_relogin: float | None = None
        self._renewed = False

    # -- helpers ---------------------------------------------------------------
    @property
    def secret(self) -> str:
        return self.entry.data[CONF_SECRET]

    @property
    def device_id(self) -> str:
        return self.entry.data[CONF_DEVICE_ID]

    @property
    def connected(self) -> bool:
        return self.status == STATUS_CONNECTED

    def _set_status(self, status: str) -> None:
        if self.status != status:
            self.status = status
            self._on_status()

    # -- main loop ---------------------------------------------------------------
    async def run(self) -> None:
        """Connect, listen and reconnect with back-off."""
        delay = RETRY_MIN
        while True:
            was_connected = False
            try:
                await self._listen_once()
            except asyncio.CancelledError:
                raise  # unloading; don't report a status change
            except LoginRequired as err:
                self.last_error = self.stop_reason = str(err)
                self._set_status(STATUS_LOGIN_REQUIRED)
                delay = RETRY_MAX
            except DeviceStopped as err:
                self.last_error = self.stop_reason = str(err)
                self._set_status(STATUS_STOPPED)
                if err.final:
                    return
                delay = RETRY_MAX
            except _Reconnect as err:
                was_connected = self.connected
                self.last_error = str(err)
                _LOGGER.info("Pushover connection reconnecting: %s", err)
            except TimeoutError:
                was_connected = self.connected
                self.last_error = "no keep-alive from Pushover"
                _LOGGER.warning(
                    "No keep-alive from Pushover for %ss, reconnecting",
                    KEEPALIVE_TIMEOUT,
                )
            except Exception as err:  # noqa: BLE001 - network, DNS, 5xx, ...
                was_connected = self.connected
                self.last_error = str(err) or type(err).__name__
                _LOGGER.warning("Pushover connection error: %s", self.last_error)

            if was_connected:
                delay = RETRY_MIN  # a healthy connection dropped; start over
            if self.status not in (STATUS_LOGIN_REQUIRED, STATUS_STOPPED):
                self._set_status(STATUS_RECONNECTING)
            await asyncio.sleep(delay)
            delay = min(delay * 2, RETRY_MAX)

    async def _listen_once(self) -> None:
        async with self.session.ws_connect(WS_URL, headers=api.HEADERS) as ws:
            await ws.send_str(f"login:{self.device_id}:{self.secret}\n")
            # Pick up anything that queued while disconnected.
            await self._sync_and_check(startup=True)
            self.last_error = self.stop_reason = None
            self._set_status(STATUS_CONNECTED)
            while True:
                msg = await asyncio.wait_for(ws.receive(), KEEPALIVE_TIMEOUT)
                if msg.type == aiohttp.WSMsgType.BINARY:
                    frames = msg.data.decode("ascii", "ignore")
                elif msg.type == aiohttp.WSMsgType.TEXT:
                    frames = msg.data
                else:
                    raise _Reconnect(f"websocket closed ({msg.type.name})")
                for frame in frames:
                    if frame == "!":
                        await self._sync_and_check(startup=False)
                    elif frame == "R":
                        raise _Reconnect("reload requested by Pushover")
                    elif frame == "E":
                        await self._handle_session_error(
                            "Pushover reported a permanent error for this device"
                        )
                        raise _Reconnect("re-logged in after device error")
                    elif frame == "A":
                        raise DeviceStopped(
                            "This Pushover device logged in from another session. "
                            "Reload the integration to take it back.",
                            final=True,
                        )

    async def _sync_and_check(self, startup: bool) -> None:
        await self.sync(startup)
        if self._renewed:
            # The websocket is still logged in with the old secret.
            self._renewed = False
            raise _Reconnect("session renewed")

    # -- login recovery --------------------------------------------------------
    async def _handle_session_error(self, reason: str) -> None:
        """Try an automatic re-login, else report that a login is needed."""
        password = self.entry.data.get(CONF_PASSWORD)
        if not password:
            raise LoginRequired(f"{reason}; please log in again")
        if (
            self._last_relogin is not None
            and time.monotonic() - self._last_relogin < RELOGIN_COOLDOWN
        ):
            # A fresh login didn't help: licence expired or device removed.
            raise DeviceStopped(
                f"{reason} even after logging in again. Check the Pushover "
                "Desktop licence and that the device still exists on pushover.net"
            )
        try:
            login = await api.async_login(
                self.session, self.entry.data[CONF_EMAIL], password
            )
        except api.TwoFactorRequired as err:
            raise LoginRequired(
                "Automatic re-login needs a two-factor code; please log in again"
            ) from err
        except api.AuthError as err:
            raise LoginRequired(
                "Saved Pushover password was rejected; please log in again"
            ) from err
        # Other errors (network, 5xx) propagate and are retried with back-off.
        self._last_relogin = time.monotonic()
        self._renewed = True
        _LOGGER.warning("Pushover session renewed with the saved password")
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, CONF_SECRET: login["secret"]}
        )

    # -- sync --------------------------------------------------------------------
    async def sync(self, startup: bool) -> None:
        """Download pending messages, hand them over, then delete them."""
        async with self._sync_lock:
            try:
                messages = await api.async_fetch_messages(
                    self.session, self.secret, self.device_id
                )
            except api.SessionInvalid:
                await self._handle_session_error("Pushover rejected the session")
                messages = await api.async_fetch_messages(
                    self.session, self.secret, self.device_id
                )
            if not messages:
                return
            messages.sort(key=api.message_id)
            highest = api.message_id(messages[-1])
            new = [m for m in messages if api.message_id(m) > self._highest_handled]
            if new:
                now = time.time()
                queued = startup or any(
                    now - api.as_int(m.get("date")) > QUEUED_AGE for m in new
                )
                # Only delete once the alerts have been handed over, so
                # nothing is lost if Home Assistant stops part-way.
                await self._on_alerts(new, queued)
            self._highest_handled = max(self._highest_handled, highest)
            await api.async_delete_through(
                self.session, self.secret, self.device_id, highest
            )

    async def acknowledge(self, receipt: str) -> None:
        await api.async_acknowledge(self.session, self.secret, receipt)
