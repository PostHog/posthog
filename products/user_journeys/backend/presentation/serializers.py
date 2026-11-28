import re
from collections.abc import Mapping
from typing import Any, cast

from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema_field
from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.schema import FunnelsQuery

from ..facade import api
from ..facade.contracts import (
    MAX_CONVERSION_WINDOW_MINUTES,
    MAX_SELECTOR_LENGTH,
    MAX_STEPS,
    MAX_TEXT_LENGTH,
    MAX_URL_LENGTH,
    MIN_CONVERSION_WINDOW_MINUTES,
    MIN_STEPS,
    CreateJourneyInput,
    ElementClickStep,
    JourneyLatestRun,
    JourneyStep,
    JourneyWithLatestRun,
    PageviewStep,
    UpdateJourneyInput,
)
from ..facade.enums import JourneyStepType, UrlMatching

_URL_MATCHING_HELP = (
    "How `url` is compared with the page URL: `exact` matches the whole URL, `contains` matches a "
    "case-insensitive substring, and `regex` matches a regular expression."
)


class _StepTypeField(serializers.CharField):
    step_type: JourneyStepType

    def to_internal_value(self, data: object) -> str:
        value = super().to_internal_value(cast(str, data))
        if value != self.step_type.value:
            self.fail("invalid")
        return value


@extend_schema_field({"type": "string", "const": JourneyStepType.PAGEVIEW.value})
class _PageviewStepTypeField(_StepTypeField):
    step_type = JourneyStepType.PAGEVIEW


@extend_schema_field({"type": "string", "const": JourneyStepType.ELEMENT_CLICK.value})
class _ElementClickStepTypeField(_StepTypeField):
    step_type = JourneyStepType.ELEMENT_CLICK


class _StrictStepSerializer(serializers.Serializer):
    def to_internal_value(self, data: Any) -> Any:
        if isinstance(data, Mapping):
            unknown = sorted(set(data) - set(self.fields))
            if unknown:
                raise serializers.ValidationError({key: ["This field is not allowed in this step."] for key in unknown})
        return super().to_internal_value(data)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("url") is not None and attrs.get("url_matching") == UrlMatching.REGEX:
            try:
                re.compile(attrs["url"])
            except re.error:
                raise serializers.ValidationError({"url": ["Enter a valid regular expression."]})
        return attrs


class PageviewStepSerializer(_StrictStepSerializer):
    type = _PageviewStepTypeField(help_text="Marks the step as a pageview of a matching URL.")
    url = serializers.CharField(
        max_length=MAX_URL_LENGTH, help_text="URL, URL fragment or regular expression the page URL must match."
    )
    url_matching = serializers.ChoiceField(
        choices=UrlMatching.choices, default=UrlMatching.EXACT.value, help_text=_URL_MATCHING_HELP
    )


class ElementClickStepSerializer(_StrictStepSerializer):
    type = _ElementClickStepTypeField(help_text="Marks the step as an autocaptured click on a matching element.")
    selector = serializers.CharField(
        max_length=MAX_SELECTOR_LENGTH, help_text="CSS selector of the clicked element, for example `button.signup`."
    )
    text = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=MAX_TEXT_LENGTH,
        help_text="Exact text of the clicked element. Leave out to match any text.",
    )
    href = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=MAX_URL_LENGTH,
        help_text="Exact link target of the clicked element. Leave out to match any link.",
    )
    url = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=MAX_URL_LENGTH,
        help_text="URL of the page the click happens on. Leave out to match the click on any page.",
    )
    url_matching = serializers.ChoiceField(
        choices=UrlMatching.choices, default=UrlMatching.EXACT.value, help_text=_URL_MATCHING_HELP
    )


JourneyStepSchema = PolymorphicProxySerializer(
    component_name="JourneyStep",
    serializers={
        JourneyStepType.PAGEVIEW.value: PageviewStepSerializer,
        JourneyStepType.ELEMENT_CLICK.value: ElementClickStepSerializer,
    },
    resource_type_field_name="type",
)


@extend_schema_field(JourneyStepSchema)
class JourneyStepField(serializers.Field):
    def to_internal_value(self, data: object) -> JourneyStep:
        if not isinstance(data, Mapping):
            raise serializers.ValidationError("Enter each step as an object.")
        step_type = data.get("type")
        if step_type == JourneyStepType.PAGEVIEW.value:
            pageview = PageviewStepSerializer(data=data)
            pageview.is_valid(raise_exception=True)
            return PageviewStep(**pageview.validated_data)
        if step_type == JourneyStepType.ELEMENT_CLICK.value:
            click = ElementClickStepSerializer(data=data)
            click.is_valid(raise_exception=True)
            return ElementClickStep(**click.validated_data)
        if step_type is None:
            raise serializers.ValidationError({"type": ["This field is required."]})
        raise serializers.ValidationError({"type": ["Select pageview or element_click."]})

    def to_representation(self, value: JourneyStep) -> dict[str, Any]:
        if isinstance(value, PageviewStep):
            return cast(dict[str, Any], PageviewStepSerializer(value).data)
        if isinstance(value, ElementClickStep):
            return cast(dict[str, Any], ElementClickStepSerializer(value).data)
        raise TypeError(f"Unsupported journey step: {type(value).__name__}")


_FIELD_HELP = {
    "name": "Display name for the journey.",
    "description": "What the journey covers and why it matters.",
    "steps": (
        f"Ordered steps a session must complete, from {MIN_STEPS} to {MAX_STEPS}. Each step is a pageview "
        "or a click on an element."
    ),
    "conversion_window_minutes": (
        f"Minutes a session has to go from the first step to the last, from {MIN_CONVERSION_WINDOW_MINUTES} "
        f"to {MAX_CONVERSION_WINDOW_MINUTES}."
    ),
    "source": "Where the journey was defined: `toolbar` for the toolbar, `manual` for the app or the API.",
    "start_url": (
        "Full http or https URL where a journey run opens the browser. Leave it null to start at the first "
        "step, which then must be an exact pageview of a full URL. Its host must be one of the project's "
        "authorized URLs when a run starts."
    ),
}

CREATE_NULL_MESSAGE = "Can't be null. Send a value for this field."
# Update inputs use None for "keep the stored value", so an explicit null is rejected rather than silently ignored.
UPDATE_NULL_MESSAGE = "Can't be null. To keep the current value, leave this field out of the request."


def _steps_field(required: bool, null_message: str) -> serializers.ListField:
    return serializers.ListField(
        child=JourneyStepField(),
        min_length=MIN_STEPS,
        max_length=MAX_STEPS,
        required=required,
        error_messages={"null": null_message},
        help_text=_FIELD_HELP["steps"],
    )


def _input_kwargs(null_message: str) -> dict[str, dict]:
    not_null = {"allow_null": False, "error_messages": {"null": null_message}}
    return {
        "name": {"help_text": _FIELD_HELP["name"], "max_length": 255, "allow_blank": False, **not_null},
        "description": {"help_text": _FIELD_HELP["description"], "allow_blank": True, **not_null},
        "conversion_window_minutes": {
            "help_text": _FIELD_HELP["conversion_window_minutes"],
            "min_value": MIN_CONVERSION_WINDOW_MINUTES,
            "max_value": MAX_CONVERSION_WINDOW_MINUTES,
            **not_null,
        },
        "source": {"help_text": _FIELD_HELP["source"], **not_null},
        "start_url": {"help_text": _FIELD_HELP["start_url"], "max_length": MAX_URL_LENGTH, "allow_blank": True},
    }


class JourneyLatestRunSerializer(DataclassSerializer):
    class Meta:
        dataclass = JourneyLatestRun
        fields = ["id", "status", "created_at", "finished_at", "failed_step_index"]
        extra_kwargs = {
            "status": {
                "help_text": "Status of the run: `pending`, `running`, `passed`, `failed` or `errored`.",
            },
            "created_at": {"help_text": "When the run was created."},
            "finished_at": {"help_text": "When the run ended. Null while it is pending or running."},
            "failed_step_index": {
                "help_text": "Position of the first failed step, from 0. Null unless a step of the run failed."
            },
        }

    id = serializers.UUIDField(source="run_id", read_only=True, help_text="Unique identifier of the run.")


class JourneySerializer(DataclassSerializer):
    steps = serializers.ListField(child=JourneyStepField(), help_text=_FIELD_HELP["steps"])
    latest_run = JourneyLatestRunSerializer(
        allow_null=True,
        read_only=True,
        help_text="The journey's newest run, so a list can show whether the journey still works. Null if it never ran.",
    )

    class Meta:
        dataclass = JourneyWithLatestRun
        # Keeps the schema component, and so the generated `JourneyApi` type, named after the journey.
        ref_name = "Journey"
        extra_kwargs = {
            **{field: {"help_text": help_text} for field, help_text in _FIELD_HELP.items() if field != "steps"},
            "id": {"help_text": "Unique identifier of the journey."},
            "team_id": {"help_text": "Project the journey belongs to."},
            "created_by_id": {"help_text": "ID of the user who created the journey, if known."},
            "created_at": {"help_text": "When the journey was created."},
            "updated_at": {"help_text": "When the journey was last changed."},
        }


@extend_schema_field(FunnelsQuery)  # type: ignore[arg-type]  # Supported by the Pydantic schema extension.
class _FunnelsQueryField(serializers.JSONField):
    pass


class JourneyFunnelQuerySerializer(serializers.Serializer):
    query = _FunnelsQueryField(
        read_only=True,
        help_text=(
            "Ordered funnel that counts the sessions that complete the journey's steps in order, within the "
            "journey's conversion window. Send it to the query endpoint to get per-step conversion."
        ),
    )


def validate_run_url(value: str | None) -> str | None:
    """Reject a URL whose text alone rules it out as a page a run opens. Empty values pass unchanged."""
    if value:
        error = api.run_url_error(value)
        if error is not None:
            raise serializers.ValidationError(error)
    return value


class CreateJourneyInputSerializer(DataclassSerializer):
    steps = _steps_field(required=True, null_message=CREATE_NULL_MESSAGE)

    def validate_start_url(self, value: str | None) -> str | None:
        return validate_run_url(value)

    class Meta:
        dataclass = CreateJourneyInput
        extra_kwargs = _input_kwargs(CREATE_NULL_MESSAGE)


class UpdateJourneyInputSerializer(DataclassSerializer):
    steps = _steps_field(required=False, null_message=UPDATE_NULL_MESSAGE)

    def validate_start_url(self, value: str | None) -> str | None:
        return validate_run_url(value)

    class Meta:
        dataclass = UpdateJourneyInput
        extra_kwargs = {
            **_input_kwargs(UPDATE_NULL_MESSAGE),
            "start_url": {
                "help_text": f"{_FIELD_HELP['start_url']} Send an empty string to remove the stored start URL.",
                "max_length": MAX_URL_LENGTH,
                "allow_blank": True,
                "allow_null": False,
                "error_messages": {"null": UPDATE_NULL_MESSAGE},
            },
        }
