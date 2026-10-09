# Push Alert TTS

**Have your Pushover alerts spoken out loud on your Home Assistant speakers**
(Google/Nest speakers, Sonos, and any other speaker Home Assistant can play
text-to-speech on), with one switch to turn it on and off.

Typical use: you're on call, an alert arrives on Pushover in the middle of the
night, and you want the bedroom speaker to wake you as well as your phone.

> **Unofficial.** Push Alert TTS is an unofficial Pushover Open Client. It is
> not made, endorsed or supported by Pushover, LLC. Pushover® is a registered
> trademark of Pushover, LLC.

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=VibeOps-ZA&repository=push-alert-tts&category=integration)

---

## Contents

1. [How it works](#1-how-it-works)
2. [Before you start - checklist](#2-before-you-start---checklist)
3. [Step 1 - Install HACS](#3-step-1---install-hacs)
4. [Step 2 - Download Push Alert TTS](#4-step-2---download-push-alert-tts)
5. [Step 3 - Connect it to Pushover](#5-step-3---connect-it-to-pushover)
6. [Step 4 - Choose speakers and what to say](#6-step-4---choose-speakers-and-what-to-say)
7. [Step 5 - Test it](#7-step-5---test-it)
8. [Step 6 - Add it to a dashboard](#8-step-6---add-it-to-a-dashboard)
9. [What each entity does](#9-what-each-entity-does)
10. [Turning it on and off automatically (scheduling)](#10-turning-it-on-and-off-automatically-scheduling)
11. [Voice control (Google / Alexa / Assist)](#11-voice-control-google--alexa--assist)
12. [Emergency alerts, repeats and Acknowledge](#12-emergency-alerts-repeats-and-acknowledge)
13. [Login, passwords and security](#13-login-passwords-and-security)
14. [Advanced: automations, events and actions](#14-advanced-automations-events-and-actions)
15. [Troubleshooting](#15-troubleshooting)
16. [Updating and removing](#16-updating-and-removing)
17. [FAQ](#17-faq)

---

## 1. How it works

- Home Assistant logs in to Pushover **once** and adds itself as an extra
  device on your Pushover account, just like adding a second phone.
- From then on, every Pushover alert you receive is also sent to Home
  Assistant. **Your phone and computer keep getting every alert exactly as
  before.** Nothing is taken away from them.
- When an alert arrives and the **Push Alert TTS** switch is on, Home
  Assistant turns your chosen speakers up to the announce volume, speaks the
  alert, and then puts the volume back to what it was.
- If Home Assistant was restarting or offline when alerts arrived, they are
  collected as soon as it reconnects. If several arrived, it says "Multiple
  Pushover alerts recorded".
- Home Assistant connects **out** to Pushover. You don't need to open any
  ports or expose Home Assistant to the internet.

---

## 2. Before you start - checklist

Work through this list. Each item links to the official guide if you need to
set it up.

| # | You need | How to check / set it up |
|---|---|---|
| 1 | **Home Assistant 2025.6 or newer** | Check under **Settings → About**. New to Home Assistant? Start at [Installation](https://www.home-assistant.io/installation/) and [Getting started](https://www.home-assistant.io/getting-started/). To update: [Updating Home Assistant](https://www.home-assistant.io/common-tasks/general/). |
| 2 | **An administrator login** to Home Assistant | Only admins can add integrations. See [Users](https://www.home-assistant.io/docs/authentication/). |
| 3 | **A speaker that Home Assistant can use** | Go to **Settings → Devices & services → Entities** and search for `media_player`. Google/Nest speakers usually appear automatically through [Google Cast](https://www.home-assistant.io/integrations/cast/). Sonos: [Sonos integration](https://www.home-assistant.io/integrations/sonos/). Others: search the [integrations list](https://www.home-assistant.io/integrations/). |
| 4 | **A text-to-speech (TTS) engine** | The free, easy option is [Google Translate text-to-speech](https://www.home-assistant.io/integrations/google_translate/). If you subscribe to [Home Assistant Cloud](https://www.nabucasa.com/), its [cloud voices](https://www.home-assistant.io/integrations/cloud/) work too. You can test it in **Settings → Developer tools → Actions**: choose *Text-to-speech (TTS): Speak*, pick your TTS engine and speaker, type "Hello", then **Perform action**. |
| 5 | **A Pushover account** with alerts already arriving on your phone | Sign up at [pushover.net](https://pushover.net/) and install the [iPhone/iPad](https://pushover.net/clients/ios) or [Android](https://pushover.net/clients/android) app. |
| 6 | **A Pushover for Desktop licence** | Pushover counts this integration as a *desktop* device. It's **free for 30 days**, then a **once-off US$4.99** per account, covering all your desktop devices. Buy it while logged in at [pushover.net/clients/desktop](https://pushover.net/clients/desktop). If you already use Pushover in a desktop web browser you may already own it. |
| 7 | **A free Pushover device slot** | Pushover allows 10 devices per account. Your devices are listed when you log in at [pushover.net](https://pushover.net/). |
| 8 | **HACS** (Home Assistant Community Store) | Used to download and update this integration. See [Step 1](#3-step-1---install-hacs). |
| 9 | *(Optional, recommended)* **The Home Assistant app on your phone** | Lets Push Alert TTS warn your phone if a speaker or the connection fails. Install from the [Companion app docs](https://companion.home-assistant.io/docs/getting_started/) and allow notifications. |
| 10 | *(Optional)* **Voice control** | For "Hey Google, turn on Push Alert TTS", see [section 11](#11-voice-control-google--alexa--assist). |

---

## 3. Step 1 - Install HACS

Skip this step if you already see **HACS** in your Home Assistant sidebar.

HACS is a free add-on store for community-made integrations like this one.
Follow the official guide, which has screenshots:

1. **Check the prerequisites:** [HACS prerequisites](https://hacs.xyz/docs/use/download/prerequisites/).
   You need a free [GitHub account](https://github.com/signup).
2. **Download HACS:** [Download HACS](https://hacs.xyz/docs/use/download/download/).
   - **Home Assistant OS** (most Raspberry Pi, Home Assistant Green/Yellow and
     virtual-machine installs): you add the HACS *app* and start it. The guide
     shows how.
   - **Container / Core installs:** you run a one-line script. The guide shows
     how.
3. **Restart Home Assistant:** **Settings → System →** power icon (top right)
   **→ Restart Home Assistant**.
4. **Set up HACS:** [Initial configuration](https://hacs.xyz/docs/use/configuration/basic/).
   In short: **Settings → Devices & services → + Add integration → HACS**,
   tick the boxes, then link it to GitHub using the code it shows you. Refresh
   your browser if HACS doesn't appear in the list.

When it's done, **HACS** appears in the left sidebar.

---

## 4. Step 2 - Download Push Alert TTS

### Option A - one click

Click this button. It opens your Home Assistant at the right place in HACS:

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=VibeOps-ZA&repository=push-alert-tts&category=integration)

The first time, it asks for your Home Assistant address, e.g.
`http://homeassistant.local:8123`. Then click **Download**, keep the latest
version, and click **Download** again. Continue at step 4 below.

### Option B - by hand

1. Open **HACS** from the sidebar.
2. Click the **three dots (⋮)** in the top-right corner → **Custom repositories**.
3. In **Repository**, paste `https://github.com/VibeOps-ZA/push-alert-tts`.
4. In **Type** (or *Category*), choose **Integration**, then click **Add**.
   ([HACS guide to custom repositories](https://hacs.xyz/docs/faq/custom_repositories/))

   <img src="https://raw.githubusercontent.com/VibeOps-ZA/push-alert-tts/main/docs/images/01-hacs-custom-repository.png" alt="HACS Custom repositories dialog with the repository URL and type Integration" width="300">
5. Close the dialog. Search HACS for **Push Alert TTS** and open it.

   <img src="https://raw.githubusercontent.com/VibeOps-ZA/push-alert-tts/main/docs/images/02-hacs-repository.png" alt="The Push Alert TTS page in HACS" width="700">
6. Click **Download** (bottom right), keep the latest version, then click **Download**.

   <img src="https://raw.githubusercontent.com/VibeOps-ZA/push-alert-tts/main/docs/images/03-hacs-download-dialog.png" alt="HACS download dialog" width="450">
7. **Restart Home Assistant** (**Settings → System →** power icon **→ Restart
   Home Assistant**). Home Assistant usually also shows a *Restart required*
   repair message you can click.

### Option C - without HACS (manual)

1. Download the latest release ZIP from the [Releases page](https://github.com/VibeOps-ZA/push-alert-tts/releases),
   or the code via **Code → Download ZIP**.
2. Copy the folder `custom_components/push_alert_tts` into your Home Assistant
   `config/custom_components/` folder. Create `custom_components` if it
   doesn't exist. To reach the config folder, use the
   File editor or Samba share app
   ([how to access your config files](https://www.home-assistant.io/common-tasks/os/#configuring-access-to-files)).
3. Restart Home Assistant.

You won't get automatic update notices with the manual method.

---

## 5. Step 3 - Connect it to Pushover

[![Open your Home Assistant instance and start setting up Push Alert TTS.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=push_alert_tts)

Or by hand: **Settings → Devices & services → + Add integration** (bottom
right) → search **Push Alert TTS**. If it isn't listed, refresh the browser
page. If it's still missing, Home Assistant hasn't been restarted since the
download.

<p><img src="https://raw.githubusercontent.com/VibeOps-ZA/push-alert-tts/main/docs/images/04-add-integration-search.png" alt="Searching for Push Alert TTS in Add integration" width="450"></p>

Fill in:

| Field | What to enter |
|---|---|
| **Pushover email** | The email you log in to pushover.net with. |
| **Pushover password** | Your Pushover password. It is used to log in once. Unless you tick the box below, it is then thrown away. |
| **Device name** | How Home Assistant will appear in your Pushover device list. Default `ha-alert-tts`. Letters, numbers, `_` and `-` only, up to 25 characters. Must be different from your other Pushover device names. |
| **Save password for automatic re-login** | Leave **off** unless you understand [section 13](#13-login-passwords-and-security). If on, the password is stored **in plain text** so the integration can log in again by itself. |

<p><img src="https://raw.githubusercontent.com/VibeOps-ZA/push-alert-tts/main/docs/images/05-login-form.png" alt="The Push Alert TTS login form" width="450"></p>

Click **Submit**.

- If your Pushover account uses **two-factor authentication**, you'll be asked
  for the 6-digit code from your authenticator app.
- You'll see **Success**. Pushover may notify you that a new device was added.
- A device called **Push Alert TTS** now appears under
  **Settings → Devices & services → Push Alert TTS**.

Nothing will be spoken yet. Next you choose the speakers.

---

## 6. Step 4 - Choose speakers and what to say

Go to **Settings → Devices & services → Push Alert TTS → ⚙ Configure** (the
cog, or **⋮ → Configure** on some versions). Every setting can be changed at
any time and takes effect immediately; nothing restarts.

<details>
<summary>Screenshot of the settings form</summary>

<p><img src="https://raw.githubusercontent.com/VibeOps-ZA/push-alert-tts/main/docs/images/06-options-form.png" alt="The Push Alert TTS settings form" width="420"></p>
</details>

The examples below use this sample alert:

> **Title:** `PROD: disk full`
> **Message:**
> ```
> Host web-01 /var at 98%
> Runbook: https://wiki.example.com/disk
> Triggered by Datadog monitor 1234
> ```
> **App:** `Datadog`  **Priority:** High (1)

### Speakers *(required)*

The speakers to announce on. Pick one or more. They all speak at the same time.
You can pick speaker groups (e.g. a Google Home speaker group) too.
Nothing is spoken until at least one speaker is chosen.

### Text-to-speech engine *(required)*

The voice to use, e.g. `tts.google_en_com` or *Home Assistant
Cloud*. See checklist item 4 if the list is empty.

### Language *(optional)*

Leave empty to use the engine's default. Otherwise enter a language code the
engine supports, e.g. `en-GB`, `en-US`, `en-AU`, `de`.
Each engine's documentation lists its codes, e.g.
[Google Translate](https://www.home-assistant.io/integrations/google_translate/)
or [Home Assistant Cloud](https://www.home-assistant.io/integrations/cloud/).

### What to say

| Choice | What is spoken for the sample alert | Good for |
|---|---|---|
| **Fixed phrase** *(default)* | "Pushover alert received, please check" | Waking you up without reading anything sensitive aloud. |
| **Alert title** | "PROD: disk full" | Short, informative alerts. |
| **Whole alert** | "PROD: disk full. Host web-01 /var at 98% Runbook: link Triggered by Datadog monitor 1234" (cut to the maximum length) | Short alerts where you want everything. |
| **Part of the message (regex)** | Whatever your pattern picks out, e.g. "Host web-01 /var at 98%" | Long alerts where only one part matters. See below. |

In every mode:
- Web links are spoken as "link", and HTML formatting is removed.
- If the title or regex produces nothing, the **fixed phrase** is spoken, so an
  alert is never silently skipped.
- If several alerts arrive at once (e.g. after an outage), the
  **phrase for several queued alerts** is spoken instead.

### Fixed phrase

The sentence used by *Fixed phrase* mode, and the fallback for the other modes.
Default: `Pushover alert received, please check`.

### Regular expression (only for "Part of the message")

A [regular expression](https://docs.python.org/3/howto/regex.html) ("regex")
is a search pattern. Push Alert TTS searches the **message** first, then the
**title**, and speaks:
1. the part in a group named `say`, written `(?P<say> ... )`, if your pattern
   has one, otherwise
2. the part in the first set of brackets `( ... )`, otherwise
3. everything the pattern matched.

Matching ignores upper/lower case, `^` and `$` match the start and end of each
line, and `.` also matches line breaks.

Ready-made patterns to copy:

| I want to hear… | Pattern | Result for the sample |
|---|---|---|
| Only the first line of the message | `^(?P<say>[^\n]+)` | "Host web-01 /var at 98%" |
| The word after "Host" | `Host:?\s*(?P<say>\S+)` | "web-01" |
| Everything before the first full stop | `^(?P<say>[^.]+)` | "Host web-01 /var at 98%" (up to the first `.`) |
| A line starting "Summary:" | `^Summary:\s*(?P<say>.+?)$` | *(no match → fixed phrase)* |
| Severity and the next word | `(?P<say>(?:CRITICAL\|WARNING\|ERROR)\s+\S+)` | *(no match → fixed phrase)* |
| A percentage | `(?P<say>\d+%)` | "98%" |

To build and test your own, paste a real alert into [regex101.com](https://regex101.com/),
choose the **Python** flavour on the left, and turn on the `i`, `m` and `s`
flags to match how Push Alert TTS searches. An invalid pattern is rejected
when you click Submit.

### Maximum spoken length

The most characters that will be spoken. Longer text is cut at a word
boundary. Default `200` (roughly 15 seconds of speech). `0` = no limit.

### Phrase for several queued alerts

Spoken when more than one alert arrives at the same moment, usually after Home
Assistant was restarting or offline. Default: `Multiple Pushover alerts recorded`.

### Phrase for emergency repeats

Spoken on each repeat of an unacknowledged emergency alert (see
[section 12](#12-emergency-alerts-repeats-and-acknowledge)). Default:
`Pushover emergency alert, please acknowledge`.

### Only these Pushover apps *(optional)*

Leave empty to announce alerts from **every** app. To limit it, list Pushover
application names separated by commas, e.g. `Datadog, Grafana`. Case doesn't
matter. The app name is shown with each alert in the Pushover phone app, and
under *Last alert → app* in Home Assistant after the first alert.

### Minimum priority

Alerts below this [Pushover priority](https://pushover.net/api#priority) are
not announced (they're still received and logged):

| Priority | Meaning in Pushover |
|---|---|
| Lowest (-2) | No notification at all on your phone |
| Low (-1) | Quiet notification, no sound |
| Normal (0) | Normal notification |
| High (1) | Bypasses your phone's Pushover quiet hours |
| Emergency (2) | Repeats on your phone until acknowledged |

Default: **Lowest (-2)**, meaning everything is announced.

### Phone / fallback notification *(optional, recommended)*

A notification action Push Alert TTS uses to warn you when something is wrong:
- a chosen speaker is unavailable when an alert arrives,
- the Pushover connection is down while the switch is on,
- Pushover needs you to log in again.

Pick your phone from the list, e.g. `notify.mobile_app_your_phone`. That
appears once the [Home Assistant Companion app](https://companion.home-assistant.io/docs/getting_started/)
is installed and logged in on your phone. On iPhone these warnings are sent as
*Time Sensitive*, so they can break through Focus modes if you allow it in iOS
settings. Any other `notify.*` action (e.g. email, Telegram) can be typed in too.

### Emergency repeat interval / Maximum emergency repeats

How often (in seconds) and how many times an unacknowledged emergency alert is
repeated on the speakers when **Repeat emergencies** is on. Defaults: `60`
seconds, `10` times.

### Warn when offline for

How long (in seconds) the Pushover connection must be down, while the switch is
on, before you're warned. Default `60`. Short drops are normal and reconnect
automatically; alerts sent meanwhile are collected after reconnecting.

---

## 7. Step 5 - Test it

1. Open **Settings → Devices & services → Push Alert TTS →** the **Push
   Alert TTS** device.
2. Turn on the **Push Alert TTS** switch.
3. Press **Test announcement** (under *Diagnostic*). Your speakers should say
   the fixed phrase.
4. Now test the whole path: log in at [pushover.net](https://pushover.net/),
   use the **send a notification** box on the main page, leave the device as
   **(all devices)**, type a message, and send. Within a few seconds your
   phone gets it and your speakers announce it. **Last alert** updates.

<p><img src="https://raw.githubusercontent.com/VibeOps-ZA/push-alert-tts/main/docs/images/07-device-page.png" alt="The Push Alert TTS device page with its controls and sensors" width="700"></p>

---

## 8. Step 6 - Add it to a dashboard

Using the visual editor:
1. Open a dashboard and click the **pencil** (top right) to edit. New to
   dashboards? See [Dashboards](https://www.home-assistant.io/dashboards/).
2. **+ Add card** → **By entity** → search `push alert tts` → tick the
   entities you want → **Continue** → **Add to dashboard**.

Example card (tile cards in a dashboard section):

<p><img src="https://raw.githubusercontent.com/VibeOps-ZA/push-alert-tts/main/docs/images/09-dashboard-card.png" alt="Example Push Alert TTS dashboard card" width="380"></p>

Or paste this card. Click **+ Add card → Manual** and replace the text:

```yaml
type: entities
title: Push Alert TTS
entities:
  - entity: switch.push_alert_tts
    name: Announce alerts
  - entity: number.push_alert_tts_announce_volume
  - entity: switch.push_alert_tts_repeat_emergencies
  - entity: button.push_alert_tts_acknowledge
  - entity: binary_sensor.push_alert_tts_pushover_connected
  - entity: sensor.push_alert_tts_last_alert
```

If you renamed anything, use the names shown on the device page instead.

---

## 9. What each entity does

| Entity (default ID) | What it does |
|---|---|
| **Push Alert TTS** `switch.push_alert_tts` | Main on/off. **Off** = alerts are still received and logged, just not spoken. Remembers its state across restarts. |
| **Announce volume** `number.push_alert_tts_announce_volume` | Volume used while speaking (0-100 %, default 60 %). The previous volume is put back afterwards. |
| **Repeat emergencies** `switch.push_alert_tts_repeat_emergencies` | Repeat *emergency-priority* alerts until acknowledged. |
| **Acknowledge** `button.push_alert_tts_acknowledge` | Acknowledge pending emergency alerts and stop repeats ([section 12](#12-emergency-alerts-repeats-and-acknowledge)). |
| **Test announcement** `button.push_alert_tts_test_announcement` | Speak the fixed phrase now. |
| **Pushover connected** `binary_sensor.push_alert_tts_pushover_connected` | Connected / Disconnected. Its *status* attribute is `connected`, `reconnecting`, `login_required` or `stopped`, and *last_error* says why. |
| **Last alert** `sensor.push_alert_tts_last_alert` | When the last alert arrived. Attributes: title, message, app, priority, count, queued, announced, spoken_text, pending_emergencies. |

About speakers:
- A **muted** speaker is unmuted for the announcement and muted again afterwards.
- A speaker that was **off** is turned off again afterwards.
- If a speaker can't report its current volume (rare), it is still set to the
  announce volume so you hear the alert, but its old volume can't be restored.

---

## 10. Turning it on and off automatically (scheduling)

The main switch is an ordinary Home Assistant switch, so you can control it the
same way as any light or plug. Pick one method.

### Method 1 - a weekly schedule (no code)

1. **Settings → Devices & services → Helpers → + Create helper → Schedule**.
   Name it e.g. `Standby hours` and drag on the calendar to mark when you're on
   call. ([Schedule helper docs](https://www.home-assistant.io/integrations/schedule/))
2. **Settings → Automations & scenes → + Create automation → Create new automation**.
3. **⋮ → Edit in YAML**, replace everything with the YAML below, and **Save**.

```yaml
alias: Push Alert TTS follows standby schedule
triggers:
  - trigger: state
    entity_id: schedule.standby_hours
    to: ["on", "off"]
actions:
  - action: "switch.turn_{{ trigger.to_state.state }}"
    target:
      entity_id: switch.push_alert_tts
mode: single
```

### Method 2 - fixed times every day

```yaml
alias: Push Alert TTS overnight
triggers:
  - trigger: time
    at: "22:00:00"
    id: "on"
  - trigger: time
    at: "06:30:00"
    id: "off"
actions:
  - action: "switch.turn_{{ trigger.id }}"
    target:
      entity_id: switch.push_alert_tts
mode: single
```

### Method 3 - an on-call calendar

If your rota is in a calendar connected to Home Assistant (e.g.
[Google Calendar](https://www.home-assistant.io/integrations/google/) or
[Local Calendar](https://www.home-assistant.io/integrations/local_calendar/)):

```yaml
alias: Push Alert TTS follows on-call calendar
triggers:
  - trigger: calendar
    event: start
    entity_id: calendar.on_call
    id: "on"
  - trigger: calendar
    event: end
    entity_id: calendar.on_call
    id: "off"
actions:
  - action: "switch.turn_{{ trigger.id }}"
    target:
      entity_id: switch.push_alert_tts
mode: single
```

New to automations? See [Automation basics](https://www.home-assistant.io/docs/automation/basics/)
and [Editing automations in YAML](https://www.home-assistant.io/docs/automation/editor/).

---

## 11. Voice control (Google / Alexa / Assist)

1. Make your voice assistant available to Home Assistant first:
   - **Google Assistant / Alexa** via
     [Home Assistant Cloud](https://www.nabucasa.com/) (easiest; see the
     [Home Assistant Cloud docs](https://www.home-assistant.io/integrations/cloud/)), or the
     free manual [Google Assistant](https://www.home-assistant.io/integrations/google_assistant/)
     setup.
   - **Assist** (Home Assistant's own voice): see [Assist](https://www.home-assistant.io/voice_control/).
2. Expose the entities: **Settings → Voice assistants → Expose → + Expose
   entities**, choose the assistant, tick **Push Alert TTS** and
   **Acknowledge**. ([Exposing entities](https://www.home-assistant.io/voice_control/voice_remote_expose_devices/))
3. Say:
   - "Hey Google, turn **on** / **off** Push Alert TTS"
   - "Hey Google, activate Acknowledge". Google treats buttons as scenes, so
     "activate" is required.

Want a different phrase? Give the entity a different name or an
[alias](https://www.home-assistant.io/voice_control/aliases/) in Home Assistant:
open the entity → **⚙ Settings → Voice assistants**. In this example the switch
also answers to "Standby mode" ("Hey Google, turn on standby mode").

<p><img src="https://raw.githubusercontent.com/VibeOps-ZA/push-alert-tts/main/docs/images/08-voice-assistants.png" alt="Voice assistant exposure and aliases for the Push Alert TTS switch" width="450"></p>

---

## 12. Emergency alerts, repeats and Acknowledge

Pushover's **emergency (priority 2)** alerts repeat on your phone until someone
acknowledges them.

- **Repeat emergencies** on: the speakers repeat the *emergency phrase* every
  *repeat interval* until the alert is acknowledged, the switch is turned off,
  or the *maximum repeats* is reached.
- **Acknowledge** button: tells Pushover the alert is acknowledged. Pushover
  then stops re-alerting on **every** device on your account (phone, computer
  and Home Assistant), and the speakers stop repeating.
- Acknowledged on your **phone** instead? Home Assistant sees that and stops
  repeating too.
- Pending emergencies are remembered across Home Assistant restarts, so
  Acknowledge still works afterwards.

Normal and high-priority alerts don't need acknowledging, and Pushover gives
third-party clients no way to clear them from your other devices.

---

## 13. Login, passwords and security

- **Default (recommended):** your password is used once at setup to get a
  Pushover session, then discarded. Pushover sessions don't normally expire.
- **If Pushover ever rejects the session:**
  - Home Assistant shows a **Re-authenticate** prompt under
    **Settings → Devices & services**, plus a notification.
  - If you set a phone/fallback notification, you also get a message there.
  - Click **Re-authenticate** and log in again. The same Pushover device is
    kept where possible.
- **Save password for automatic re-login:**
  - Lets the integration log in again by itself, without your help.
  - The password is stored **in plain text** in Home Assistant's
    `.storage/core.config_entries` file, and therefore in your
    [backups](https://www.home-assistant.io/common-tasks/general/).
    A password can't be hashed and still be used to log in.
  - It does **not** work with two-factor authentication, because a new code is
    needed each time.
  - To change this choice later, go to **Settings → Devices & services → Push
    Alert TTS → ⋮ → Reconfigure**, log in again, and tick or untick the box.
- **When logging in again doesn't help,** the cause is usually an expired
  Desktop licence, the device being deleted on pushover.net, or the device
  being logged in elsewhere. Push Alert TTS raises an item in
  [Repairs](https://www.home-assistant.io/integrations/repairs/)
  (**Settings → System → Repairs**) explaining why, and keeps retrying quietly
  in case it was temporary.
- **Diagnostics** downloads (device page → **⋮ → Download diagnostics**) hide
  your email, password, session and device ID.

---

## 14. Advanced: automations, events and actions

### Event: `push_alert_tts_alert`

Fired for **every** alert, whether or not it was spoken. Use it to do more than
speak, e.g. flash lights:

```yaml
alias: Flash bedroom light on high-priority Pushover alerts
triggers:
  - trigger: event
    event_type: push_alert_tts_alert
conditions:
  - condition: template
    value_template: "{{ trigger.event.data.highest_priority >= 1 }}"
actions:
  - action: light.turn_on
    target:
      entity_id: light.bedroom
    data:
      flash: long
```

The event data includes `count`, `queued`, `highest_priority`, `emergency`,
`title`, `message`, `app`, `announced`, `spoken_text`, and `messages` (the raw
Pushover fields).

### Event: `push_alert_tts_acknowledged`

Fired when alerts are acknowledged from Home Assistant.

### Actions

- `push_alert_tts.speak` says any text on the configured speakers at the
  announce volume. Handy for your own automations:

  ```yaml
  action: push_alert_tts.speak
  data:
    message: "The back door has been open for ten minutes"
  ```

- `push_alert_tts.acknowledge` does the same as pressing the Acknowledge button.

---

## 15. Troubleshooting

| Problem | What to check |
|---|---|
| **Push Alert TTS** isn't in the *Add integration* list | Restart Home Assistant after downloading, then hard-refresh the browser (Ctrl+F5 / Cmd+Shift+R). |
| "That device name is already used" | Choose another device name, or delete the old device at pushover.net. |
| "Pushover refused the device registration" | You may already have 10 devices. Remove one at pushover.net. |
| Phone gets the alert, speaker says nothing | 1) Is the **Push Alert TTS** switch on? 2) Did **Last alert** update? If **no**, the sender targets a specific device; it must send to *all devices* or include your Push Alert TTS device name. If **yes**, check *announced*/*spoken_text* on Last alert, press **Test announcement**, and check the speaker and TTS engine in Configure. 3) Is a minimum priority or app filter excluding it? |
| Test announcement is silent | Run the TTS test from checklist item 4. Check that the speaker isn't on another app or group, and that the volume slider isn't 0. |
| **Pushover connected** is off | Check your internet connection. The *last_error* attribute says why. It reconnects by itself; alerts sent meanwhile are collected afterwards. |
| *status* is `login_required` | Re-authenticate (see [section 13](#13-login-passwords-and-security)). |
| *status* is `stopped` | Read **Settings → System → Repairs**. Usually the Desktop licence (30-day trial ended) or the device was deleted or logged in elsewhere. Fix it, then **⋮ → Reload** on the integration. |
| Speaker stays loud after an announcement | It couldn't report its volume before speaking. Set the volume once in the speaker's own app. |
| Need help | Open an [issue](https://github.com/VibeOps-ZA/push-alert-tts/issues) and attach a diagnostics download (device page → ⋮ → Download diagnostics). Turn on debug logging via **⋮ → Enable debug logging**, reproduce, then turn it off to download the log. |

---

## 16. Updating and removing

- **Updating:** HACS shows an update under **Settings → Updates** (or in HACS)
  when a new version is released. Click **Update**, then restart Home Assistant.
- **Removing:**
  1. **Settings → Devices & services → Push Alert TTS → ⋮ → Delete**.
  2. In HACS, open Push Alert TTS → **⋮ → Remove**, then restart.
  3. Log in at [pushover.net](https://pushover.net/) and delete the device to
     free the slot.

---

## 17. FAQ

**Will my phone stop getting alerts?** No. Home Assistant is an *extra*
device; every device gets its own copy.

**Does it work when I'm away from home?** It announces on your home speakers
whenever Home Assistant is running. Turn the switch off when you're out, or
schedule it.

**Is my Pushover traffic sent anywhere else?** No. Home Assistant talks only to
Pushover's servers, and speech is handled by the TTS engine you choose. A cloud
TTS engine receives the text it speaks.

**Can it read only certain alerts?** Yes: use *Only these Pushover apps* and/or
*Minimum priority*.

**Does it need the Pushover API token or user key?** No. It logs in like the
Pushover apps do.

**What if my power or internet goes down?** Nothing at home can announce
anything then. Your phone remains your main alert. Use Pushover's own
*Critical Alerts* setting on your phone for emergencies.

---

## Acknowledgements

Push Alert TTS is original code; nothing was copied from other projects. It is
built on, or checked with, these public resources:

| Resource | Used for |
|---|---|
| [Pushover Open Client API](https://pushover.net/api/client) | The documented protocol for logging in, registering a device, receiving, deleting and acknowledging messages. |
| [Home Assistant developer docs](https://developers.home-assistant.io/) | Standard integration patterns (config and options flows, entities, Repairs, diagnostics). |
| [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component) | Test framework (development only, not shipped). |
| [home-assistant/actions](https://github.com/home-assistant/actions) (hassfest) and [hacs/action](https://github.com/hacs/action) | Automated validation on GitHub. |
| [HACS](https://hacs.xyz/) and [My Home Assistant](https://my.home-assistant.io/) | Installation docs and the one-click buttons in this README. |

The icon is original and drawn by [`scripts/make_icon.py`](scripts/make_icon.py).

---

## Licence and disclaimer

[MIT licence](LICENSE). This project uses Pushover's public
[Open Client API](https://pushover.net/api/client) and is not affiliated with
or supported by Pushover, LLC. Use it in line with Pushover's
[terms of service](https://pushover.net/terms).
