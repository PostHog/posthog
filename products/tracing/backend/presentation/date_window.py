"""Relative time-window parsing for the tracing (APM) API.

Tracing is a short-window product — trace retention is measured in hours and days,
not months or years — so the relative-window shorthand it accepts is intentionally
different from PostHog's global ``relative_date_parse`` grammar in one place: here a
bare lowercase ``m`` means **minutes**, whereas the global parser reads ``m`` as
months (and only an uppercase ``M`` as minutes). ``-30m`` meaning "30 minutes ago"
is what an APM user expects, and anything coarser than a few weeks is meaningless
for span data.

We translate the friendly tracing shorthand onto the global parser's token
vocabulary so the rest of the date-range machinery is unchanged, pass ISO 8601
timestamps and the broader global relative grammar (``-1dStart``, ``-3q`` …) through
untouched so nothing that worked before regresses, and reject everything else with a
``ValidationError`` (HTTP 400) instead of silently falling back to "now" — which
previously turned a typo'd window into stale data with no error.
"""

import re

from dateutil import parser as dateutil_parser
from rest_framework import serializers

# Friendly tracing window: an integer with a single short unit, e.g. "-30m", "90s", "-2w".
# Case-insensitive; the leading minus is optional because windows are always in the past.
_TRACING_WINDOW_RE = re.compile(r"^-?(?P<number>\d+)(?P<unit>[smhdw])$", re.IGNORECASE)

# Map the friendly unit onto the token that posthog.utils.relative_date_parse understands.
# The deliberate part is "m" -> "M" (minutes): the global parser reads lowercase "m" as months.
_UNIT_TO_RELATIVE_TOKEN = {"s": "s", "m": "M", "h": "h", "d": "d", "w": "w"}

# The global relative-date grammar (kept in sync with posthog.utils.relative_date_parse).
# Used only to let already-supported formats — week/day/month boundaries, quarters, years —
# pass through unchanged rather than rejecting them. A match needs either a number (position
# optional) or a bare unit WITH a Start/End boundary; a bare unit alone (e.g. "h") is rejected,
# since the global parser would silently resolve it to "now" — the fail-open this module prevents.
_GLOBAL_RELATIVE_RE = re.compile(r"-?(?:\d+[hdwmqysHDWMQY](?:Start|End)?|[hdwmqysHDWMQY](?:Start|End))")


def normalize_tracing_window(value: str | None) -> str | None:
    """Normalize a single ``date_from``/``date_to`` value for the tracing API.

    Returns the normalized string (or ``None`` for an empty value, so the caller's
    default applies). Raises ``rest_framework.serializers.ValidationError`` for input
    that is neither a recognized relative window nor an ISO 8601 timestamp.
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None

    match = _TRACING_WINDOW_RE.match(stripped)
    if match:
        token = _UNIT_TO_RELATIVE_TOKEN[match.group("unit").lower()]
        return f"-{match.group('number')}{token}"

    # Absolute ISO 8601 timestamps pass through untouched.
    try:
        dateutil_parser.isoparse(stripped)
        return stripped
    except ValueError:
        pass

    # Preserve the broader global relative grammar (e.g. "-1dStart", "wStart", "-3q", "-1y")
    # so anything that already worked keeps working.
    if _GLOBAL_RELATIVE_RE.fullmatch(stripped):
        return stripped

    raise serializers.ValidationError(
        f"Invalid date range value {value!r}. Use a relative window like '-30m' (minutes), "
        "'-90s', '-6h', '-7d', '-2w', or an ISO 8601 timestamp."
    )


def normalize_tracing_date_range(raw: object, *, default_date_from: str = "-1h") -> dict:
    """Normalize a raw ``dateRange`` dict from request input.

    Falls back to ``{"date_from": default_date_from}`` when the input is missing or not
    a dict. ``date_from`` is normalized (defaulting when absent); ``date_to`` is
    normalized when present and left out otherwise (meaning "now" downstream).
    """
    if not isinstance(raw, dict) or not raw:
        return {"date_from": default_date_from}

    normalized: dict = dict(raw)
    normalized["date_from"] = normalize_tracing_window(raw.get("date_from")) or default_date_from
    date_to = normalize_tracing_window(raw.get("date_to"))
    if date_to is None:
        normalized.pop("date_to", None)
    else:
        normalized["date_to"] = date_to
    return normalized
