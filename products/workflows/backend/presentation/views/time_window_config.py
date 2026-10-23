import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from rest_framework import serializers

_WEEKDAYS = frozenset({"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"})
_DAY_OPTIONS = frozenset({"any", "weekday", "weekend"})
_CLOCK_TIME = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d", re.ASCII)


def validate_time_window_config(config: object) -> None:
    if not isinstance(config, dict):
        raise serializers.ValidationError({"config": "Time window settings must be an object."})

    errors: dict[str, str] = {}
    day = config.get("day")
    valid_day = (isinstance(day, str) and day in _DAY_OPTIONS) or (
        isinstance(day, list) and bool(day) and all(isinstance(value, str) and value in _WEEKDAYS for value in day)
    )
    if not valid_day:
        errors["day"] = "Choose 'any', 'weekday', 'weekend', or a nonempty list of lowercase weekday names."

    time = config.get("time")
    valid_time = time == "any" or (
        isinstance(time, list)
        and len(time) == 2
        and all(isinstance(value, str) and _CLOCK_TIME.fullmatch(value) for value in time)
    )
    if not valid_time:
        errors["time"] = "Choose 'any' or two times in 24-hour HH:mm format, such as ['09:00', '17:00']."

    for field in ("timezone", "fallback_timezone"):
        value = config.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            errors[field] = "Choose an IANA timezone, such as 'Europe/London', or null to use the default."
            continue
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            errors[field] = "Choose an IANA timezone, such as 'Europe/London', or null to use the default."

    if "use_person_timezone" in config and not isinstance(config["use_person_timezone"], bool):
        errors["use_person_timezone"] = "Use true or false."

    if errors:
        raise serializers.ValidationError({"config": errors})
