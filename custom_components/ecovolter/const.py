"""Constants for EcoVolter."""

DOMAIN = "ecovolter"
PLATFORMS = ["sensor", "binary_sensor", "switch", "number"]

CONF_SECRET = "secret"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_PORT = 80
# Live status refresh in seconds. 1 s overloads some charger firmware, which
# then starts timing out; 2 s is still "live" and much more stable.
DEFAULT_SCAN_INTERVAL = 2
MIN_SCAN_INTERVAL = 1
MAX_SCAN_INTERVAL = 60

# When the charger stops responding, polling slows down step by step up to
# this interval so the charger can recover instead of being hammered.
MAX_BACKOFF_INTERVAL = 30
# After this many seconds without a successful status read, entities become
# unavailable instead of silently showing frozen values.
STALE_AFTER_SECONDS = 60

SETTINGS_REFRESH_SECONDS = 60
# Re-check settings this long after a write (instead of a full minute).
SETTINGS_VERIFY_AFTER_WRITE_SECONDS = 10
DIAGNOSTIC_REFRESH_SECONDS = 60

DNS_REFRESH_SECONDS = 3600
REQUEST_TIMEOUT_SECONDS = 4
CONNECT_TIMEOUT_SECONDS = 2

MIN_CURRENT = 6
MAX_CURRENT = 16
