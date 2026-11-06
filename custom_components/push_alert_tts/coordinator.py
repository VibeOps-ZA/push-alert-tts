"""Runtime for Push Alert TTS: decides what to say and where, and says it."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import OrderedDict, deque
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_OFF,
    STATE_PLAYING,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import api, llm
from .client import STATUS_LOGIN_REQUIRED, STATUS_STOPPED, PushoverListener
from .const import (
    AI_API_OLLAMA,
    AI_OFFLINE_SKIP,
    AI_REVIEW_DAYS,
    AI_REVIEW_MAX,
    CONF_AI_API,
    CONF_AI_API_KEY,
    CONF_AI_CONTEXT,
    CONF_AI_EMERGENCY_TIMEOUT,
    CONF_AI_ENABLED,
    CONF_AI_GPU_LAYERS,
    CONF_AI_INSTRUCTIONS,
    CONF_AI_KEEP_ALIVE,
    CONF_AI_MAX_WORDS,
    CONF_AI_MODEL,
    CONF_AI_START_PATTERN,
    CONF_AI_TIMEOUT,
    CONF_AI_URL,
    CONF_EMERGENCY_MESSAGE,
    CONF_FALLBACK_NOTIFY,
    CONF_HISTORY_DAYS,
    CONF_MESSAGE_MODE,
    CONF_OFFLINE_ALERT_DELAY,
    CONF_REPEAT_INTERVAL,
    CONF_REPEAT_MAX,
    CONF_SPEAKERS,
    CONF_TTS_ENTITY,
    CONF_TTS_LANGUAGE,
    DEFAULT_AI_EMERGENCY_TIMEOUT,
    DEFAULT_AI_MAX_WORDS,
    DEFAULT_AI_TIMEOUT,
    DEFAULT_EMERGENCY_MESSAGE,
    DEFAULT_HISTORY_DAYS,
    DEFAULT_OFFLINE_ALERT_DELAY,
    DEFAULT_REPEAT_INTERVAL,
    DEFAULT_REPEAT_MAX,
    DEFAULT_VOLUME,
    DOMAIN,
    EVENT_ACK,
    EVENT_ALERT,
    ISSUE_STOPPED,
    MAX_AI_CONTEXT,
    MAX_AI_GPU_LAYERS,
    MAX_AI_TIMEOUT,
    MAX_HISTORY_DAYS,
    MAX_MESSAGE_INPUT,
    MAX_TITLE_INPUT,
    MESSAGE_FIELDS,
    MODE_REGEX,
    PLAYBACK_END_TIMEOUT,
    PLAYBACK_START_TIMEOUT,
    SIGNAL_UPDATE,
    TEXT_TIMEOUT,
    WAKE_TIMEOUT,
)
from .memory import read_memory, split_lines, write_memory
from .spoken import (
    OUTCOME_ERROR,
    OUTCOME_MULTIPLE,
    OUTCOME_TIMEOUT,
    build_spoken,
    build_text,
    clean,
    should_announce,
)

SOURCE_AI = "ai"
SOURCE_FILTER = "filter"  # the normal (non-AI) spoken text

_LOGGER = logging.getLogger(__name__)
_BAD_STATES = (STATE_UNAVAILABLE, STATE_UNKNOWN, None)

SERVICE_TIMEOUT = 15  # volume / mute / power calls
TTS_TIMEOUT = 45  # text-to-speech call (cloud engines can be slow)
RECEIPT_LIFETIME = 3 * 3600  # Pushover emergency receipts expire within 3 h
SPEAKER_SETTLE = 30  # wait this long at start-up for speakers to load
STORE_VERSION = 1
MAX_HISTORY_ENTRIES = 20000  # hard cap on the history file, whatever the age
HISTORY_PRUNE_INTERVAL = timedelta(hours=24)


def history_record(
    msg: Mapping[str, Any],
    received: datetime,
    *,
    queued: bool,
    announced: bool,
    spoken_text: str | None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One line of the history file (the raw alert, length-capped).

    ``extra`` adds the AI fields and step timings for the announced alert.
    """
    sent = api.as_int(msg.get("date"))
    row = {
        "received": received.isoformat(timespec="seconds"),
        "sent": (
            dt_util.utc_from_timestamp(sent).isoformat(timespec="seconds")
            if sent
            else None
        ),
        "app": str(msg.get("app") or ""),
        "priority": api.as_int(msg.get("priority")),
        "title": str(msg.get("title") or "")[:MAX_TITLE_INPUT],
        "message": str(msg.get("message") or "")[:MAX_MESSAGE_INPUT],
        "message_length": len(str(msg.get("message") or "")),
        "url": msg.get("url") or None,
        "url_title": msg.get("url_title") or None,
        "queued": queued,
        "announced": announced,
        "spoken_text": spoken_text,
    }
    if extra:
        row.update(extra)
    return row


def review_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """A history row as shown by the AI review sensor."""
    return {
        "received": row.get("received"),
        "alert": llm.alert_text(row),
        "spoken": row.get("spoken_text"),
        "ai_text": row.get("ai_text"),
        "source": row.get("spoken_source"),
        "reason": row.get("ai_reason"),
        "ai_seconds": row.get("ai_seconds"),
    }


def read_review(path: str, now: datetime) -> list[dict[str, Any]]:
    """Recent rows the AI looked at (oldest first), for the review sensor."""
    cutoff = now - timedelta(days=AI_REVIEW_DAYS)
    rows = []
    for row in _read_lines(path):
        if "ai_reason" not in row and "ai_text" not in row:
            continue
        when = _parse_time(row.get("received"))
        if when is not None and when >= cutoff:
            rows.append(review_row(row))
    return rows[-AI_REVIEW_MAX:]


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt_util.UTC)


def _read_lines(path: str) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue  # a half-written line after a power cut
            if isinstance(row, dict):
                rows.append(row)
    return rows


def append_history(path: str, rows: list[dict[str, Any]]) -> None:
    """Append rows (runs in the executor: small appends, kind to SD cards)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def prune_history(path: str, days: int, now: datetime) -> int:
    """Drop rows older than `days` (0 deletes the file). Returns rows kept."""
    if days <= 0:
        if os.path.exists(path):
            os.remove(path)
        return 0
    rows = _read_lines(path)
    cutoff = now - timedelta(days=days)
    kept = [
        r
        for r in rows
        if (when := _parse_time(r.get("received"))) is not None and when >= cutoff
    ][-MAX_HISTORY_ENTRIES:]
    if len(kept) != len(rows):
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in kept)
        os.replace(tmp, path)
    return len(kept)


def read_history(
    path: str, days: int, limit: int, search: str | None, now: datetime
) -> list[dict[str, Any]]:
    """Newest first, optionally filtered by age and a case-insensitive search."""
    cutoff = now - timedelta(days=days) if days > 0 else None
    needle = (search or "").strip().lower()
    out: list[dict[str, Any]] = []
    for row in reversed(_read_lines(path)):
        if cutoff is not None:
            when = _parse_time(row.get("received"))
            if when is None or when < cutoff:
                continue
        if needle and not any(
            needle in str(row.get(k) or "").lower()
            for k in ("title", "message", "app", "spoken_text")
        ):
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _ms_since(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


class _Marks:
    """Records step times (ms since t0) into a timings dict, if there is one."""

    def __init__(self, timings: dict[str, Any] | None, t0: float | None) -> None:
        self.timings = timings
        self.t0 = t0

    def __call__(self, key: str) -> None:
        if self.timings is not None and self.t0 is not None:
            self.timings[key] = _ms_since(self.t0)


class AlertTTS:
    """Everything one Push Alert TTS config entry needs at runtime."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.listener = PushoverListener(hass, entry, self._on_alerts, self._on_status)
        self._store: Store[dict[str, Any]] = Store(
            hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        # Values owned by entities (restored on start-up).
        self.enabled = False
        self.repeat_until_ack = False
        self.volume: float = DEFAULT_VOLUME
        # State shown on sensors.
        self.last_alert: dict[str, Any] | None = None
        self.last_alert_time: datetime | None = None
        self.last_spoken: str | None = None
        self._receipts: dict[str, float] = {}  # receipt -> expiry (epoch)
        self._speak_lock = asyncio.Lock()
        self._repeat_task: asyncio.Task | None = None
        self._ack_event = asyncio.Event()
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._offline_timer: CALLBACK_TYPE | None = None
        self._offline_notified = False
        self._login_notified = False
        self._stopping = False
        self._speaker_unsub: CALLBACK_TYPE | None = None
        self._timers: set[CALLBACK_TYPE] = set()
        self._started_at = time.monotonic()
        # The last alert as received (not cleaned), for the preview action.
        self._last_raw: dict[str, Any] | None = None
        # Alert batches are processed one at a time, in arrival order.
        self._alert_lock = asyncio.Lock()
        self._history_lock = asyncio.Lock()
        self.history_path = hass.config.path(DOMAIN, f"history_{entry.entry_id}.jsonl")
        # AI wording.
        self.memory_path = hass.config.path(DOMAIN, f"ai_memory_{entry.entry_id}.txt")
        self.memory_versions_dir = hass.config.path(DOMAIN, "ai_memory_versions")
        self.memory: list[str] = []
        self._memory_lock = asyncio.Lock()
        self._ai_offline_until = 0.0  # monotonic; skip the LLM until then
        self.last_ai: dict[str, Any] | None = None  # last AI attempt
        self.review: deque[dict[str, Any]] = deque(maxlen=AI_REVIEW_MAX)

    # -- options (read live, so changes apply without a reload) ----------------
    @property
    def options(self) -> Mapping[str, Any]:
        return self.entry.options

    @property
    def speakers(self) -> list[str]:
        return list(self.options.get(CONF_SPEAKERS) or [])

    @property
    def history_days(self) -> int:
        days = api.as_int(self.options.get(CONF_HISTORY_DAYS, DEFAULT_HISTORY_DAYS))
        return max(0, min(days, MAX_HISTORY_DAYS))

    @property
    def ai_enabled(self) -> bool:
        return bool(
            self.options.get(CONF_AI_ENABLED)
            and self.options.get(CONF_AI_URL)
            and self.options.get(CONF_AI_MODEL)
        )

    def _ai_number(self, key: str, default: int, maximum: int) -> int:
        value = api.as_int(self.options.get(key, default)) or default
        return max(1, min(value, maximum))

    def _ai_model_settings(self) -> tuple[int | None, str | int | None, int | None]:
        """Context size, keep-alive and GPU layers for Ollama; None = default."""
        context = api.as_int(self.options.get(CONF_AI_CONTEXT)) or 0
        context = min(context, MAX_AI_CONTEXT) if context > 0 else None
        try:
            keep_alive = llm.keep_alive_value(self.options.get(CONF_AI_KEEP_ALIVE))
        except ValueError:
            keep_alive = None
        gpu = self.options.get(CONF_AI_GPU_LAYERS)
        gpu_layers = (
            None
            if gpu is None or gpu == ""
            else max(0, min(api.as_int(gpu), MAX_AI_GPU_LAYERS))
        )
        return context, keep_alive, gpu_layers

    @property
    def pending_receipts(self) -> list[str]:
        now = time.time()
        return [r for r, expiry in self._receipts.items() if expiry > now]

    # -- lifecycle -------------------------------------------------------------
    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        now = time.time()
        self._receipts = {
            r: e for r, e in (data.get("receipts") or {}).items() if e > now
        }
        try:
            self.memory = await self.hass.async_add_executor_job(
                read_memory, self.memory_path
            )
            self.review.extend(
                await self.hass.async_add_executor_job(
                    read_review, self.history_path, dt_util.utcnow()
                )
            )
        except OSError as err:
            _LOGGER.warning("Could not read the AI memory or history: %s", err)

    @callback
    def async_start(self) -> None:
        self.async_options_changed()

        @callback
        def _start(_hass: HomeAssistant) -> None:
            # Start once Home Assistant has finished starting, so speakers and
            # the TTS engine exist before queued alerts are announced.
            if not self._stopping:
                self._started_at = time.monotonic()
                self.entry.async_create_background_task(
                    self.hass, self.listener.run(), f"{DOMAIN}_listener"
                )

        self.entry.async_on_unload(async_at_started(self.hass, _start))

        async def _prune(_now: Any) -> None:
            await self.async_prune_history()

        self.entry.async_on_unload(
            async_track_time_interval(self.hass, _prune, HISTORY_PRUNE_INTERVAL)
        )

    @callback
    def async_options_changed(self) -> None:
        """(Re)subscribe to the selected speakers."""
        if self._speaker_unsub:
            self._speaker_unsub()
            self._speaker_unsub = None
        if self.speakers:
            self._speaker_unsub = async_track_state_change_event(
                self.hass, self.speakers, self._on_speaker_change
            )
        # Apply a changed (or switched off) history period straight away.
        self.entry.async_create_background_task(
            self.hass, self.async_prune_history(), f"{DOMAIN}_history_prune"
        )
        self.update_entities()

    @callback
    def async_stop(self) -> None:
        self._stopping = True
        if self._speaker_unsub:
            self._speaker_unsub()
        for unsub in list(self._timers):
            unsub()
        self._timers.clear()
        self._cancel_offline_timer()
        self._stop_repeats()

    @callback
    def update_entities(self) -> None:
        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}")

    def _later(self, delay: float, action: Any) -> None:
        unsub: CALLBACK_TYPE | None = None

        async def _run(now: Any) -> None:
            self._timers.discard(unsub)
            if not self._stopping:
                await action(now)

        unsub = async_call_later(self.hass, delay, _run)
        self._timers.add(unsub)

    def _save_receipts(self) -> None:
        self._store.async_delay_save(lambda: {"receipts": self._receipts}, 1)

    # -- connection status -----------------------------------------------------
    @callback
    def _on_status(self) -> None:
        if self._stopping:
            return
        status = self.listener.status
        if self.listener.connected:
            self._cancel_offline_timer()
            if self._offline_notified:
                self.hass.async_create_task(
                    self._notify_fallback("Pushover connection restored.")
                )
            self._offline_notified = False
            self._login_notified = False
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_STOPPED)
            persistent_notification.async_dismiss(self.hass, f"{DOMAIN}_login")
        elif status == STATUS_LOGIN_REQUIRED and not self._login_notified:
            self._login_notified = True
            self._raise_login_problem()
        elif status == STATUS_STOPPED and self.listener.stop_reason:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                ISSUE_STOPPED,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key=ISSUE_STOPPED,
                translation_placeholders={"reason": self.listener.stop_reason},
            )
            self.hass.async_create_task(
                self._notify_fallback(
                    f"Push Alert TTS stopped: {self.listener.stop_reason}"
                )
            )
        if not self.listener.connected and self._offline_timer is None:
            delay = int(
                self.options.get(CONF_OFFLINE_ALERT_DELAY, DEFAULT_OFFLINE_ALERT_DELAY)
            )
            self._offline_timer = async_call_later(
                self.hass, delay, self._offline_check
            )
        self.update_entities()

    def _raise_login_problem(self) -> None:
        reason = self.listener.stop_reason or "Pushover login required"
        _LOGGER.error("Push Alert TTS: %s", reason)
        self.entry.async_start_reauth(self.hass)
        persistent_notification.async_create(
            self.hass,
            f"{reason}. Open Settings > Devices & services > Push Alert TTS and "
            "re-authenticate.",
            title="Push Alert TTS needs you to log in again",
            notification_id=f"{DOMAIN}_login",
        )
        self.hass.async_create_task(self._notify_fallback(f"Push Alert TTS: {reason}"))

    def _cancel_offline_timer(self) -> None:
        if self._offline_timer:
            self._offline_timer()
            self._offline_timer = None

    async def _offline_check(self, _now: Any) -> None:
        self._offline_timer = None
        if (
            self._stopping
            or self.listener.connected
            or not self.enabled
            or self._offline_notified
        ):
            return
        self._offline_notified = True
        detail = self.listener.last_error or self.listener.status
        await self._notify_fallback(
            f"Pushover connection offline - alerts will not be announced ({detail})."
        )
        await self.speak("Pushover connection offline", notify_on_failure=False)

    # -- speakers going away while enabled --------------------------------------
    @callback
    def _on_speaker_change(self, event: Event[EventStateChangedData]) -> None:
        new = event.data["new_state"]
        old = event.data["old_state"]
        if not self.enabled or new is None or new.state != STATE_UNAVAILABLE:
            return
        if old is not None and old.state == STATE_UNAVAILABLE:
            return
        entity_id = event.data["entity_id"]

        async def _still_down(_now: Any) -> None:
            state = self.hass.states.get(entity_id)
            if self.enabled and state is not None and state.state == STATE_UNAVAILABLE:
                await self._notify_fallback(
                    f"{state.name} is unavailable - Push Alert TTS can't announce on it."
                )

        self._later(60, _still_down)

    async def async_enabled_changed(self, enabled: bool) -> None:
        """Called by the switch. Warn straight away if something is wrong."""
        self.enabled = enabled
        self.update_entities()
        if not enabled:
            self._stop_repeats()
            return
        problems = []
        if not self.listener.connected:
            problems.append(f"Pushover is {self.listener.status.replace('_', ' ')}")
        if not self.speakers:
            problems.append("no speakers are selected")
        if not self.options.get(CONF_TTS_ENTITY):
            problems.append("no text-to-speech engine is selected")
        down = [
            s
            for s in self.speakers
            if (st := self.hass.states.get(s)) is None or st.state in _BAD_STATES
        ]
        if down:
            problems.append("unavailable: " + ", ".join(down))
        if problems:
            await self._notify_fallback(
                "Push Alert TTS turned on, but " + "; ".join(problems) + "."
            )

    # -- alerts ------------------------------------------------------------------
    async def _on_alerts(self, messages: list[dict], queued: bool) -> None:
        """Called by the listener for every batch of new messages.

        Must not raise: the listener deletes the messages afterwards.
        """
        try:
            self._handle_alerts(messages, queued)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Failed to process Pushover alerts")
            if self.enabled:
                self.entry.async_create_background_task(
                    self.hass, self._announce(None, False), f"{DOMAIN}_announce"
                )

    def _handle_alerts(self, messages: list[dict], queued: bool) -> None:
        received = (dt_util.utcnow(), time.monotonic())
        acked_any = False
        fresh: list[dict] = []
        for m in messages:
            priority = api.as_int(m.get("priority"))
            receipt = m.get("receipt")
            if priority >= 2 and api.as_int(m.get("acked")):
                # Acknowledged elsewhere (e.g. on the phone).
                if receipt and self._receipts.pop(receipt, None) is not None:
                    acked_any = True
                continue
            key = str(m.get("umid_str") or m.get("umid") or m.get("id_str"))
            if key in self._seen:
                continue  # Pushover's own re-send of an emergency message
            self._seen[key] = None
            fresh.append(m)
        while len(self._seen) > 500:
            self._seen.popitem(last=False)
        if acked_any:
            self._save_receipts()
            if not self.pending_receipts:
                self._ack_event.set()
                self._stop_repeats()

        wanted = [m for m in fresh if should_announce(m, self.options)]
        for m in wanted:
            receipt = m.get("receipt")
            if receipt and api.as_int(m.get("priority")) >= 2:
                expire = api.as_int(m.get("expire")) or RECEIPT_LIFETIME
                self._receipts[receipt] = time.time() + min(expire, RECEIPT_LIFETIME)
                self._save_receipts()

        if not fresh:
            self.update_entities()
            return
        # Working out the text runs the user's regular expression, so it
        # happens in the background (in a worker thread, with a time limit)
        # and the listener can delete the messages promptly and keep receiving.
        self.entry.async_create_background_task(
            self.hass,
            self._process(fresh, wanted, queued, self.enabled, received),
            f"{DOMAIN}_process",
        )

    async def _process(
        self,
        fresh: list[dict],
        wanted: list[dict],
        queued: bool,
        enabled: bool,
        received: tuple[datetime, float] | None = None,
    ) -> None:
        if received is None:
            received = (dt_util.utcnow(), time.monotonic())
        async with self._alert_lock:
            try:
                await self._process_locked(fresh, wanted, queued, enabled, received)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Failed to process Pushover alerts")
                if enabled and wanted:
                    self.entry.async_create_background_task(
                        self.hass, self._announce(None, False), f"{DOMAIN}_announce"
                    )

    async def _process_locked(
        self,
        fresh: list[dict],
        wanted: list[dict],
        queued: bool,
        enabled: bool,
        received: tuple[datetime, float],
    ) -> None:
        received_at, t0 = received
        last = fresh[-1]
        top = max(api.as_int(m.get("priority")) for m in fresh)
        timings: dict[str, Any] = {}
        if sent := api.as_int(last.get("date")):
            timings["pushover_delay_s"] = round(received_at.timestamp() - sent, 1)
        spoken = await self.compute_spoken(wanted) if wanted else None
        filter_text = spoken["text"] if spoken else None
        timings["text_ms"] = _ms_since(t0)
        emergency = any(api.as_int(m.get("priority")) >= 2 for m in wanted)
        ai = await self.ai_wording(wanted, spoken, emergency) if wanted else None
        if ai is not None:
            timings["ai_done_ms"] = _ms_since(t0)
        use_ai = bool(ai and ai["text"])
        text = ai["text"] if use_ai else filter_text
        source = SOURCE_AI if use_ai else (SOURCE_FILTER if wanted else None)
        announce = bool(wanted) and enabled

        self._last_raw = {
            k: last.get(k) for k in ("title", "message", "app", "priority")
        }
        self.last_alert = {
            "title": clean(last.get("title") or last.get("app")),
            "message": clean(str(last.get("message") or "")[:MAX_MESSAGE_INPUT]),
            "app": last.get("app", ""),
            "priority": api.as_int(last.get("priority")),
            "count": len(fresh),
            "queued": queued,
            "announced": announce,
            "spoken_text": text if announce else None,
            "spoken_outcome": spoken["outcome"] if spoken else None,
            "spoken_source": source,
            "filter_text": filter_text,
            "ai_text": ai["text"] if ai else None,
            "ai_reason": ai["reason"] if ai else None,
            "ai_seconds": ai["seconds"] if ai else None,
            "timings": timings,
        }
        self.last_alert_time = received_at
        self.hass.bus.async_fire(
            EVENT_ALERT,
            {
                "count": len(fresh),
                "queued": queued,
                "highest_priority": top,
                "emergency": top >= 2,
                "title": self.last_alert["title"],
                "message": self.last_alert["message"],
                "app": self.last_alert["app"],
                "announced": announce,
                "spoken_text": text,
                "spoken_source": source,
                "messages": [{k: m.get(k) for k in MESSAGE_FIELDS} for m in fresh],
            },
        )
        self.update_entities()

        wanted_ids = {id(m) for m in wanted}
        extra: dict[str, Any] = {
            "spoken_source": source,
            "filter_text": filter_text,
            "timings": timings,  # shared: the announcement adds its steps
        }
        if ai is not None:
            extra.update(
                ai_text=ai["text"],
                ai_answer=ai["answer"],
                ai_reason=ai["reason"],
                ai_seconds=ai["seconds"],
            )
        rows = [
            history_record(
                m,
                received_at,
                queued=queued,
                announced=announce and id(m) in wanted_ids,
                spoken_text=text if id(m) in wanted_ids else None,
                extra=extra if id(m) in wanted_ids else None,
            )
            for m in fresh
        ]
        if announce:
            self.entry.async_create_background_task(
                self.hass,
                self._announce_and_record(text, emergency, rows, timings, t0),
                f"{DOMAIN}_announce",
            )
        else:
            await self._record(rows)

    async def _announce_and_record(
        self,
        text: str | None,
        emergency: bool,
        rows: list[dict[str, Any]],
        timings: dict[str, Any],
        t0: float,
    ) -> None:
        """Announce, then save the history with the announcement's timings."""
        try:
            await self._announce(text, emergency, timings, t0)
        finally:
            await self._record(rows)
            self.update_entities()

    async def _record(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            if "ai_reason" in row:
                self.review.append(review_row(row))
        if self.history_days:
            await self._write_history(rows)

    # -- AI wording --------------------------------------------------------------
    async def ai_wording(
        self,
        alerts: list[Mapping[str, Any]],
        spoken: Mapping[str, Any] | None,
        emergency: bool,
    ) -> dict[str, Any] | None:
        """Ask the LLM to word the alert. None when AI wording is off.

        Never raises. ``text`` is None when the normal text must be used, and
        ``reason`` then says why.
        """
        if not self.ai_enabled:
            return None
        started = time.monotonic()
        result: dict[str, Any] = {
            "text": None,
            "answer": None,
            "reason": None,
            "seconds": None,
        }
        if len(alerts) != 1 or (spoken and spoken.get("outcome") == OUTCOME_MULTIPLE):
            result["reason"] = llm.REASON_MULTIPLE
        elif started < self._ai_offline_until:
            result["reason"] = llm.REASON_OFFLINE_RECENT
        else:
            opts = self.options
            max_words = self._ai_number(CONF_AI_MAX_WORDS, DEFAULT_AI_MAX_WORDS, 200)
            timeout = (
                self._ai_number(
                    CONF_AI_EMERGENCY_TIMEOUT, DEFAULT_AI_EMERGENCY_TIMEOUT, 60
                )
                if emergency
                else self._ai_number(
                    CONF_AI_TIMEOUT, DEFAULT_AI_TIMEOUT, MAX_AI_TIMEOUT
                )
            )
            context_size, keep_alive, gpu_layers = self._ai_model_settings()
            try:
                answer = await llm.ask(
                    async_get_clientsession(self.hass),
                    api=opts.get(CONF_AI_API) or AI_API_OLLAMA,
                    url=str(opts.get(CONF_AI_URL)),
                    model=str(opts.get(CONF_AI_MODEL)),
                    system=llm.system_prompt(
                        opts.get(CONF_AI_INSTRUCTIONS), self.memory, max_words
                    ),
                    user=llm.alert_text(alerts[0]),
                    timeout=timeout,
                    api_key=opts.get(CONF_AI_API_KEY) or None,
                    max_tokens=max(60, max_words * 4),
                    context_size=context_size,
                    keep_alive=keep_alive,
                    gpu_layers=gpu_layers,
                )
                result["answer"] = answer
                result["text"], result["reason"] = llm.check_answer(
                    answer, max_words, opts.get(CONF_AI_START_PATTERN) or None
                )
            except llm.AIError as err:
                result["reason"] = err.reason
                if err.reason == llm.REASON_OFFLINE:
                    self._ai_offline_until = time.monotonic() + AI_OFFLINE_SKIP
                _LOGGER.info(
                    "AI wording not used (%s): %s; speaking the normal text",
                    err.reason,
                    err.detail,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.exception("AI wording failed; speaking the normal text")
                result["reason"] = llm.REASON_ERROR
        result["seconds"] = round(time.monotonic() - started, 2)
        self.last_ai = {
            **result,
            "time": dt_util.utcnow().isoformat(timespec="seconds"),
        }
        return result

    async def async_set_memory(self, lines: list[str]) -> None:
        async with self._memory_lock:
            await self.hass.async_add_executor_job(
                write_memory,
                self.memory_path,
                lines,
                self.memory_versions_dir,
                dt_util.utcnow(),
            )
            self.memory = list(lines)
        self.update_entities()

    async def async_add_memory(self, text: str) -> list[str]:
        """Add plain-language correction(s), exactly as written."""
        new = split_lines(text)
        if new:
            await self.async_set_memory([*self.memory, *new])
        return new

    async def compute_spoken(self, alerts: list[Mapping[str, Any]]) -> dict[str, Any]:
        """build_spoken() with a time limit, so a runaway regex can't hang us."""
        options = dict(self.options)
        if options.get(CONF_MESSAGE_MODE) != MODE_REGEX:
            return build_spoken(alerts, options)
        try:
            async with asyncio.timeout(TEXT_TIMEOUT):
                return await self.hass.async_add_executor_job(
                    build_spoken, alerts, options
                )
        except TimeoutError:
            _LOGGER.warning(
                "The regular expression took longer than %s s; spoke the fixed "
                "phrase instead. Simplify the pattern",
                TEXT_TIMEOUT,
            )
            outcome = OUTCOME_TIMEOUT
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Could not build the spoken text")
            outcome = OUTCOME_ERROR
        return {"text": self._fixed_phrase(), "outcome": outcome, "groups": {}}

    # -- history -----------------------------------------------------------------
    async def _write_history(self, rows: list[dict[str, Any]]) -> None:
        async with self._history_lock:
            try:
                await self.hass.async_add_executor_job(
                    append_history, self.history_path, rows
                )
            except OSError as err:
                _LOGGER.warning("Could not save alert history: %s", err)

    async def async_prune_history(self) -> None:
        async with self._history_lock:
            try:
                await self.hass.async_add_executor_job(
                    prune_history,
                    self.history_path,
                    self.history_days,
                    dt_util.utcnow(),
                )
            except OSError as err:
                _LOGGER.warning("Could not prune alert history: %s", err)

    async def get_history(
        self, days: int | None, limit: int, search: str | None
    ) -> list[dict[str, Any]]:
        return await self.hass.async_add_executor_job(
            read_history,
            self.history_path,
            self.history_days if days is None else days,
            limit,
            search,
            dt_util.utcnow(),
        )

    async def last_raw_alert(self) -> dict[str, Any] | None:
        """The last alert received; from history if HA restarted since."""
        if self._last_raw is not None:
            return dict(self._last_raw)
        rows = await self.get_history(0, 1, None)
        if rows:
            return {k: rows[0].get(k) for k in ("title", "message", "app", "priority")}
        return None

    async def _announce(
        self,
        text: str | None,
        emergency: bool,
        timings: dict[str, Any] | None = None,
        t0: float | None = None,
    ) -> None:
        # Right after start-up, give speakers a moment to load.
        settle_until = self._started_at + SPEAKER_SETTLE
        while time.monotonic() < settle_until and not self._speakers_ready():
            await asyncio.sleep(1)
        await self.speak(text or self._fixed_phrase(), timings=timings, t0=t0)
        if emergency and self.repeat_until_ack and self.pending_receipts:
            self._stop_repeats()
            self._ack_event.clear()
            self._repeat_task = self.entry.async_create_background_task(
                self.hass, self._repeat(), f"{DOMAIN}_repeat"
            )

    def _speakers_ready(self) -> bool:
        return bool(self.speakers) and all(
            (st := self.hass.states.get(s)) is not None and st.state not in _BAD_STATES
            for s in self.speakers
        )

    def _fixed_phrase(self) -> str:
        return build_text([], self.options)

    async def _repeat(self) -> None:
        interval = float(
            self.options.get(CONF_REPEAT_INTERVAL, DEFAULT_REPEAT_INTERVAL)
        )
        maximum = int(self.options.get(CONF_REPEAT_MAX, DEFAULT_REPEAT_MAX))
        text = self.options.get(CONF_EMERGENCY_MESSAGE) or DEFAULT_EMERGENCY_MESSAGE
        for _ in range(maximum):
            try:
                await asyncio.wait_for(self._ack_event.wait(), interval)
                return  # acknowledged
            except TimeoutError:
                pass
            if not (self.enabled and self.repeat_until_ack and self.pending_receipts):
                return
            await self.speak(text)

    def _stop_repeats(self) -> None:
        if self._repeat_task and not self._repeat_task.done():
            self._repeat_task.cancel()
        self._repeat_task = None

    async def acknowledge(self) -> None:
        """Acknowledge pending emergency alerts here and on Pushover."""
        receipts = self.pending_receipts
        self._ack_event.set()
        self._stop_repeats()
        self.hass.bus.async_fire(EVENT_ACK, {"receipts": receipts})
        failed = []
        for receipt in receipts:
            try:
                await self.listener.acknowledge(receipt)
            except api.SessionInvalid as err:
                # Expired / unknown receipt: nothing left to acknowledge.
                _LOGGER.info("Receipt %s no longer acknowledgeable: %s", receipt, err)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Acknowledge failed for %s: %s", receipt, err)
                failed.append(receipt)
                continue
            self._receipts.pop(receipt, None)
        self._save_receipts()
        self.update_entities()
        if failed:
            raise HomeAssistantError(
                f"Pushover acknowledge failed for {len(failed)} alert(s); try again"
            )

    # -- speaking ----------------------------------------------------------------
    async def speak(
        self,
        text: str,
        notify_on_failure: bool = True,
        timings: dict[str, Any] | None = None,
        t0: float | None = None,
    ) -> None:
        """Say `text` on every selected speaker at the configured volume.

        ``timings`` (if given) gets each step's time in ms since ``t0``.
        """
        mark = _Marks(timings, t0)
        async with self._speak_lock:
            mark("speak_start_ms")
            await self._speak(text, notify_on_failure, mark)
            self.update_entities()

    async def _speak(
        self, text: str, notify_on_failure: bool, mark: _Marks | None = None
    ) -> None:
        mark = mark or _Marks(None, None)
        ready, down = [], []
        for entity_id in self.speakers:
            state = self.hass.states.get(entity_id)
            bad = state is None or state.state in _BAD_STATES
            (down if bad else ready).append(entity_id)
        if down and notify_on_failure:
            await self._notify_fallback(
                f"{text} (speaker unavailable: {', '.join(down)})"
            )
        if not ready:
            if notify_on_failure and not down:
                await self._notify_fallback(f"{text} (no speakers selected)")
            return
        tts_entity = self.options.get(CONF_TTS_ENTITY)
        if not tts_entity:
            _LOGGER.error("No text-to-speech engine selected")
            if notify_on_failure:
                await self._notify_fallback(f"{text} (no text-to-speech engine)")
            return

        before = {s: self.hass.states.get(s) for s in ready}
        was_off = [s for s, st in before.items() if st and st.state == STATE_OFF]
        muted = [
            s for s, st in before.items() if st and st.attributes.get("is_volume_muted")
        ]
        previous: dict[str, float | None] = {}
        try:
            levels = await asyncio.gather(*(self._wake(s) for s in ready))
            previous = dict(zip(ready, levels, strict=True))
            for s in muted:
                await self._call(
                    "media_player", "volume_mute", s, is_volume_muted=False
                )
            for s in ready:
                await self._call(
                    "media_player",
                    "volume_set",
                    s,
                    volume_level=round(self.volume / 100, 2),
                )
            data: dict[str, Any] = {
                "media_player_entity_id": ready,
                "message": text,
                "cache": True,
            }
            if language := self.options.get(CONF_TTS_LANGUAGE):
                data["language"] = language
            started = time.monotonic()
            mark("tts_call_ms")
            async with asyncio.timeout(TTS_TIMEOUT):
                await self.hass.services.async_call(
                    "tts",
                    "speak",
                    data,
                    target={ATTR_ENTITY_ID: tts_entity},
                    blocking=True,
                )
            mark("tts_done_ms")
            self.last_spoken = text
            await self._wait_for_playback(ready, before, text, started, mark)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Announcement failed: %s", err)
            if notify_on_failure:
                await self._notify_fallback(f"{text} (speaker announcement failed)")
        finally:
            for s, level in previous.items():
                if level is not None:
                    await self._call(
                        "media_player", "volume_set", s, volume_level=level
                    )
            for s in muted:
                await self._call("media_player", "volume_mute", s, is_volume_muted=True)
            for s in was_off:
                await self._call("media_player", "turn_off", s)

    async def _call(
        self, domain: str, service: str, entity_id: str, **data: Any
    ) -> bool:
        try:
            async with asyncio.timeout(SERVICE_TIMEOUT):
                await self.hass.services.async_call(
                    domain, service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True
                )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("%s.%s failed for %s: %s", domain, service, entity_id, err)
            return False
        return True

    async def _wake(self, entity_id: str) -> float | None:
        """Return the speaker's current volume, waking it briefly if needed."""
        state = self.hass.states.get(entity_id)
        if state and (volume := state.attributes.get("volume_level")) is not None:
            return volume
        try:
            await self.hass.services.async_call(
                "media_player", "turn_on", {ATTR_ENTITY_ID: entity_id}, blocking=False
            )
        except Exception:  # noqa: BLE001
            return None
        for _ in range(WAKE_TIMEOUT * 4):
            await asyncio.sleep(0.25)
            state = self.hass.states.get(entity_id)
            if state and (volume := state.attributes.get("volume_level")) is not None:
                return volume
        _LOGGER.info("%s did not report its volume; it won't be restored", entity_id)
        return None

    async def _wait_for_playback(
        self,
        speakers: list[str],
        before: Mapping[str, Any],
        text: str,
        started: float,
        mark: _Marks | None = None,
    ) -> None:
        """Wait until our announcement has started and then finished."""
        mark = mark or _Marks(None, None)

        def ours_playing() -> bool:
            for s in speakers:
                st = self.hass.states.get(s)
                if st is None or st.state != STATE_PLAYING:
                    continue
                old = before.get(s)
                old_id = old.attributes.get("media_content_id") if old else None
                if st.attributes.get("media_content_id") != old_id or (
                    old is None or old.state != STATE_PLAYING
                ):
                    return True
            return False

        loop = asyncio.get_running_loop()
        deadline = loop.time() + PLAYBACK_START_TIMEOUT
        while not ours_playing() and loop.time() < deadline:
            await asyncio.sleep(0.25)
        if not ours_playing():
            return  # never saw it play (or a speaker that doesn't report it)
        mark("playback_start_ms")
        # ~15 characters per second of speech, plus margin.
        deadline = loop.time() + max(PLAYBACK_END_TIMEOUT, len(text) / 12 + 20)
        while ours_playing() and loop.time() < deadline:
            await asyncio.sleep(0.25)
        mark("playback_end_ms")

    # -- fallback notification ---------------------------------------------------
    async def _notify_fallback(self, message: str) -> None:
        service = (self.options.get(CONF_FALLBACK_NOTIFY) or "").strip()
        if not service:
            return
        domain, _, name = service.partition(".")
        if domain != "notify" or not name:
            _LOGGER.warning("Fallback notify action %r is not notify.<name>", service)
            return
        payload: dict[str, Any] = {"title": "Push Alert TTS", "message": message}
        if name.startswith("mobile_app_"):
            # Break through iOS Focus / Do Not Disturb where allowed.
            payload["data"] = {"push": {"interruption-level": "time-sensitive"}}
        try:
            async with asyncio.timeout(SERVICE_TIMEOUT):
                await self.hass.services.async_call(
                    "notify", name, payload, blocking=True
                )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Fallback notification via %s failed: %s", service, err)
