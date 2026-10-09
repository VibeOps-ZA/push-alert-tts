"""Minimal async client for the Pushover Open Client API.

https://pushover.net/api/client
"""

from __future__ import annotations

from typing import Any

import aiohttp

from .const import (
    ACK_URL,
    DELETE_URL,
    DEVICES_URL,
    LOGIN_URL,
    MESSAGES_URL,
    USER_AGENT,
)

HEADERS = {"User-Agent": USER_AGENT}
TIMEOUT = aiohttp.ClientTimeout(total=30)


class PushoverError(Exception):
    """Generic Pushover API error."""

    def __init__(
        self, message: str, status: int | None = None, errors: Any = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.errors = errors or {}


class AuthError(PushoverError):
    """Login rejected (bad email/password or 2FA code)."""


class TwoFactorRequired(PushoverError):
    """Account needs a two-factor code."""


class SessionInvalid(PushoverError):
    """The stored session secret or device is no longer accepted."""


def as_int(value: Any) -> int:
    """Convert to int, defaulting to 0."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def message_id(msg: dict) -> int:
    """Return the per-device message id."""
    return as_int(msg.get("id_str") or msg.get("id"))


def _is_pushover_rejection(body: dict, status: int) -> bool:
    """True only for a real Pushover JSON reply rejecting the request.

    Proxies, CDNs and outages return other 4xx/5xx codes or non-JSON bodies;
    those are transient and must never be mistaken for a bad login.
    """
    return status in (400, 401, 403, 404) and body.get("status") == 0


def _raise_for(body: dict, status: int, what: str) -> None:
    if body.get("status") == 1:
        return
    errors = body.get("errors")
    if _is_pushover_rejection(body, status):
        raise SessionInvalid(f"{what} rejected (HTTP {status})", status, errors)
    raise PushoverError(f"{what} failed (HTTP {status})", status, errors)


async def _json(resp: aiohttp.ClientResponse) -> dict:
    try:
        body = await resp.json(content_type=None)
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


async def _post(
    session: aiohttp.ClientSession, url: str, data: dict
) -> tuple[int, dict]:
    async with session.post(url, data=data, headers=HEADERS, timeout=TIMEOUT) as resp:
        return resp.status, await _json(resp)


async def async_login(
    session: aiohttp.ClientSession,
    email: str,
    password: str,
    twofa: str | None = None,
) -> dict:
    """Log in and return the login body (id = user key, secret = session)."""
    data = {"email": email, "password": password}
    if twofa:
        data["twofa"] = twofa
    status, body = await _post(session, LOGIN_URL, data)
    if status == 412:
        raise TwoFactorRequired("Two-factor code required", status, body.get("errors"))
    if body.get("status") == 1 and body.get("secret"):
        return body
    if _is_pushover_rejection(body, status):
        raise AuthError("Login failed", status, body.get("errors"))
    raise PushoverError(f"Login failed (HTTP {status})", status, body.get("errors"))


async def async_register_device(
    session: aiohttp.ClientSession, secret: str, name: str
) -> str:
    """Register a new Open Client device and return its id."""
    status, body = await _post(
        session, DEVICES_URL, {"secret": secret, "name": name, "os": "O"}
    )
    if body.get("status") != 1 or not body.get("id"):
        raise PushoverError("Device registration failed", status, body.get("errors"))
    return body["id"]


async def async_fetch_messages(
    session: aiohttp.ClientSession, secret: str, device_id: str
) -> list[dict]:
    """Download all pending messages for the device."""
    async with session.get(
        MESSAGES_URL,
        params={"secret": secret, "device_id": device_id},
        headers=HEADERS,
        timeout=TIMEOUT,
    ) as resp:
        status = resp.status
        body = await _json(resp)
    _raise_for(body, status, "Message download")
    return list(body.get("messages") or [])


async def async_delete_through(
    session: aiohttp.ClientSession, secret: str, device_id: str, highest: int
) -> None:
    """Delete all messages up to and including `highest`."""
    status, body = await _post(
        session,
        DELETE_URL.format(device_id=device_id),
        {"secret": secret, "message": str(highest)},
    )
    _raise_for(body, status, "Message delete")


async def async_acknowledge(
    session: aiohttp.ClientSession, secret: str, receipt: str
) -> None:
    """Acknowledge an emergency-priority receipt (stops retries everywhere)."""
    status, body = await _post(
        session, ACK_URL.format(receipt=receipt), {"secret": secret}
    )
    _raise_for(body, status, "Acknowledge")
