"""Constants for Push Alert TTS (an unofficial Pushover Open Client)."""

from __future__ import annotations

DOMAIN = "push_alert_tts"
VERSION = "0.6.1"

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
CONF_SPOKEN_TEMPLATE = "spoken_template"
CONF_REGEX_SOURCE = "regex_source"
CONF_PART_MAX_LENGTH = "part_max_length"
CONF_TIDY_TEXT = "tidy_text"
CONF_HISTORY_DAYS = "history_days"
CONF_EXPAND_ABBREVIATIONS = "expand_abbreviations"
CONF_REMOVE_REPEATS = "remove_repeated_words"

# AI wording (optional local LLM). Stored flat in the options; shown in a
# collapsible "AI wording" section of the options form.
CONF_AI_SECTION = "ai_wording"
CONF_AI_ENABLED = "ai_enabled"
CONF_AI_API = "ai_api"
CONF_AI_URL = "ai_url"
CONF_AI_MODEL = "ai_model"
CONF_AI_API_KEY = "ai_api_key"
CONF_AI_TIMEOUT = "ai_timeout"
CONF_AI_EMERGENCY_TIMEOUT = "ai_emergency_timeout"
CONF_AI_MAX_WORDS = "ai_max_words"
CONF_AI_INSTRUCTIONS = "ai_instructions"
CONF_AI_START_PATTERN = "ai_start_pattern"
CONF_AI_CONTEXT = "ai_context_size"  # Ollama num_ctx
CONF_AI_KEEP_ALIVE = "ai_keep_alive"  # Ollama keep_alive
CONF_AI_GPU_LAYERS = "ai_gpu_layers"  # Ollama num_gpu
CONF_AI_MEMORY = "ai_memory"  # form field only; the memory lives in a file
CONF_AI_AUTO_BACKFILL = "ai_auto_backfill"
CONF_AI_OFFLINE_ALERT = "ai_offline_alert"
AI_OPTION_KEYS = (
    CONF_AI_ENABLED,
    CONF_AI_API,
    CONF_AI_URL,
    CONF_AI_MODEL,
    CONF_AI_API_KEY,
    CONF_AI_TIMEOUT,
    CONF_AI_EMERGENCY_TIMEOUT,
    CONF_AI_MAX_WORDS,
    CONF_AI_INSTRUCTIONS,
    CONF_AI_START_PATTERN,
    CONF_AI_CONTEXT,
    CONF_AI_KEEP_ALIVE,
    CONF_AI_GPU_LAYERS,
    CONF_AI_AUTO_BACKFILL,
    CONF_AI_OFFLINE_ALERT,
)
AI_API_OLLAMA = "ollama"
AI_API_OPENAI = "openai"
AI_APIS = [AI_API_OLLAMA, AI_API_OPENAI]
DEFAULT_AI_TIMEOUT = 60
MAX_AI_TIMEOUT = 600
DEFAULT_AI_EMERGENCY_TIMEOUT = 5
DEFAULT_AI_MAX_WORDS = 20
MAX_AI_CONTEXT = 1048576  # largest context size accepted (tokens)
MAX_AI_GPU_LAYERS = 1000
AI_CONNECT_TIMEOUT = 5  # seconds to open the connection to the LLM
AI_OFFLINE_SKIP = 60  # after a connection failure, skip the LLM this long
AI_MEMORY_VERSIONS = 20  # earlier copies of the AI memory kept
AI_MEMORY_LINE_MAX = 500  # characters per memory line
AI_REVIEW_DAYS = 3  # the AI review sensor shows this many days
AI_REVIEW_MAX = 50  # ... and at most this many alerts
AI_BACKFILL_TIMEOUT = 30  # max seconds per alert when re-wording past alerts
AI_BACKFILL_PAUSE = 1  # seconds between past alerts, so live alerts get the LLM
AI_BACKFILL_DEFAULT_DAYS = 3
AI_BACKFILL_MAX = 500  # past alerts per run
AI_PROBE_INTERVAL = 300  # seconds between checks that the LLM server answers
AI_PROBE_TIMEOUT = 10  # seconds for one check
DEFAULT_AI_AUTO_BACKFILL = True
DEFAULT_AI_OFFLINE_ALERT = 30  # minutes; 0 = no alert
MAX_AI_OFFLINE_ALERT = 1440

MODE_FIXED = "fixed"
MODE_TITLE = "title"
MODE_FULL = "full"
MODE_REGEX = "regex"
MESSAGE_MODES = [MODE_FIXED, MODE_TITLE, MODE_FULL, MODE_REGEX]

# Where the regular expression looks, in order (first match wins).
SOURCE_MESSAGE_TITLE = "message_title"
SOURCE_TITLE_MESSAGE = "title_message"
SOURCE_TITLE = "title"
SOURCE_MESSAGE = "message"
REGEX_SOURCES = [
    SOURCE_MESSAGE_TITLE,
    SOURCE_TITLE_MESSAGE,
    SOURCE_TITLE,
    SOURCE_MESSAGE,
]

DEFAULT_FIXED_MESSAGE = "Pushover alert received, please check"
DEFAULT_MULTIPLE_MESSAGE = "Multiple Pushover alerts recorded"
DEFAULT_EMERGENCY_MESSAGE = "Pushover emergency alert, please acknowledge"
DEFAULT_MAX_LENGTH = 200
DEFAULT_MIN_PRIORITY = -2
DEFAULT_REPEAT_INTERVAL = 60
DEFAULT_REPEAT_MAX = 10
DEFAULT_OFFLINE_ALERT_DELAY = 60
DEFAULT_VOLUME = 60
DEFAULT_PART_MAX_LENGTH = 40
DEFAULT_HISTORY_DAYS = 0  # off
MAX_HISTORY_DAYS = 90

# Safety nets for building the spoken text.
MAX_TITLE_INPUT = 500  # characters of the title the regex may look at
MAX_MESSAGE_INPUT = 4000  # characters of the message the regex may look at
HARD_MAX_SPOKEN = 2000  # never speak more than this, whatever max_length says
TEXT_TIMEOUT = 2  # seconds a regular expression may run before giving up

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
ISSUE_AI_OFFLINE = "ai_offline"
