import re
from typing import Any, Literal, Optional, cast

from posthog.dataclasses import frozen

# One grammar for every duration a workflow expresses: '10d', '1.5h', '30m', '45s'. It is the format
# the Node worker parses (nodejs/src/cdp/services/hogflows/duration.ts), so a value this module accepts
# and the worker rejects is a step that validates on save and throws on the run.
#
# The alternation keeps each digit run owned by one quantifier. The obvious `\d*\.?\d+` lets `\d*` and
# `\d+` both claim the same digits, so a long non-matching value backtracks quadratically and one
# request can burn a web process. This form matches the same strings linearly.
#
# `[0-9]`, not `\d`: Python's `\d` also matches Unicode digits ('٧', '７') and `float()` parses them,
# so `\d` accepts a value the worker's ASCII regex cannot read.
_DURATION_BODY = r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)[dhms]"

DURATION_PATTERN = rf"^{_DURATION_BODY}$"
# A delay_until offset is the same shape, signed, so it can point before the date it offsets.
SIGNED_DURATION_PATTERN = rf"^-?{_DURATION_BODY}$"

_SIGNED_DURATION_REGEX = re.compile(SIGNED_DURATION_PATTERN)

DurationUnit = Literal["d", "h", "m", "s"]

SECONDS_PER_DURATION_UNIT: dict[str, float] = {"d": 86400, "h": 3600, "m": 60, "s": 1}
MINUTES_PER_DURATION_UNIT: dict[str, float] = {"d": 1440, "h": 60, "m": 1, "s": 1 / 60}

# What a single fixed delay is allowed to wait for, per unit. Mirrors the executor's clamp in
# nodejs/src/cdp/services/hogflows/actions/delay.ts. It bounds a delay step only: a conversion window
# takes its value whole, and 'd': 30 there would turn a 365-day window into 30 days without saying so.
MAX_VALUE_FOR_DURATION_UNIT: dict[str, float] = {"d": 30, "h": 24, "m": 60, "s": 60}

DURATION_EXAMPLES = "'30s', '30m', '2h', '1.5d'"


@frozen
class ParsedDuration:
    amount: float
    unit: DurationUnit
    negative: bool


def parse_duration(value: Any) -> Optional[ParsedDuration]:
    """The parts of a duration string, or None when it is not one.

    Returns the parts rather than a total because each caller bounds them differently: a fixed delay
    clamps the amount per unit, an offset keeps its sign, and a conversion window takes the value whole.
    """
    if not isinstance(value, str) or not _SIGNED_DURATION_REGEX.match(value):
        return None
    negative = value.startswith("-")
    body = value[1:] if negative else value
    return ParsedDuration(amount=float(body[:-1]), unit=cast(DurationUnit, body[-1]), negative=negative)


def is_duration(value: Any) -> bool:
    """True for an unsigned duration string."""
    parsed = parse_duration(value)
    return parsed is not None and not parsed.negative


def is_signed_duration(value: Any) -> bool:
    """True for a duration string that may point backwards, as a delay_until offset may."""
    return parse_duration(value) is not None


def duration_minutes(value: str) -> float:
    """Minutes for a value that has already matched DURATION_PATTERN."""
    return float(value[:-1]) * MINUTES_PER_DURATION_UNIT[value[-1]]


def duration_error(field: str) -> str:
    return f"{field} must be a duration string such as {DURATION_EXAMPLES}. ISO-8601 formats are not supported."
