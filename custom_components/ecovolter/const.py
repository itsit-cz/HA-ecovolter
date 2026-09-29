"""Constants for EcoVolter."""

DOMAIN = "ecovolter"
PLATFORMS = ["sensor", "binary_sensor", "switch", "number"]

CONF_SECRET = "secret"

DEFAULT_PORT = 80
DEFAULT_SCAN_INTERVAL = 5
DNS_REFRESH_SECONDS = 3600
REQUEST_TIMEOUT_SECONDS = 4

MIN_CURRENT = 6
MAX_CURRENT = 16
