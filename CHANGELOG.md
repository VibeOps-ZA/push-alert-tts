# Changelog

All notable changes to **Push Alert TTS**.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
