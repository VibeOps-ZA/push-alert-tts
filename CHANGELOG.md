# Changelog

All notable changes to **Push Alert TTS**.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.4.0] - 2026-10-16

### Added
- **Expand common abbreviations** option (off by default): speaks common IT
  shorthand in full, e.g. `prod` production, `db01` database 01, `lb`
  load balancer. Whole words only; the full list is in the README.
- **Remove repeated words** option for the spoken template (on by default):
  words an earlier part already said are left out, e.g. "integration momo
  mtn" after "za mtn momo hr" is spoken as "integration".

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
