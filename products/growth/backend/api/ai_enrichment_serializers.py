"""Request and response serializers for the staff AI enrichment API (see ai_enrichment.py).

These are the source of truth for the generated frontend types and MCP tool schemas, so every
field carries help_text and every response shape is a declared serializer rather than a raw dict.
"""

from typing import Any

from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers

from posthog.exceptions_capture import capture_exception

from products.growth.backend.enrichment.lab import DEFAULT_SAMPLE_SIZE, DRAFT_VERSION_SENTINEL, MAX_SAMPLE_SIZE
from products.growth.backend.enrichment.labels import (
    MAX_OUTPUT_FIELD_DESCRIPTION_CHARS,
    MAX_OUTPUT_FIELDS,
    MAX_PROMPT_TEXT_CHARS,
    OUTPUT_FIELD_KEY_RE,
    OUTPUT_FIELD_TYPES,
    RESERVED_OUTPUT_FIELD_KEYS,
    PromptConfigError,
    validate_input_fields,
    validate_output_fields,
)
from products.growth.backend.models import EnrichmentPromptConfig

_OUTPUT_FIELDS_HELP = (
    "Output schema: list of {key, type, description}. type is 'boolean', 'number', or 'string'. This is the "
    "classifier's entire output contract - the label is a human name and is never an output key, so renaming a "
    "label changes nothing about what a version computes. Keys must match ^[a-z][a-z0-9_]*$, be unique, and not "
    f"be 'meta' or 'inputs'. At most {MAX_OUTPUT_FIELDS} fields."
)

_PROMPT_TEXT_HELP = (
    "System prompt; {email} is replaced with the signup email domain at runtime. "
    f"At most {MAX_PROMPT_TEXT_CHARS} characters."
)

_MODEL_HELP = "Gateway model to classify with, routed through the LLM gateway. See GET /models/ for what it serves."

_INPUT_FIELDS_HELP = (
    "Dotted paths into the archived Harmonic payload fed to the prompt, e.g. funding.fundingStage. Every selected "
    "value reaches the LLM and is then stored on the result indefinitely, so keep this list intentional."
)


class OutputFieldSerializer(serializers.Serializer):
    key = serializers.RegexField(
        OUTPUT_FIELD_KEY_RE,
        help_text="Output key, e.g. ai_pilled. Lowercase, starts with a letter, letters/digits/underscore only.",
    )
    type = serializers.ChoiceField(
        choices=[(value, value) for value in OUTPUT_FIELD_TYPES],
        help_text="Value type the LLM must return for this key.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=MAX_OUTPUT_FIELD_DESCRIPTION_CHARS,
        help_text=f"Shown to the LLM to describe what this key means. At most {MAX_OUTPUT_FIELD_DESCRIPTION_CHARS} "
        "characters.",
    )

    def validate_key(self, value: str) -> str:
        if value in RESERVED_OUTPUT_FIELD_KEYS:
            raise serializers.ValidationError(f"{value!r} is reserved for provenance and cannot be an output key.")
        return value


def _validate_output_fields_list(value: list[dict[str, str]]) -> list[dict[str, str]]:
    """The two rules OutputFieldSerializer cannot enforce per item: uniqueness across the list,
    and a cap on the list's own length (unlike max_length on a single field, list-item-count
    limits aren't expressible on a `many=True` nested serializer)."""
    if len(value) > MAX_OUTPUT_FIELDS:
        raise serializers.ValidationError(f"At most {MAX_OUTPUT_FIELDS} output fields are allowed, got {len(value)}.")
    keys = [field["key"] for field in value]
    duplicates = {key for key in keys if keys.count(key) > 1}
    if duplicates:
        raise serializers.ValidationError(f"Duplicate output field key {sorted(duplicates)[0]!r}.")
    return value


def _validate_config_shape(attrs: dict[str, Any], *, capture_path: str | None = None) -> None:
    """Run validate_input_fields/validate_output_fields (enrichment/labels.py) against a
    throwaway, unsaved config built from the submitted shape, translating a PromptConfigError
    into a normal 400 instead of it surfacing as an unhandled 500 - or, on the streaming /run/
    endpoint, only after a 200 response has already started.

    capture_path is set only by the money-spending /run/ endpoint's serializer: a bad draft
    config there means a request was about to reach the LLM gateway, which is worth tracking
    even though it's "just" a 400. Plain save-time validation errors are routine user input and
    don't need capture_exception, matching how ActivateRequestSerializer/RenameRequestSerializer
    style 400s are handled elsewhere in this file.
    """
    draft = EnrichmentPromptConfig(
        name=attrs.get("label", ""),
        prompt_text=attrs.get("prompt_text", ""),
        model=attrs.get("model", ""),
        input_fields=attrs.get("input_fields", []),
        output_fields=attrs["output_fields"],
    )
    try:
        validate_input_fields(draft)
        validate_output_fields(draft)
    except PromptConfigError as e:
        if capture_path is not None:
            capture_exception(e, {"path": capture_path})
        raise serializers.ValidationError(str(e)) from e


class LabelSummarySerializer(serializers.Serializer):
    label = serializers.CharField(help_text="Label name computed by one or more prompt config versions.")  # type: ignore[assignment]  # DRF Field.label collides with a field named label
    version_count = serializers.IntegerField(help_text="Number of prompt config versions saved for this label.")
    active_version = serializers.CharField(
        allow_null=True, help_text="Version string the batch runner currently computes for this label, or null."
    )


@extend_schema_serializer(many=False)
class LabelListResponseSerializer(serializers.Serializer):
    results = LabelSummarySerializer(many=True, help_text="Distinct labels, alphabetical.")


class ConfigVersionSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Prompt config row id.")
    name = serializers.CharField(help_text="Label this config computes, e.g. ai_pilled.")
    version = serializers.CharField(help_text="Server-assigned version identity, e.g. v3.")
    prompt_text = serializers.CharField(help_text=_PROMPT_TEXT_HELP)
    model = serializers.CharField(help_text="Gateway model id this version was authored against.")
    input_fields = serializers.ListField(child=serializers.CharField(), help_text=_INPUT_FIELDS_HELP)
    output_fields = OutputFieldSerializer(many=True, help_text=_OUTPUT_FIELDS_HELP)
    is_active = serializers.BooleanField(help_text="Whether the batch runner currently computes this version.")
    created_by_email = serializers.SerializerMethodField(
        help_text="Email of the staff user who created this version, or null for system-seeded rows."
    )
    created_at = serializers.DateTimeField(help_text="When this version was created.")
    has_results = serializers.SerializerMethodField(
        help_text="Whether any EnrichmentLabelResult rows reference this version. Informational only: the API "
        "never edits a version's content in place, it only creates a new one, so this doesn't gate anything. "
        "The label name is not part of a version's content and can always be renamed."
    )

    @extend_schema_field(serializers.EmailField(allow_null=True))
    def get_created_by_email(self, obj: EnrichmentPromptConfig) -> str | None:
        return obj.created_by.email if obj.created_by else None

    @extend_schema_field(serializers.BooleanField())
    def get_has_results(self, obj: EnrichmentPromptConfig) -> bool:
        return obj.version in self.context.get("versions_with_results", set())


@extend_schema_serializer(many=False)
class ConfigListResponseSerializer(serializers.Serializer):
    results = ConfigVersionSerializer(many=True, help_text="Versions for the requested label, newest first.")


class ConfigsQuerySerializer(serializers.Serializer):
    label = serializers.CharField(help_text="Label name to list prompt config versions for.")  # type: ignore[assignment]  # DRF Field.label collides with a field named label


class ActivateRequestSerializer(serializers.Serializer):
    config_id = serializers.UUIDField(help_text="Prompt config id to activate for its label.")


class GatewayModelSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Gateway model id, usable as `model` on save/run.")


@extend_schema_serializer(many=False)
class GatewayModelListResponseSerializer(serializers.Serializer):
    results = GatewayModelSerializer(
        many=True,
        help_text="Models the gateway currently lists (cached for 5 minutes), or empty if it is unreachable - "
        "there is no curated mirror, since one goes stale silently.",
    )


class SaveRequestSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=128, help_text="Label this config computes, e.g. ai_pilled.")  # type: ignore[assignment]  # DRF Field.label collides with a field named label
    version = serializers.CharField(
        max_length=128,
        required=False,
        allow_blank=True,
        help_text="Version identity for the new row, e.g. v3. Optional: omit (or send blank) to accept the "
        "server-suggested next version for this label. Versions are immutable once created - there is no "
        "update endpoint - and (label, version) must be unique.",
    )
    prompt_text = serializers.CharField(max_length=MAX_PROMPT_TEXT_CHARS, help_text=_PROMPT_TEXT_HELP)
    model = serializers.CharField(max_length=128, help_text=_MODEL_HELP)
    input_fields = serializers.ListField(
        child=serializers.CharField(), required=False, default=list, help_text=_INPUT_FIELDS_HELP
    )
    output_fields = OutputFieldSerializer(many=True, allow_empty=False, help_text=_OUTPUT_FIELDS_HELP)

    def validate_version(self, value: str) -> str:
        # The /run/ endpoint stamps every unsaved draft with exactly this string (see
        # DRAFT_VERSION_SENTINEL's docstring); accepting it here would let a saved row collide in
        # meaning with an in-flight test run's draft.
        if value == DRAFT_VERSION_SENTINEL:
            raise serializers.ValidationError(
                f"{DRAFT_VERSION_SENTINEL!r} is reserved for unsaved test runs and cannot be saved as a version."
            )
        return value

    def validate_output_fields(self, value: list[dict[str, str]]) -> list[dict[str, str]]:
        return _validate_output_fields_list(value)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        _validate_config_shape(attrs)
        return attrs


class RunRequestSerializer(serializers.Serializer):
    label = serializers.CharField(  # type: ignore[assignment]
        max_length=128,
        help_text="Label this draft config computes, e.g. ai_pilled. Need not already exist - run classifies "
        "against an in-memory config only and persists nothing.",
    )
    prompt_text = serializers.CharField(max_length=MAX_PROMPT_TEXT_CHARS, help_text=_PROMPT_TEXT_HELP)
    model = serializers.CharField(max_length=128, help_text=_MODEL_HELP)
    input_fields = serializers.ListField(
        child=serializers.CharField(), required=False, default=list, help_text=_INPUT_FIELDS_HELP
    )
    output_fields = OutputFieldSerializer(many=True, allow_empty=False, help_text=_OUTPUT_FIELDS_HELP)
    sample = serializers.IntegerField(
        required=False,
        default=DEFAULT_SAMPLE_SIZE,
        min_value=1,
        max_value=MAX_SAMPLE_SIZE,
        help_text=f"Number of the most recently archived, distinct orgs to classify (1-{MAX_SAMPLE_SIZE}). Each "
        "sampled org costs one LLM call, so keep this bounded during iteration.",
    )

    def validate_output_fields(self, value: list[dict[str, str]]) -> list[dict[str, str]]:
        return _validate_output_fields_list(value)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # capture_path: this endpoint spends real LLM money the moment it starts streaming, so a
        # draft config that would fail is worth tracking even though it never reaches the LLM.
        _validate_config_shape(attrs, capture_path="ai_enrichment.run")
        return attrs
