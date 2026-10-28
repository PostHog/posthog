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


def _validate_whole_minutes(value: int) -> None:
    # Schedulers that drive monitors count in minutes, so a value between minutes cannot be honored.
    if value % 60:
        raise serializers.ValidationError("Must be a whole number of minutes.")


CREATE_NULL_MESSAGE = "Can't be null. Send a value for this field."
# Update inputs use None for "keep the stored value", so an explicit null is rejected rather than silently ignored.
UPDATE_NULL_MESSAGE = "Can't be null. To keep the current value, leave this field out of the request."


def _input_kwargs(null_message: str) -> dict[str, dict]:
    not_null = {"allow_null": False, "error_messages": {"null": null_message}}
    return {
        **{field: {"help_text": help_text, **not_null} for field, help_text in _FIELD_HELP.items() if field != "url"},
        "name": {"help_text": _FIELD_HELP["name"], "max_length": 255, **not_null},
        "interval_seconds": {
            "help_text": _FIELD_HELP["interval_seconds"],
            "min_value": MIN_INTERVAL_SECONDS,
            "max_value": MAX_INTERVAL_SECONDS,
            "validators": [_validate_whole_minutes],
            **not_null,
        },
        "timeout_seconds": {
            "help_text": _FIELD_HELP["timeout_seconds"],
            "min_value": MIN_TIMEOUT_SECONDS,
            "max_value": MAX_TIMEOUT_SECONDS,
            **not_null,
        },
    }


def _url_field(required: bool, null_message: str) -> serializers.CharField:
    return serializers.CharField(
        max_length=2048,
        required=required,
        error_messages={"null": null_message},
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
    url = _url_field(required=True, null_message=CREATE_NULL_MESSAGE)

    class Meta:
        dataclass = CreateUptimeMonitorInput
        extra_kwargs = _input_kwargs(CREATE_NULL_MESSAGE)


class UpdateUptimeMonitorInputSerializer(DataclassSerializer):
    url = _url_field(required=False, null_message=UPDATE_NULL_MESSAGE)

    class Meta:
        dataclass = UpdateUptimeMonitorInput
        extra_kwargs = _input_kwargs(UPDATE_NULL_MESSAGE)
