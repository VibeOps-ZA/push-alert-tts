"""Constants for Push Alert TTS (an unofficial Pushover Open Client)."""

from __future__ import annotations

DOMAIN = "push_alert_tts"
VERSION = "0.2.1"

# --- Pushover Open Client API -------------------------------------------------
API_BASE = "https://api.pushover.net/1"
LOGIN_URL = f"{API_BASE}/users/login.json"
DEVICES_URL = f"{API_BASE}/devices.json"
MESSAGES_URL = f"{API_BASE}/messages.json"
DELETE_URL = API_BASE + "/devices/{device_id}/update_highest_message.json"
ACK_URL = API_BASE + "/receipts/{receipt}/acknowledge.json"
WS_URL = "wss://client.pushover.net/push"
USER_AGENT = (
    f"push-alert-tts/{VERSION} (unofficial Pushover Open Client for Home Assistant)"
)

# --- Config entry data --------------------------------------------------------
CONF_SECRET = "secret"
CONF_DEVICE_ID = "device_id"
CONF_DEVICE_NAME = "device_name"
CONF_USER_KEY = "user_key"
CONF_TWOFA = "twofa"
CONF_STORE_PASSWORD = "store_password"
DEFAULT_DEVICE_NAME = "ha-alert-tts"

# --- Options -----------------------------------------------------------------
CONF_SPEAKERS = "speakers"
CONF_TTS_ENTITY = "tts_entity"
CONF_TTS_LANGUAGE = "tts_language"
CONF_MESSAGE_MODE = "message_mode"
CONF_FIXED_MESSAGE = "fixed_message"
CONF_MULTIPLE_MESSAGE = "multiple_message"
CONF_EMERGENCY_MESSAGE = "emergency_message"
CONF_REGEX = "regex"
CONF_MAX_LENGTH = "max_length"
CONF_APP_FILTER = "app_filter"
CONF_MIN_PRIORITY = "min_priority"
CONF_FALLBACK_NOTIFY = "fallback_notify"
CONF_REPEAT_INTERVAL = "repeat_interval"
CONF_REPEAT_MAX = "repeat_max"
CONF_OFFLINE_ALERT_DELAY = "offline_alert_delay"

MODE_FIXED = "fixed"
MODE_TITLE = "title"
MODE_FULL = "full"
MODE_REGEX = "regex"
MESSAGE_MODES = [MODE_FIXED, MODE_TITLE, MODE_FULL, MODE_REGEX]

DEFAULT_FIXED_MESSAGE = "Pushover alert received, please check"
DEFAULT_MULTIPLE_MESSAGE = "Multiple Pushover alerts recorded"
DEFAULT_EMERGENCY_MESSAGE = "Pushover emergency alert, please acknowledge"
DEFAULT_MAX_LENGTH = 200
DEFAULT_MIN_PRIORITY = -2
DEFAULT_REPEAT_INTERVAL = 60
DEFAULT_REPEAT_MAX = 10
DEFAULT_OFFLINE_ALERT_DELAY = 60
DEFAULT_VOLUME = 60

PRIORITIES = {
    "-2": "Lowest (-2)",
    "-1": "Low (-1)",
    "0": "Normal (0)",
    "1": "High (1)",
    "2": "Emergency (2)",
}

# --- Runtime ------------------------------------------------------------------
EVENT_ALERT = f"{DOMAIN}_alert"
EVENT_ACK = f"{DOMAIN}_acknowledged"
SIGNAL_UPDATE = f"{DOMAIN}_update"

KEEPALIVE_TIMEOUT = 120  # Pushover sends "#" roughly every 30 s
QUEUED_AGE = 120  # messages older than this when fetched count as queued
RETRY_MIN = 15  # Pushover asks clients to back off before reconnecting
RETRY_MAX = 300
WAKE_TIMEOUT = 3  # seconds to wait for a sleeping speaker to report its volume
PLAYBACK_START_TIMEOUT = 15
PLAYBACK_END_TIMEOUT = 60

MESSAGE_FIELDS = (
    "id_str",
    "umid_str",
    "title",
    "message",
    "app",
    "priority",
    "date",
    "receipt",
    "acked",
    "url",
    "url_title",
)

ISSUE_LOGIN = "login_failed"
ISSUE_STOPPED = "device_stopped"
