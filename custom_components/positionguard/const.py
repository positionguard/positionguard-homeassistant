"""Constants for the PositionGuard integration."""

DOMAIN = "positionguard"

# Config flow keys
CONF_API_KEY = "api_key"
CONF_BASE_URL = "base_url"
CONF_GROUP_IDS = "group_ids"

# Default values
DEFAULT_BASE_URL = "https://api.positionguardai.com/api/v1"
DEFAULT_SCAN_INTERVAL_SECONDS = 30

# --- Transient-failure resilience (see coordinator._async_update_data) ---
# A single failed poll is almost always a brief edge/tunnel hiccup or short
# I/O contention that self-heals by the next 30s cycle. To avoid a scary ERROR
# log and a momentary entity flap, we retry once mid-cycle and tolerate one
# fully failed cycle before surfacing the failure.

# Backoff between the first failed attempt and the single in-cycle retry.
# Kept short and FIXED: we deliberately do NOT honor a 429 Retry-After hint
# here — sleeping out a 60s rate-limit window mid-cycle would overrun the 30s
# poll interval, so we'd rather fail the cycle and let toleration + the next
# poll cover it. Worst case attempt (<=10s request timeout) + backoff +
# retry (<=10s) stays under the 30s interval, so cycles never stack.
RETRY_BACKOFF_SECONDS = 2

# Number of consecutive failed cycles at which we stop holding last-known
# state and surface the failure (entities -> unavailable, ERROR logged).
# N=2 tolerates exactly one fully failed cycle (~30s of stale state) and
# surfaces on the second consecutive failure. Kept low so a genuine outage
# (or a real departure) is never masked for more than ~one poll interval.
MAX_CONSECUTIVE_FAILURES = 2

# Attribution shown in HA UI for entities from this integration
ATTRIBUTION = "Data provided by PositionGuard"

# Entity / device naming
MANUFACTURER = "PositionGuard"
