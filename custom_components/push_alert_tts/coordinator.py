"""Runtime for Push Alert TTS: decides what to say and where, and says it."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import OrderedDict
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
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import api
from .client import STATUS_LOGIN_REQUIRED, STATUS_STOPPED, PushoverListener
from .const import (
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
from .text import (
    OUTCOME_ERROR,
    OUTCOME_TIMEOUT,
    build_spoken,
    build_text,
    clean,
    should_announce,
)

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
) -> dict[str, Any]:
    """One line of the history file (the raw alert, length-capped)."""
    sent = api.as_int(msg.get("date"))
    return {
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
        "queued": queued,
        "announced": announced,
        "spoken_text": spoken_text,
    }


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
            self._process(fresh, wanted, queued, self.enabled),
            f"{DOMAIN}_process",
        )

    async def _process(
        self, fresh: list[dict], wanted: list[dict], queued: bool, enabled: bool
    ) -> None:
        async with self._alert_lock:
            try:
                await self._process_locked(fresh, wanted, queued, enabled)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Failed to process Pushover alerts")
                if enabled and wanted:
                    self.entry.async_create_background_task(
                        self.hass, self._announce(None, False), f"{DOMAIN}_announce"
                    )

    async def _process_locked(
        self, fresh: list[dict], wanted: list[dict], queued: bool, enabled: bool
    ) -> None:
        last = fresh[-1]
        top = max(api.as_int(m.get("priority")) for m in fresh)
        spoken = await self.compute_spoken(wanted) if wanted else None
        text = spoken["text"] if spoken else None
        announce = bool(wanted) and enabled
        received = dt_util.utcnow()

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
        }
        self.last_alert_time = received
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
                "messages": [{k: m.get(k) for k in MESSAGE_FIELDS} for m in fresh],
            },
        )
        self.update_entities()

        if announce:
            emergency = any(api.as_int(m.get("priority")) >= 2 for m in wanted)
            self.entry.async_create_background_task(
                self.hass, self._announce(text, emergency), f"{DOMAIN}_announce"
            )

        if self.history_days:
            wanted_ids = {id(m) for m in wanted}
            rows = [
                history_record(
                    m,
                    received,
                    queued=queued,
                    announced=announce and id(m) in wanted_ids,
                    spoken_text=text if id(m) in wanted_ids else None,
                )
                for m in fresh
            ]
            await self._write_history(rows)

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

    async def _announce(self, text: str | None, emergency: bool) -> None:
        # Right after start-up, give speakers a moment to load.
        settle_until = self._started_at + SPEAKER_SETTLE
        while time.monotonic() < settle_until and not self._speakers_ready():
            await asyncio.sleep(1)
        await self.speak(text or self._fixed_phrase())
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
    async def speak(self, text: str, notify_on_failure: bool = True) -> None:
        """Say `text` on every selected speaker at the configured volume."""
        async with self._speak_lock:
            await self._speak(text, notify_on_failure)
            self.update_entities()

    async def _speak(self, text: str, notify_on_failure: bool) -> None:
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
            async with asyncio.timeout(TTS_TIMEOUT):
                await self.hass.services.async_call(
                    "tts",
                    "speak",
                    data,
                    target={ATTR_ENTITY_ID: tts_entity},
                    blocking=True,
                )
            self.last_spoken = text
            await self._wait_for_playback(ready, before, text, started)
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
    ) -> None:
        """Wait until our announcement has started and then finished."""

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
        # ~15 characters per second of speech, plus margin.
        deadline = loop.time() + max(PLAYBACK_END_TIMEOUT, len(text) / 12 + 20)
        while ours_playing() and loop.time() < deadline:
            await asyncio.sleep(0.25)

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
