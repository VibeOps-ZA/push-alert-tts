"""Combine alerts: one speaker session, one announcement for alerts that arrive together.

With "Combine alerts" on, everything to be said goes into a queue. One worker
wakes the speakers and sets the volume once, says what is queued, then says
anything that arrived meanwhile ("2 more alerts have arrived ..."), and only
puts the speakers back once nothing more has come in for a while. Several
alerts are joined into one audio file with exact pauses, so the speakers get
one thing to play (one connect sound at most).

Must-hear speakers are checked after each announcement; one that didn't play
gets it again on its own ("Missed alert TTS: ..."), and if it still didn't,
each alert is sent as a phone notification (with its link) instead.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.components import persistent_notification

from . import api, audio
from .const import (
    BACKUP_HEAD_START,
    DOMAIN,
    PAUSE_AFTER_ALERT,
    PAUSE_AFTER_HEADING,
    SPOOL_FILES_KEPT,
    STITCH_TIMEOUT,
)

if TYPE_CHECKING:
    from .coordinator import AlertTTS

_LOGGER = logging.getLogger(__name__)

VOICE_MAIN = "main"
VOICE_BACKUP = "backup"
VOICE_CLIP = "clip"
PLAY_OK = "ok"
MISSED_PREFIX = "Missed alert TTS:"
_ORDINALS = (
    "First",
    "Second",
    "Third",
    "Fourth",
    "Fifth",
    "Sixth",
    "Seventh",
    "Eighth",
    "Ninth",
    "Tenth",
)
_LEADING_ALERT = re.compile(r"^\s*alert\s*[,:.\-]\s*", re.IGNORECASE)


def ordinal(index: int) -> str:
    """0 -> 'First', ... 9 -> 'Tenth', then 'Number 11'."""
    return _ORDINALS[index] if index < len(_ORDINALS) else f"Number {index + 1}"


def strip_leading_alert(text: str) -> str:
    """'Alert, disk, db1' -> 'disk, db1' (the heading already says alert)."""
    stripped = _LEADING_ALERT.sub("", text, count=1).strip()
    return stripped or text


def build_segments(texts: list[str], more: bool) -> list[str | float]:
    """What to say for these alerts: text parts and pauses (seconds).

    One new alert is said as it is. Otherwise a heading with the count,
    then each alert numbered, with pauses between.
    """
    count = len(texts)
    if count == 1 and not more:
        return [texts[0]]
    if more:
        heading = (
            "1 more alert has arrived."
            if count == 1
            else f"{count} more alerts have arrived."
        )
    else:
        heading = f"{count} alerts have arrived."
    out: list[str | float] = [heading, PAUSE_AFTER_HEADING]
    if count == 1:
        return [*out, strip_leading_alert(texts[0]), PAUSE_AFTER_ALERT]
    for index, text in enumerate(texts):
        out += [
            f"{ordinal(index)} alert:",
            PAUSE_AFTER_HEADING,
            strip_leading_alert(text),
            PAUSE_AFTER_ALERT,
        ]
    return out


def segments_text(segments: list[str | float]) -> str:
    """The segments as one line of text (for the history and length checks)."""
    return " ".join(s for s in segments if isinstance(s, str))


_URL = r"(https?://[^\s<>\"')\]]+)"


def find_link(msg: Mapping[str, Any], label: str) -> str | None:
    """The link after `label` in the alert's message (e.g. 'Monitor Status <url>').

    Falls back to the Pushover link of the alert if that is a web link.
    An empty label uses only the Pushover link.
    """
    message = str(msg.get("message") or "")
    if label:
        pattern = rf"{re.escape(label)}\s*[:\-]?\s*<?\s*{_URL}"
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return match.group(1)
    url = str(msg.get("url") or "")
    return url if re.match(r"^https?://", url) else None


class _FanMarks:
    """Records step times into every alert's timings (each from its own start)."""

    def __init__(self, targets: list[tuple[dict[str, Any] | None, float | None]]):
        self.targets = [(t, t0) for t, t0 in targets if t is not None]

    def __call__(self, key: str) -> None:
        now = time.monotonic()
        for timings, t0 in self.targets:
            if t0 is not None:
                timings[key] = int((now - t0) * 1000)

    def note(self, key: str, value: Any) -> None:
        for timings, _t0 in self.targets:
            timings[key] = value


@dataclass
class SpoolItem:
    """Something to say. Alerts are combined; plain items are said alone."""

    text: str
    emergency: bool = False
    rows: list[dict[str, Any]] = field(default_factory=list)  # history rows
    timings: dict[str, Any] | None = None
    t0: float | None = None
    link: str | None = None
    title: str | None = None
    plain: bool = False
    notify_on_failure: bool = True
    done: asyncio.Future | None = None


@dataclass
class _Audio:
    """Ready audio for one announcement."""

    media: str | None
    voice: str | None
    text: str
    parts: list[tuple[bytes, str] | float] | None = None  # joined parts, if joined
    engine: str | None = None


class AlertSpool:
    """The queue and the worker that speaks it (see the module docstring)."""

    def __init__(self, runtime: AlertTTS) -> None:
        self.runtime = runtime
        self.hass = runtime.hass
        self.queue: list[SpoolItem] = []
        self._added = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._file_index = 0
        self.folder = runtime.hass.config.path(DOMAIN, "spool")

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def add(self, item: SpoolItem) -> None:
        self.queue.append(item)
        self._added.set()
        if not self.busy:
            self._start()

    async def say(
        self,
        text: str,
        notify_on_failure: bool = True,
        timings: dict[str, Any] | None = None,
        t0: float | None = None,
    ) -> None:
        """Say plain text through the session and wait until it was said."""
        done = asyncio.get_running_loop().create_future()
        self.add(
            SpoolItem(
                text=text,
                plain=True,
                notify_on_failure=notify_on_failure,
                timings=timings,
                t0=t0,
                done=done,
            )
        )
        await done

    def _start(self) -> None:
        self._task = self.runtime.entry.async_create_background_task(
            self.hass, self._run(), f"{DOMAIN}_spool"
        )

    def _take(self) -> list[SpoolItem]:
        items, self.queue = self.queue, []
        # Plain items first (in order), then emergencies, then the rest.
        return sorted(items, key=lambda i: (not i.plain, not i.emergency))

    async def _run(self) -> None:
        runtime = self.runtime
        restore: dict[str, Any] | None = None
        try:
            async with runtime._speak_lock:  # noqa: SLF001 - the speakers are ours
                fresh = True  # next round is a new announcement (not "more")
                while not runtime._stopping:  # noqa: SLF001
                    if not self.queue:
                        stay = runtime.stay_connected
                        if restore is None or stay <= 0:
                            break
                        self._added.clear()
                        try:
                            async with asyncio.timeout(stay):
                                await self._added.wait()
                        except TimeoutError:
                            break
                        fresh = True
                        continue
                    if fresh and not any(i.emergency for i in self.queue):
                        gather = runtime.gather_seconds
                        if gather:
                            await asyncio.sleep(gather)  # alerts arriving together
                    items = self._take()
                    if restore is None:
                        restore = await self._open(items)
                    await self._round(items, more=not fresh)
                    fresh = False
        except Exception:  # noqa: BLE001 - never lose what was queued
            _LOGGER.exception("Combined announcements failed; using the simple way")
        finally:
            if restore is not None:
                try:
                    await runtime._restore_speakers(restore)  # noqa: SLF001
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Putting the speakers back failed")
            runtime.update_entities()
            if self.queue and not runtime._stopping:  # noqa: SLF001
                # Arrived while finishing (or after an error): speak them.
                self._start()

    async def _open(self, items: list[SpoolItem]) -> dict[str, Any]:
        """Wake the speakers and set the volume once for the session."""
        runtime = self.runtime
        mark = _FanMarks([(i.timings, i.t0) for i in items])
        mark("speak_start_ms")
        group, group_ok, ready, _down = runtime._targets()  # noqa: SLF001
        if not ready:
            return {}
        try:
            return await runtime._open_speakers(  # noqa: SLF001
                ready, mark, group if group_ok else None
            )
        except Exception:  # noqa: BLE001 - speaking still wakes them
            _LOGGER.exception("Readying the speakers failed")
            return {}

    async def _round(self, items: list[SpoolItem], more: bool) -> None:
        plain = [i for i in items if i.plain]
        alerts = [i for i in items if not i.plain]
        for item in plain:
            try:
                await self._speak_plain(item)
            finally:
                if item.done is not None and not item.done.done():
                    item.done.set_result(None)
        if alerts:
            await self._speak_alerts(alerts, more)

    async def _speak_plain(self, item: SpoolItem) -> None:
        runtime = self.runtime
        mark = _FanMarks([(item.timings, item.t0)])
        target = await runtime._check_targets(  # noqa: SLF001
            item.text, item.notify_on_failure
        )
        if target is None:
            return
        group, ready, _engine = target
        try:
            await runtime._play_text(  # noqa: SLF001
                item.text, item.notify_on_failure, mark, group, ready
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Announcement failed: %s", err)
            if item.notify_on_failure:
                await runtime._notify_fallback(  # noqa: SLF001
                    f"{item.text} (speaker announcement failed)"
                )

    # -- alerts -------------------------------------------------------------------
    async def _speak_alerts(self, alerts: list[SpoolItem], more: bool) -> None:
        runtime = self.runtime
        mark = _FanMarks([(a.timings, a.t0) for a in alerts])
        mark.note("batch_size", len(alerts))
        mark.note("batch_more", more)
        for index, alert in enumerate(alerts):
            if alert.timings is not None:
                alert.timings["batch_position"] = index + 1
        segments = build_segments([a.text for a in alerts], more)
        must = runtime.must_hear()
        missed: list[str] = []
        outcome = None
        try:
            target = await runtime._check_targets(  # noqa: SLF001
                segments_text(segments), notify_on_failure=not must
            )
            if target is None:
                missed = list(must)
            else:
                group, ready, _engine = target
                made = await self._make_audio(segments, mark)
                seen: set[str] = set()
                outcome = await runtime._play_text(  # noqa: SLF001
                    made.text,
                    not must,  # with must-hear speakers, the check below warns
                    mark,
                    group,
                    ready,
                    media=made.media,
                    voice=made.voice,
                    seen=seen,
                    watch=must,
                )
                runtime.last_spoken = made.text
                if made.voice == VOICE_CLIP and must:
                    # Only the recorded fixed phrase could be played: send the
                    # details (without must-hear speakers, _play_text did).
                    for alert in alerts:
                        await runtime._notify_fallback(  # noqa: SLF001
                            f"{alert.text} (no voice could be used; the recorded "
                            "phrase was played)",
                            link=alert.link,
                        )
                missed = [s for s in must if s not in seen]
                if missed and made.media is not None:
                    missed = await self._replay_missed(made, missed, mark)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Combined announcement failed: %s", err)
            missed = list(must)
            if not must:
                for alert in alerts:
                    await runtime._notify_fallback(  # noqa: SLF001
                        f"{alert.text} (speaker announcement failed)", link=alert.link
                    )
        mark.note("missed_speakers", missed)
        if missed:
            await self._notify_missed(alerts, missed)
        for alert in alerts:
            for row in alert.rows:
                row["announced"] = True
                row.setdefault("spoken_text", alert.text)
        await runtime._record([r for a in alerts for r in a.rows])  # noqa: SLF001
        if outcome is not None:
            mark.note("outcome", outcome)
        if any(a.emergency for a in alerts):
            runtime.start_repeats()
        runtime.update_entities()

    async def _make_audio(self, segments: list[str | float], mark: Any) -> _Audio:
        """Audio for the segments: joined with pauses, else one plain text."""
        runtime = self.runtime
        text = segments_text(segments)
        texts = [s for s in segments if isinstance(s, str)]
        if len(segments) == 1:
            voices = runtime.new_voices(text, mark)
            voices.start()
            try:
                media, voice = await voices.first()
            finally:
                voices.stop()
            return _Audio(media, voice, text)
        voice_sets = [runtime.new_voices(t, _FanMarks([])) for t in texts]
        try:
            for voices in voice_sets:
                voices.start()
            mains = [v._task(VOICE_MAIN) for v in voice_sets]  # noqa: SLF001
            _done, pending = await asyncio.wait(mains, timeout=BACKUP_HEAD_START)
            if pending:
                for voices in voice_sets:
                    voices.start_backup()  # slow today: have the backup ready
            chosen = None
            if all(await asyncio.gather(*(v.made(VOICE_MAIN) for v in voice_sets))):
                chosen = VOICE_MAIN
            elif all(await asyncio.gather(*(v.made(VOICE_BACKUP) for v in voice_sets))):
                chosen = VOICE_BACKUP
            if chosen is not None:
                parts: list[tuple[bytes, str] | float] = []
                pieces = iter(voice_sets)
                for seg in segments:
                    parts.append(
                        seg if isinstance(seg, float) else next(pieces).data[chosen]
                    )
                engine = (
                    voice_sets[0].main if chosen == VOICE_MAIN else voice_sets[0].backup
                )
                try:
                    media = await self._join(parts, engine)
                    mark("audio_ready_ms")
                    mark.note("voice", chosen)
                    mark.note("joined", True)
                    return _Audio(media, chosen, text, parts, engine)
                except Exception as err:  # noqa: BLE001 - say it as one text
                    _LOGGER.warning(
                        "Joining the alerts failed (%s); saying them as one text", err
                    )
            else:
                _LOGGER.warning(
                    "Not every part could be voiced; saying them as one text"
                )
        finally:
            for voices in voice_sets:
                voices.stop()
        mark.note("joined", False)
        voices = runtime.new_voices(text, mark)
        voices.start()
        try:
            media, voice = await voices.first()
        finally:
            voices.stop()
        return _Audio(media, voice, text)

    async def _join(
        self, parts: list[tuple[bytes, str] | float], engine: str | None
    ) -> str:
        """Join the parts into one file and return a media id that plays it."""
        if not engine:
            raise RuntimeError("no voice to play the joined audio through")
        self._file_index = (self._file_index + 1) % SPOOL_FILES_KEPT
        path = os.path.join(self.folder, f"announcement_{self._file_index}.mp3")
        await audio.stitch(self.hass, parts, path, STITCH_TIMEOUT)
        return audio.clip_media_id(self.hass, engine, path)

    async def _replay_missed(
        self, made: _Audio, missed: list[str], mark: Any
    ) -> list[str]:
        """Play it again on must-hear speakers that didn't play it. Returns still missed."""
        runtime = self.runtime
        ready = [
            s
            for s in missed
            if (st := self.hass.states.get(s)) is not None
            and st.state not in ("unavailable", "unknown")
        ]
        if not ready:
            return missed
        _LOGGER.warning("Not heard on %s; saying it there again", ", ".join(ready))
        replay = await self._missed_audio(made, mark)
        if replay.media is None:
            return missed
        tries = max(1, runtime.announce_retries)
        still = list(ready)
        for _ in range(tries):
            seen: set[str] = set()
            try:
                await runtime._attempt(  # noqa: SLF001
                    "speakers",
                    replay.media,
                    None,
                    still,
                    replay.text,
                    mark,
                    seen=seen,
                    watch=still,
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Replaying on %s failed: %s", ", ".join(still), err)
            still = [s for s in still if s not in seen]
            if not still:
                break
        mark.note("missed_replayed", ready)
        return [s for s in missed if s not in ready] + still

    async def _missed_audio(self, made: _Audio, mark: Any) -> _Audio:
        """'Missed alert TTS:' then what was said."""
        runtime = self.runtime
        text = f"{MISSED_PREFIX} {made.text}"
        if made.parts and made.engine:
            voices = runtime.new_voices(MISSED_PREFIX, _FanMarks([]))
            voices.start()
            try:
                if made.voice == VOICE_BACKUP:
                    voices.start_backup()
                if await voices.made(made.voice or VOICE_MAIN):
                    prefix = voices.data[made.voice or VOICE_MAIN]
                    parts = [prefix, PAUSE_AFTER_HEADING, *made.parts]
                    media = await self._join(parts, made.engine)
                    return _Audio(media, made.voice, text, parts, made.engine)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Joining the missed-alert audio failed: %s", err)
            finally:
                voices.stop()
        voices = runtime.new_voices(text, mark)
        voices.start()
        try:
            media, voice = await voices.first()
        finally:
            voices.stop()
        return _Audio(media, voice, text)

    async def _notify_missed(self, alerts: list[SpoolItem], missed: list[str]) -> None:
        """Each alert as a phone (and optionally Home Assistant) notification."""
        runtime = self.runtime
        names = ", ".join(
            (st.name if (st := self.hass.states.get(s)) else s) for s in missed
        )
        title = f"Push Alert TTS - not heard on {names}"
        _LOGGER.warning("Alerts not heard on %s; sending notifications", names)
        for alert in alerts:
            await runtime._notify_fallback(  # noqa: SLF001
                alert.text, link=alert.link, title=title
            )
            if runtime.missed_bell:
                body = alert.text
                if alert.link:
                    body += f"\n\n[Open the monitor]({alert.link})"
                persistent_notification.async_create(
                    self.hass,
                    body,
                    title=title,
                    notification_id=f"{DOMAIN}_missed_{api.as_int(time.time() * 1000)}",
                )
