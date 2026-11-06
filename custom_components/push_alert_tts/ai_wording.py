"""Optional AI wording: ask a local LLM to turn an alert into a short sentence.

Works with Ollama (``/api/chat``) and any OpenAI-compatible server
(``/v1/chat/completions``: LM Studio, llama.cpp, vLLM, LocalAI, OpenAI ...).

The LLM only *rewords*. The coordinator always has the normal spoken text
ready and uses it whenever this module reports a problem, so an alert is
never lost or held back by the AI for longer than the configured timeout.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

import aiohttp

from .const import (
    AI_API_OPENAI,
    AI_CONNECT_TIMEOUT,
    MAX_MESSAGE_INPUT,
    MAX_TITLE_INPUT,
)

DEFAULT_INSTRUCTIONS = """You turn a monitoring or notification alert into a very short spoken message for a smart speaker.
Say what is affected and what is wrong, most important first.
At most {max_words} words. Plain spoken words only: no symbols, markdown, URLs, IDs, IP addresses or email addresses.
Use only facts in the alert and in the memory below. Never invent anything.
Reply with the spoken message only."""

MEMORY_HEADING = "Memory (corrections from the owner; always follow them):"

# Reasons the AI text was not used (shown in history, sensors and preview).
REASON_DISABLED = "ai_off"
REASON_MULTIPLE = "several_alerts"
REASON_OFFLINE = "llm_unreachable"
REASON_OFFLINE_RECENT = "llm_unreachable_recently"
REASON_TIMEOUT = "llm_timeout"
REASON_HTTP = "llm_http_error"
REASON_BAD_RESPONSE = "llm_bad_response"
REASON_EMPTY = "llm_empty"
REASON_TOO_LONG = "llm_too_long"
REASON_SYMBOLS = "llm_symbols"
REASON_SHAPE = "llm_wrong_shape"
REASON_ERROR = "llm_error"

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")
_FORBIDDEN_RE = re.compile(r"https?://|www\.|[<>{}\[\]|@#*`_\\]", re.IGNORECASE)
_QUOTES = "\"'“”‘’` "
_CONNECT_TIMEOUT: tuple[type[BaseException], ...] = tuple(
    t for t in (getattr(aiohttp, "ConnectionTimeoutError", None),) if t is not None
)


class AIError(Exception):
    """The LLM gave no usable answer. ``reason`` is one of the REASON_ codes."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


def alert_text(alert: Mapping[str, Any]) -> str:
    """The alert exactly as received: title, then message (title not repeated)."""
    title = str(alert.get("title") or "")[:MAX_TITLE_INPUT]
    message = str(alert.get("message") or "")[:MAX_MESSAGE_INPUT]
    if not title or message.startswith(title.strip()):
        return message or title
    if not message:
        return title
    return f"{title}\n{message}"


def system_prompt(
    instructions: str | None, memory: Iterable[str], max_words: int
) -> str:
    """Instructions (or the default) plus the owner's memory lines."""
    text = (instructions or "").strip() or DEFAULT_INSTRUCTIONS
    text = text.replace("{max_words}", str(max_words))
    lines = [line.strip() for line in memory if line and line.strip()]
    if lines:
        text += (
            "\n\n" + MEMORY_HEADING + "\n" + "\n".join(f"- {line}" for line in lines)
        )
    return text


def check_answer(
    text: str | None, max_words: int, start_pattern: str | None
) -> tuple[str | None, str | None]:
    """Clean the answer and check it is speakable. Returns (text, reason)."""
    text = _THINK_RE.sub(" ", text or "")
    text = _SPACE_RE.sub(" ", text).strip().strip(_QUOTES).strip()
    if not text:
        return None, REASON_EMPTY
    if max_words > 0 and len(text.split()) > max(max_words + 5, int(max_words * 1.5)):
        return None, REASON_TOO_LONG
    if _FORBIDDEN_RE.search(text):
        return None, REASON_SYMBOLS
    if start_pattern:
        try:
            if not re.match(start_pattern, text, re.IGNORECASE):
                return None, REASON_SHAPE
        except re.error:
            return None, REASON_SHAPE
    return text, None


_KEEP_ALIVE_RE = re.compile(r"^(-?\d+|(\d+(\.\d+)?(ms|s|m|h))+)$")


def keep_alive_value(text: Any) -> str | int | None:
    """Ollama keep_alive from the setting: None (server default), int or duration."""
    value = str(text or "").strip()
    if not value:
        return None
    if not _KEEP_ALIVE_RE.match(value):
        raise ValueError(value)
    return int(value) if re.match(r"^-?\d+$", value) else value


def endpoint(api: str, url: str) -> str:
    base = url.strip().rstrip("/")
    if api == AI_API_OPENAI:
        if base.endswith("/chat/completions"):
            return base
        if not base.endswith("/v1"):
            base += "/v1"
        return base + "/chat/completions"
    if base.endswith("/api/chat"):
        return base
    return base + "/api/chat"


async def ask(
    session: aiohttp.ClientSession,
    *,
    api: str,
    url: str,
    model: str,
    system: str,
    user: str,
    timeout: float,
    api_key: str | None = None,
    max_tokens: int = 120,
    context_size: int | None = None,
    keep_alive: str | int | None = None,
    gpu_layers: int | None = None,
) -> str:
    """Send one chat request; return the raw answer text or raise AIError."""
    target = endpoint(api, url)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    if api == AI_API_OPENAI:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
            "stream": False,
        }
    else:
        body = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,  # thinking models answer far faster without it
            "options": {"temperature": 0, "num_predict": max_tokens},
        }
        # Match the settings other programs load the model with, so Ollama
        # does not reload it (slow) every time the caller changes.
        if context_size:
            body["options"]["num_ctx"] = int(context_size)
        if gpu_layers is not None:
            body["options"]["num_gpu"] = int(gpu_layers)
        if keep_alive is not None and keep_alive != "":
            body["keep_alive"] = keep_alive
    client_timeout = aiohttp.ClientTimeout(
        total=timeout, sock_connect=min(AI_CONNECT_TIMEOUT, timeout)
    )
    try:
        data = await _post(session, target, body, headers, client_timeout)
    except AIError as err:
        # Older Ollama versions / non-thinking models reject "think".
        if (
            err.reason == REASON_HTTP
            and "think" in err.detail.lower()
            and "think" in body
        ):
            body.pop("think")
            data = await _post(session, target, body, headers, client_timeout)
        else:
            raise
    try:
        if api == AI_API_OPENAI:
            return str(data["choices"][0]["message"]["content"] or "")
        return str(data["message"]["content"] or "")
    except (KeyError, IndexError, TypeError) as err:
        raise AIError(REASON_BAD_RESPONSE, f"unexpected answer: {err}") from err


async def _post(
    session: aiohttp.ClientSession,
    target: str,
    body: dict[str, Any],
    headers: dict[str, str],
    client_timeout: aiohttp.ClientTimeout,
) -> Any:
    try:
        async with session.post(
            target, json=body, headers=headers, timeout=client_timeout
        ) as resp:
            if resp.status >= 400:
                detail = (await resp.text())[:300]
                raise AIError(REASON_HTTP, f"HTTP {resp.status}: {detail}")
            try:
                return await resp.json(content_type=None)
            except ValueError as err:
                raise AIError(REASON_BAD_RESPONSE, "answer is not JSON") from err
    except AIError:
        raise
    except _CONNECT_TIMEOUT as err:
        # Could not even connect in AI_CONNECT_TIMEOUT: the host is off/asleep.
        raise AIError(REASON_OFFLINE, "connection timed out") from err
    except TimeoutError as err:  # includes aiohttp's read timeouts
        raise AIError(REASON_TIMEOUT, "no answer in time") from err
    except aiohttp.ClientConnectionError as err:
        raise AIError(REASON_OFFLINE, str(err)) from err
    except aiohttp.ClientError as err:
        raise AIError(REASON_ERROR, str(err)) from err
