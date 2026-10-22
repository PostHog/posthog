from django.core.validators import URLValidator

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import (
    MAX_INTERVAL_SECONDS,
    MAX_TIMEOUT_SECONDS,
    MIN_INTERVAL_SECONDS,
    MIN_TIMEOUT_SECONDS,
    CreateUptimeMonitorInput,
    UpdateUptimeMonitorInput,
    UptimeMonitor,
)

_FIELD_HELP = {
    "name": "Display name for the monitor.",
    "url": "The http or https URL to check.",
    "method": "HTTP method used for each check.",
    "interval_seconds": f"Seconds between checks, a whole number of minutes from {MIN_INTERVAL_SECONDS} to {MAX_INTERVAL_SECONDS}.",
    "timeout_seconds": f"Seconds to wait for a response before the check fails, from {MIN_TIMEOUT_SECONDS} to {MAX_TIMEOUT_SECONDS}.",
    "enabled": "Whether checks run for this monitor.",
}

_INPUT_KWARGS = {
    **{field: {"help_text": help_text} for field, help_text in _FIELD_HELP.items() if field != "url"},
    "interval_seconds": {
        "help_text": _FIELD_HELP["interval_seconds"],
        "min_value": MIN_INTERVAL_SECONDS,
        "max_value": MAX_INTERVAL_SECONDS,
    },
    "timeout_seconds": {
        "help_text": _FIELD_HELP["timeout_seconds"],
        "min_value": MIN_TIMEOUT_SECONDS,
        "max_value": MAX_TIMEOUT_SECONDS,
    },
}


def _validate_whole_minutes(value: int | None) -> int | None:
    # Schedulers that drive monitors count in minutes, so a value between minutes cannot be honored.
    if value is not None and value % 60:
        raise serializers.ValidationError("Must be a whole number of minutes.")
    return value


def _url_field(required: bool) -> serializers.CharField:
    return serializers.CharField(
        max_length=2048,
        required=required,
        validators=[URLValidator(schemes=["http", "https"])],
        help_text=_FIELD_HELP["url"],
    )


class UptimeMonitorSerializer(DataclassSerializer):
    class Meta:
        dataclass = UptimeMonitor
        extra_kwargs = {
            **{field: {"help_text": help_text} for field, help_text in _FIELD_HELP.items()},
            "id": {"help_text": "Unique identifier of the monitor."},
            "team_id": {"help_text": "Project the monitor belongs to."},
            "created_at": {"help_text": "When the monitor was created."},
            "updated_at": {"help_text": "When the monitor was last changed."},
        }


class CreateUptimeMonitorInputSerializer(DataclassSerializer):
    url = _url_field(required=True)

    def validate_interval_seconds(self, value: int) -> int:
        _validate_whole_minutes(value)
        return value

    class Meta:
        dataclass = CreateUptimeMonitorInput
        extra_kwargs = _INPUT_KWARGS


class UpdateUptimeMonitorInputSerializer(DataclassSerializer):
    url = _url_field(required=False)

    def validate_interval_seconds(self, value: int | None) -> int | None:
        return _validate_whole_minutes(value)

    class Meta:
        dataclass = UpdateUptimeMonitorInput
        extra_kwargs = _INPUT_KWARGS
