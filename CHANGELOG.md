# Changelog

All notable changes to **Push Alert TTS**.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.13.1] - 2026-11-11

### Fixed
- **Speakers dinging several times, one after another, for every alert.** With a *Speaker group*, each speaker was
  woken on its own (a connect sound each, a few seconds apart), then connected again when the group played (another
  sound each), and switched off one by one afterwards. Now only the group is woken, once, so every speaker connects
  at the same moment with at most one sound; the volume is set after the group is up (only where it differs), and a
  group that was off is switched off once at the end. Speakers are still woken on their own only without a group,
  when the group fails (fallback), or for a must-hear speaker that missed an alert.

### Changed
- *Connect the speaker group early* now only decides when the group is woken (when an alert arrives, or when the
  announcement starts); the speakers are never woken one by one with a group.
- *Wait for speakers to wake up* applies only without a speaker group; with one, Push Alert TTS waits up to 10 s for
  the group's speakers to report in after waking it.

## [0.13.0] - 2026-11-10

### Added
- **Combine alerts** (new *Combining and delivery* section in the options, off by default). Everything to be said
  goes into one queue and one speaker session: the speakers are woken and set to the announcement volume once, alerts
  arriving together are said as one announcement made into a single audio file with exact pauses ("3 alerts have
  arrived." - "First alert:" - ...), alerts arriving while it speaks follow straight after ("2 more alerts have
  arrived ..."), and the speakers are put back only after *Keep the speakers ready for* (default 60 s) with nothing
  new. One alert on its own is said as before. Emergencies go first and never wait. The test button, emergency
  repeats and other messages share the session. Joining uses ffmpeg; if that fails the same words are said as one
  text. New settings: *Wait for more alerts* (default 3 s), *Keep the speakers ready for*.
- **Must-hear speakers**: after each announcement, each must-hear speaker is checked; one that didn't play it hears
  it again on its own ("Missed alert TTS: ..."), up to *Retries* times; if it still didn't, each alert is sent to the
  fallback notification ("not heard on ...") with its link. Optional night list and *Night condition* (a template;
  errors count as day). Optional *Also show missed alerts in Home Assistant* (persistent notification).
- **Alert links**: the link after *Link label* (default "Monitor Status") in the alert's message (else the alert's
  web link) is saved in the history (`link`), sent with notifications (opens when tapped in the Companion app, never
  spoken), included in the `push_alert_tts_alert` event and the AI review data, and shown on the review card (the
  wording becomes a link).
- **Main voice tries**: *Main voice: time per try* (default 20 s, was a fixed 8 s) and *Main voice: extra tries*
  (default 3) before the backup voice is used.
- *Backup voice name* (for example `en_GB-cori-high` for Piper) and *Backup voice: wait at most* (default 120 s, was
  a fixed 20 s), for slow local voices.
- **Voice with backup** text-to-speech entity: the main voice with its tries, falling back to the backup voice, for
  use in any automation (`tts.speak`).
- Timings record `main_voice_tries`, `batch_size`, `batch_position`, `batch_more`, `joined` and `missed_speakers`.

### Changed
- The main voice is now preferred until it has used all its tries; the backup voice's audio is made alongside once
  the main voice fails a try or is slow (after 5 s), but only used when the main voice gives up (it was: first to
  finish wins).
- A speaker already at the announcement volume is no longer set again (Google speakers beep on every volume change),
  and only volumes that were changed are put back.
- The fixed phrase may take up to 120 s to record (slow local voices).
- With *Combine alerts* on, the `push_alert_tts_alert` event is fired once per alert as it is worded.

## [0.12.0] - 2026-11-10

### Added
- **Review card** (`custom:push-alert-tts-review-card`), loaded automatically with the integration: the AI review
  list as a table with an **Improve?** button per alert. Type a correction and press Send (or Enter): it is saved
  to the AI memory with the alert it is about, and the AI words that alert again so you can see the result.
  Nothing is spoken.
- `push_alert_tts.add_ai_correction` action: save a correction for one alert (by `received` time or `title`); the
  memory line gets "(about alerts like: <alert name>)"; optional re-wording returned as `new_wording`.
- **Word replacements for the normal text** option: `from = to` lines (e.g. `Re-Triggered = re alert`), whole words
  or phrases, any capitals. Applies to the normal (non-AI) spoken text only. Empty = off.
- The AI review list now includes each alert's `title`.

## [0.11.0] - 2026-11-10

### Fixed
- **Announcements failing when the voice service is slow or unreachable** (for example while the internet or DNS is
  struggling). The speakers were told to play before the audio existed, so they waited 30 seconds, gave up and made
  a wake-up sound on every try. Now the whole audio is made first, and only then are the speakers asked to play it.

### Added
- The *Backup text-to-speech engine* is also used when the main voice can't make the audio in time (8 seconds; the
  backup starts too after 3 seconds and the first to finish is used), not only for retries.
- **Recorded fixed phrase**: the *Fixed phrase* is recorded in advance (on start-up and when the phrase or voices
  change) and played when no voice can make the audio, so an alert is never silent while the speakers work. The full
  text is then sent to the phone notification.
- *Retries* can be set up to 5 (was 3).
- Timings record `audio_ready_ms`, `voice` (`main`, `backup` or `clip`) and `voice_failed`; `outcome` can be
  `no_audio`.

### Changed
- Each try plays once on one route: the group first; after a group failure (or no start) the next try uses each
  speaker, then the group again; a try that was cut short repeats its route. So each try makes at most one wake-up
  sound. With *Retries* at 0 a group that doesn't play still falls back to each speaker once, as before.
- A speaker gets 20 seconds to accept the ready audio (was 45 seconds for the whole text-to-speech call).

## [0.10.0] - 2026-11-10

### Added
- **Backup text-to-speech engine** (optional). Retries use it, so a problem with the main voice service can't stop the
  alert. Empty (the default) retries with the main voice, as before. *Language* applies to the main voice only.
- **Connect the speaker group early** (default off). Connects the speaker group while the alert is being worded, so the
  announcement starts about 3 seconds sooner. Off by default because some speakers play a connect sound.
- While the Pushover connection is down, new alerts are also collected over the Pushover API every 30 seconds.
- **Pushover connected** sensor: `drops`, `last_drop`, `last_drop_reason`, `polled_alerts`, `last_poll`,
  `keepalive_interval_s` and `dead_after_s` attributes. Each drop is logged as a warning.
- Timings record `prepared_ms`, `tts_used` and `group_preconnected`.

### Changed
- Speakers are woken while the alert is being worded (in the background), and volumes are set on all speakers at
  once, so announcements start sooner. Speakers that were off are still switched off again afterwards.
- A dead (silent) Pushover connection is found sooner: the keep-alive interval is measured and the connection counts
  as dead after 2.5 times the longest recent gap (45 to 120 seconds; before, always 120), then it reconnects after
  5 seconds instead of 15. When Pushover closes the connection it still waits 15 seconds, as Pushover asks.

## [0.9.1] - 2026-11-09

### Fixed
- **Wait for speakers to wake up** no longer waits for the speaker group. A Google Cast speaker group only comes on
  once something is played on it, so 0.9.0 waited the full time (10 seconds by default) before every announcement
  when the speakers had been off. Only the speakers in *Speakers* are waited for now.

## [0.9.0] - 2026-11-09

### Fixed
- **Announcements cut off after the first word.** A speaker (or speaker group) that briefly reported *buffering*
  in the middle of an announcement was taken as finished, and speakers that had been off were switched off again,
  cutting the alert short. *Buffering* now counts as playing, and an announcement only counts as finished once the
  speaker has stayed stopped for 2 seconds. Playback is followed through state changes as they happen, so even a
  very short burst of playing is seen.

### Added
- **Retries if an announcement fails or is cut short** (default 1, 0 = off). If the text-to-speech call fails, the
  speaker never starts playing, or it stops far sooner than the text needs, the alert is spoken again. If every try
  fails, the fallback notification is sent with the text and the reason. 0 keeps the earlier behaviour.
- **Wait for speakers to wake up** (default 10 seconds, 0 = off). Before speaking, waits until every speaker and the
  speaker group are on (speakers that were off, and groups, take a few seconds), then speaks anyway when the time
  is up.
- Timings record `awake_ms`, `awake_timeout`, `played_s`, `retry_ms`, `attempts`, `retry_reason` and `outcome`.

## [0.8.0] - 2026-11-09

### Added
- **Speaker group (plays in sync)** option. Set a speaker group (for example a Google Home speaker group) that
  contains your speakers, and announcements play on the group so every speaker starts at the same time instead of
  one after another. Volume is still set and restored on each speaker in *Speakers*. Empty (the default) keeps
  today's behaviour.
- Safe fallback: if the group is unavailable, the text-to-speech call fails or the group doesn't start playing
  within 10 seconds, the alert is spoken on each speaker as before. Emergencies use the same fallback.
- Timings record `route` (`group`, `group_fallback` or `speakers`) and `group_fallback_ms`.
- The options form rejects picking the group in *Speakers* as well.

## [0.7.0] - 2026-11-08

### Added
- **Wake the AI server with** (AI wording options): a button, input button or script pressed when the LLM server
  stops answering (for example a Wake-on-LAN button), at most once every 10 minutes while it stays down.
- **Backup LLM server**: *Backup LLM server address*, *Backup model* and *Use the backup only while* (an entity that
  must be on). Used only when the main server can't be reached, within the same time limit; if both fail, the
  normal text is spoken as before. History, preview and the AI review list record which server answered
  (`ai_server`: `main` or `backup`).
- `push_alert_tts.remove_ai_memory` removes an AI-memory line by number or exact text; `get_ai_memory` also returns
  the lines numbered.
- Entities: **AI reachable** (binary sensor) and **Re-word missed alerts** (button, same as `reprocess_ai`).
- The LLM server is also checked once at start-up, so *AI reachable* has a state straight away.

## [0.6.1] - 2026-11-08

### Added
- **Re-word missed alerts when the AI is back** (AI wording options, on by default). When the LLM server answers
  again after being unreachable, alerts that got the normal text meanwhile are worded by the AI for the AI review
  list, the same as running `push_alert_tts.reprocess_ai` (at least the last 3 days). Nothing is spoken.
- **Repair alert when the AI is unreachable for** (AI wording options, default 30 minutes, 0 = off). Raises a Home
  Assistant repair when the LLM server hasn't answered for that long; it clears itself when the server is back.
- While either option is on, the LLM server is checked every 5 minutes with a plain web request to its address
  (no model is loaded). Real alerts also update whether it is reachable.

### Changed
- Live alerts are unchanged: if the AI can't be reached, the normal text is still spoken straight away.

## [0.6.0] - 2026-11-08

### Added
- New action `push_alert_tts.reprocess_ai` (**Re-word past alerts with AI**). It asks the AI to word past alerts
  that got no AI text, for example while the AI was offline or when several alerts arrived at once, so they show
  up in the AI review list for checking and teaching. Nothing is spoken, and what was spoken at the time stays
  recorded. Options: `days` (default 3) and `limit` (default 100, up to 500). It runs one alert at a time, waits
  while a live alert is being worded or spoken, allows each alert at most 30 seconds, and stops if the AI can't
  be reached. It only runs when you call it.
- History rows re-worded this way gain `ai_backfilled`, `ai_backfill_time` and `ai_first_reason` (why no AI text
  was used at the time). The AI review sensor adds `backfilled` and keeps showing the original reason.

## [0.5.5] - 2026-11-06

### Fixed
- The device page showed version 0.5.3 for 0.5.4 (`const.VERSION` was not bumped). Now matches the manifest.

### Changed
- Import order sorted after the 0.5.4 rename (lint only; no behaviour change).

## [0.5.4] - 2026-11-06

### Fixed
- Home Assistant 2026.10+ logged `Error getting tools from LLM platform push_alert_tts` (`module ... has no attribute
  'async_get_tools'`). HA now treats any integration file named `llm.py` as an "LLM tools" platform for Assist. Push
  Alert TTS does not provide Assist tools; its `llm.py` was only the AI-wording helper, so it was renamed to
  `ai_wording.py`. No change to settings or behaviour.

## [0.5.3] - 2026-11-06

### Added
- AI wording, Ollama only: optional **GPU layers** (`num_gpu`) setting. With
  **Context size**, it lets alerts use the model exactly as other programs
  load it, so Ollama does not reload it (15-25 s) before an alert. Empty =
  Ollama decides, as before.

## [0.5.2] - 2026-11-06

### Changed
- Documentation, tests and the changelog use only generic example names;
  the options-form screenshot no longer shows a regional voice.

## [0.5.1] - 2026-11-06

### Added
- AI wording, Ollama only: optional **Context size** (`num_ctx`) and **Keep
  the model loaded for** (`keep_alive`) settings. Matching what other programs
  use for the same model stops Ollama reloading it (15-20 s) before an alert.
  Empty / 0 = the server's defaults, as before.

### Changed
- README and tests use a generic example name for the abbreviations example.

## [0.5.0] - 2026-11-06

### Added
- **AI wording** (optional, off by default): a local LLM you run yourself
  (Ollama, or any OpenAI-compatible server) words each alert as one short
  sentence. The alert is sent exactly as received, with your instructions and
  the AI memory. Settings in a new collapsible *AI wording* section: server
  type, address, model, optional API key, time limit (default 60 s),
  emergency time limit (default 5 s), maximum words, instructions and an
  optional "answer must start with" pattern.
- **Safe fallback**: the normal spoken text is always worked out first and is
  spoken whenever the AI is off, unreachable, too slow, or answers with
  nothing, too many words, symbols/links or the wrong shape. After a failed
  connection the AI is skipped for a minute. Several queued alerts keep the
  queued-alerts phrase.
- **AI memory**: plain-language corrections sent with every alert. Add them
  with the new **AI correction** text entity, the new
  `push_alert_tts.add_ai_memory` action or the settings; read them with
  `push_alert_tts.get_ai_memory`. Previous versions are kept (newest 20).
- **AI review** sensor: the alerts of the last 3 days (up to 50) with the
  alert as received and what was spoken (not saved in the recorder).
- History lines now also hold the alert's link, original message length, the
  normal text, the AI's answer and text, which was spoken and why, and step
  timings (Pushover delay, text, AI, TTS call, playback start/end). The same
  fields are attributes of the Last alert sensor.
- `push_alert_tts.preview` also asks the AI (option `use_ai`) and returns both
  texts.

### Changed
- History lines for announced alerts are written once the announcement has
  finished, so they include its timings.
- Internal: the spoken-text helpers moved from `text.py` to `spoken.py`
  (`text.py` is now the text entity platform).

## [0.4.0] - 2026-10-16

### Added
- **Expand common abbreviations** option (off by default): speaks common IT
  shorthand in full, e.g. `prod` production, `db01` database 01, `lb`
  load balancer. Whole words only; the full list is in the README.
- **Remove repeated words** option for the spoken template (on by default):
  words an earlier part already said are left out, e.g. "integration pay
  shop" after "eu shop pay hr" is spoken as "integration".

### Changed
- Existing spoken templates now leave out repeated words. Turn **Remove
  repeated words** off to keep the v0.3.0 behaviour.

## [0.3.0] - 2026-10-16

### Added
- **Spoken template** (regex mode): build a short sentence from your regex's
  named groups, e.g. `Alert, {s1}, {s2}, {state}`. Built-in placeholders
  `{app}`, `{priority}`, `{priority_name}`, `{title}`, `{message}` and numbered
  groups. Unknown placeholders are rejected when saving the options.
- **Where the regex looks**: message then title (as before), title then
  message, title only, or message only.
- **Maximum length of each template part** (default 40) and **Tidy text for
  speech** (default on: `_` and dots between words read as spaces, `|` as a
  pause, doubled or dangling commas removed).
- **Alert history** (off by default, up to 90 days): a small JSON-lines file
  in the config folder, pruned daily, capped at 20,000 alerts, deleted when
  turned off or when the integration is removed.
- Actions `push_alert_tts.get_history` (search saved alerts) and
  `push_alert_tts.preview` (show, and optionally speak, what an alert would
  sound like - including the last alert received - with the captured groups
  and the reason for any fallback).
- Last alert sensor attribute `spoken_outcome`.

### Changed
- Safety nets for spoken text: only the first 500 characters of the title and
  4,000 of the message are searched; a template less than half filled falls
  back to the fixed phrase; a regex taking over 2 seconds is abandoned (fixed
  phrase spoken, warning logged); spoken text never exceeds 2,000 characters
  even when the maximum length is 0.
- The spoken text is now worked out in the background (regex in a worker
  thread), so a slow pattern can't hold up Home Assistant or the Pushover
  connection.
- Tidy text is on by default, so existing title / whole-alert / regex setups
  now read underscores and dotted host names as words. Turn it off in the
  options to keep the old behaviour.

## [0.2.2] - 2026-10-09

### Changed
- New brand icon (phone alert to speaker) with a lighter dark-theme version.
- Licence changed from MIT to **GPL-3.0** for this and future versions.

### Docs
- README screenshots updated with the new icon.

## [0.2.1] - 2026-10-09

### Fixed
- HACS installs were missing the brand icon and showed a translation error under
  the regex option (v0.2.0 was tagged before those fixes).
- Device page shows the real version (`const.VERSION` now matches the manifest;
  a test keeps them in sync).

### Docs
- Dark-theme screenshots for each setup step (personal details masked) and an
  Acknowledgements section.

## [0.2.0] - 2026-10-09

### Added
- First release: unofficial Pushover Open Client for Home Assistant. Registers
  Home Assistant as its own Pushover device and announces incoming alerts via
  text-to-speech on chosen speakers - on/off switch, volume, message modes
  (fixed, title, full, regex extract), filters, emergency repeat/acknowledge,
  re-login handling, phone fallback, tests and HACS/hassfest CI.
