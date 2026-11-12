"""Lenient input for a table's `sync_frequency`.

Agents and scripts write "daily" or "60min" where the API wants "24hour" or "1hour". The field maps
those spellings to the canonical value before the choice check. Output and the OpenAPI enum keep the
canonical values only.
"""

import re
from typing import Any

from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from products.warehouse_sources.backend.facade.types import SettableSyncFrequency

_MINUTES_BY_FREQUENCY = {
    SettableSyncFrequency.FIVE_MINUTES.value: 5,
    SettableSyncFrequency.FIFTEEN_MINUTES.value: 15,
    SettableSyncFrequency.THIRTY_MINUTES.value: 30,
    SettableSyncFrequency.ONE_HOUR.value: 60,
    SettableSyncFrequency.SIX_HOURS.value: 6 * 60,
    SettableSyncFrequency.TWELVE_HOURS.value: 12 * 60,
    SettableSyncFrequency.ONE_DAY.value: 24 * 60,
    SettableSyncFrequency.SEVEN_DAYS.value: 7 * 24 * 60,
    SettableSyncFrequency.THIRTY_DAYS.value: 30 * 24 * 60,
}
_FREQUENCY_BY_MINUTES = {minutes: frequency for frequency, minutes in _MINUTES_BY_FREQUENCY.items()}

_WORD_SYNONYMS = {
    "hourly": SettableSyncFrequency.ONE_HOUR.value,
    "daily": SettableSyncFrequency.ONE_DAY.value,
    "weekly": SettableSyncFrequency.SEVEN_DAYS.value,
    "monthly": SettableSyncFrequency.THIRTY_DAYS.value,
}

_MINUTES_PER_UNIT = {
    "m": 1,
    "min": 1,
    "mins": 1,
    "minute": 1,
    "minutes": 1,
    "h": 60,
    "hr": 60,
    "hrs": 60,
    "hour": 60,
    "hours": 60,
    "d": 24 * 60,
    "day": 24 * 60,
    "days": 24 * 60,
    "w": 7 * 24 * 60,
    "wk": 7 * 24 * 60,
    "week": 7 * 24 * 60,
    "weeks": 7 * 24 * 60,
    "mo": 30 * 24 * 60,
    "month": 30 * 24 * 60,
    "months": 30 * 24 * 60,
}
_DURATION_PATTERN = re.compile(r"^(?:every)?(\d+)([a-z]+)$")
_SEPARATORS = re.compile(r"[\s_\-]+")

SYNC_FREQUENCY_HELP_TEXT = (
    "How often to sync. One of 5min, 15min, 30min, 1hour, 6hour, 12hour, 24hour, 7day or 30day; the fastest is "
    "5 minutes. Common spellings are mapped to these: hourly = 1hour, daily = 24hour, weekly = 7day, "
    "monthly = 30day, and durations such as 60min, 1h, 24h, 1day or 1week. To stop a table syncing, set "
    "should_sync to false instead."
)

NEVER_SYNC_FREQUENCY_ERROR = '"never" is not a sync frequency. To stop syncing this table, set should_sync to false.'

_INVALID_CHOICE_ERROR = (
    '"{input}" is not a valid sync frequency. The fastest sync frequency is 5 minutes. Valid values: '
    + ", ".join(_MINUTES_BY_FREQUENCY)
    + '. Common spellings such as "daily" (24hour) and "hourly" (1hour) are also accepted.'
)


def normalize_sync_frequency(value: str) -> str:
    """The canonical frequency for a common spelling, or the input unchanged when none matches."""
    key = _SEPARATORS.sub("", value).lower()
    if key in _MINUTES_BY_FREQUENCY:
        return key
    if key in _WORD_SYNONYMS:
        return _WORD_SYNONYMS[key]
    match = _DURATION_PATTERN.match(key)
    if match:
        unit_minutes = _MINUTES_PER_UNIT.get(match.group(2))
        if unit_minutes is not None:
            return _FREQUENCY_BY_MINUTES.get(int(match.group(1)) * unit_minutes, value)
    return value


class SyncFrequencyField(serializers.ChoiceField):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("help_text", SYNC_FREQUENCY_HELP_TEXT)
        kwargs.setdefault("error_messages", {"invalid_choice": _INVALID_CHOICE_ERROR})
        super().__init__(choices=SettableSyncFrequency.choices, **kwargs)

    def to_internal_value(self, data: Any) -> str:
        if isinstance(data, str):
            if _SEPARATORS.sub("", data).lower() == "never":
                raise ValidationError(NEVER_SYNC_FREQUENCY_ERROR)
            data = normalize_sync_frequency(data)
        return super().to_internal_value(data)
