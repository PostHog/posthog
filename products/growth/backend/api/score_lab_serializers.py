"""Request and response serializers for the staff score lab API (see score_lab.py).

These are the source of truth for the generated frontend types and MCP tool schemas, so every
field carries help_text and every response shape is a declared serializer rather than a raw dict.
"""

from typing import Any

from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers

from products.growth.backend.enrichment.input_query import InputQueryError, parse_input_query
from products.growth.backend.enrichment.lab import (
    DEFAULT_SAMPLE_SIZE,
    HARMONIC_INPUT_FIELD_PATHS,
    LABEL_SLUG_RE,
    MAX_SAMPLE_SIZE,
)
from products.growth.backend.enrichment.labels import (
    OUTPUT_FIELD_KEY_RE,
    OUTPUT_FIELD_TYPES,
    RESERVED_OUTPUT_FIELD_KEYS,
)
from products.growth.backend.models import EnrichmentPromptConfig

_OUTPUT_FIELDS_HELP = (
    "Output schema: list of {key, type, description}. type is 'boolean', 'number', or 'string'. This is the "
    "classifier's entire output contract - the label is a human name and is never an output key, so renaming a "
    "label changes nothing about what a version computes. Keys must match ^[a-z][a-z0-9_]*$, be unique, and not "
    "be 'meta' or 'inputs'."
)

_MODEL_HELP = "Gateway model to classify with, routed through the LLM gateway. See GET /models/ for what it serves."

_PROMPT_TEXT_HELP = "System prompt; {email} is replaced with the signup email domain at runtime."

_INPUT_FIELDS_HELP = (
    "Dotted paths into the archived Harmonic payload fed to the prompt, e.g. funding.fundingStage. Restricted to "
    "the allow-list served by GET /input_fields/, because every selected value reaches the LLM and is then stored "
    "on the result indefinitely. Ignored when input_query is set."
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
        help_text="Shown to the LLM to describe what this key means.",
    )

    def validate_key(self, value: str) -> str:
        if value in RESERVED_OUTPUT_FIELD_KEYS:
            raise serializers.ValidationError(f"{value!r} is reserved for provenance and cannot be an output key.")
        return value


def _validate_output_field_keys_are_unique(value: list[dict[str, str]]) -> list[dict[str, str]]:
    """Uniqueness is the one rule OutputFieldSerializer cannot enforce per item."""
    keys = [field["key"] for field in value]
    duplicates = {key for key in keys if keys.count(key) > 1}
    if duplicates:
        raise serializers.ValidationError(f"Duplicate output field key {sorted(duplicates)[0]!r}.")
    return value


def _validate_input_query(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parse_input_query(value)
    except InputQueryError as e:
        raise serializers.ValidationError(str(e))
    return value


class LabelSummarySerializer(serializers.Serializer):
    label = serializers.CharField(help_text="Label name computed by one or more prompt config versions.")  # type: ignore[assignment]  # DRF Field.label collides with a field named label
    version_count = serializers.IntegerField(help_text="Number of prompt config versions saved for this label.")
    active_version = serializers.CharField(
        allow_null=True, help_text="Version string the batch runner currently computes for this label, or null."
    )


@extend_schema_serializer(many=False)
class LabelListResponseSerializer(serializers.Serializer):
    results = LabelSummarySerializer(many=True, help_text="Distinct labels, alphabetical.")


class InputFieldSerializer(serializers.Serializer):
    value = serializers.CharField(help_text="Dotted path into the archived Harmonic payload, e.g. website.url.")
    label = serializers.CharField(help_text="Human-readable name for the path.")  # type: ignore[assignment]  # DRF Field.label collides with a field named label
    type = serializers.CharField(help_text="Shape of the value at this path, e.g. Text, Number, Date, List.")


@extend_schema_serializer(many=False)
class InputFieldListResponseSerializer(serializers.Serializer):
    results = InputFieldSerializer(
        many=True,
        help_text="Every payload path a config may select, in display order. Anything outside this list is "
        "rejected on run and save.",
    )


class GatewayModelSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Gateway model id, usable as `model` on run/save.")


@extend_schema_serializer(many=False)
class GatewayModelListResponseSerializer(serializers.Serializer):
    results = GatewayModelSerializer(
        many=True,
        help_text="Models the gateway currently lists (cached for 5 minutes), or empty if it is unreachable - "
        "there is no curated mirror, since one goes stale silently.",
    )


class ConfigVersionSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Prompt config row id.")
    name = serializers.CharField(help_text="Label this config computes, e.g. ai_pilled.")
    version = serializers.CharField(help_text="Server-assigned version identity, e.g. v3.")
    prompt_text = serializers.CharField(help_text=_PROMPT_TEXT_HELP)
    model = serializers.CharField(help_text="Gateway model id this version was authored against.")
    input_fields = serializers.ListField(child=serializers.CharField(), help_text=_INPUT_FIELDS_HELP)
    input_query = serializers.CharField(
        allow_null=True,
        help_text="HogQL SELECT defining classifier input rows, an alternative to input_fields. Null when "
        "input_fields is used instead. Each result row becomes one classification input; a 'company' or "
        "'domain' column (if present) is used for display, and every column is passed to the prompt as the "
        "Company data JSON keyed by column name.",
    )
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


class RunRequestSerializer(serializers.Serializer):
    label = serializers.CharField(  # type: ignore[assignment]
        max_length=128,
        help_text="Label this config computes, e.g. ai_pilled. Need not already exist - run classifies "
        "against an in-memory config only and persists nothing.",
    )
    prompt_text = serializers.CharField(help_text=_PROMPT_TEXT_HELP)
    model = serializers.CharField(max_length=128, help_text=_MODEL_HELP)
    input_fields = serializers.ListField(
        child=serializers.ChoiceField(choices=HARMONIC_INPUT_FIELD_PATHS),
        required=False,
        default=list,
        help_text=_INPUT_FIELDS_HELP,
    )
    input_query = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        default=None,
        help_text="HogQL SELECT defining classifier input rows, an alternative to input_fields. When set, rows "
        "are built from this query (capped at `sample` rows) instead of recently archived orgs; 'contains' is "
        "ignored. Parsed and validated on submit but never executed until /run/ actually runs.",
    )
    output_fields = OutputFieldSerializer(many=True, allow_empty=False, help_text=_OUTPUT_FIELDS_HELP)
    sample = serializers.IntegerField(
        required=False,
        default=DEFAULT_SAMPLE_SIZE,
        min_value=1,
        max_value=MAX_SAMPLE_SIZE,
        help_text=f"Number of rows to classify (1-{MAX_SAMPLE_SIZE}): recent archived orgs, or HogQL query rows "
        "when input_query is set. Each sampled row costs one LLM call, so keep this bounded during iteration.",
    )
    contains = serializers.CharField(
        required=False,
        default="",
        allow_blank=True,
        help_text="Optional case-insensitive substring filter on the archived company or organization name. "
        "Ignored when input_query is set.",
    )

    def validate_input_query(self, value: str | None) -> str | None:
        return _validate_input_query(value)

    def validate_output_fields(self, value: list[dict[str, str]]) -> list[dict[str, str]]:
        return _validate_output_field_keys_are_unique(value)


class RenameRequestSerializer(serializers.Serializer):
    config_id = serializers.UUIDField(help_text="Any config of the label to rename.")
    label = serializers.CharField(  # type: ignore[assignment]  # DRF Field.label collides with a field named label
        max_length=128,
        help_text="New label name. A label is shared by every version of it, so this renames them all. "
        "It changes nothing about what the classifier does: the output contract is output_fields.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        new_label = attrs["label"]
        if not LABEL_SLUG_RE.match(new_label):
            raise serializers.ValidationError({"label": f"{new_label!r} is not a valid label slug."})
        config = EnrichmentPromptConfig.objects.filter(pk=attrs["config_id"]).first()
        if config is None:
            return attrs  # existence is the view's job: 404, not 400
        if new_label != config.name and EnrichmentPromptConfig.objects.filter(name=new_label).exists():
            raise serializers.ValidationError(
                {"label": f"{new_label!r} already exists; renaming would merge two distinct labels."}
            )
        return attrs


class SaveRequestSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=128, help_text="Label this config computes, e.g. ai_pilled.")  # type: ignore[assignment]  # DRF Field.label collides with a field named label
    prompt_text = serializers.CharField(help_text=_PROMPT_TEXT_HELP)
    model = serializers.CharField(max_length=128, help_text=_MODEL_HELP)
    input_fields = serializers.ListField(
        child=serializers.ChoiceField(choices=HARMONIC_INPUT_FIELD_PATHS),
        required=False,
        default=list,
        help_text=_INPUT_FIELDS_HELP,
    )
    input_query = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        default=None,
        help_text="HogQL SELECT defining classifier input rows, an alternative to input_fields. Parsed and "
        "validated on save but never executed - execution only happens on /run/.",
    )
    output_fields = OutputFieldSerializer(many=True, allow_empty=False, help_text=_OUTPUT_FIELDS_HELP)

    def validate_input_query(self, value: str | None) -> str | None:
        return _validate_input_query(value)

    def validate_output_fields(self, value: list[dict[str, str]]) -> list[dict[str, str]]:
        return _validate_output_field_keys_are_unique(value)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        label = attrs["label"]
        is_new_label = not EnrichmentPromptConfig.objects.filter(name=label).exists()
        if is_new_label and not LABEL_SLUG_RE.match(label):
            raise serializers.ValidationError(
                {
                    "label": f"{label!r} is not a valid label slug (lowercase, starts with a letter, "
                    "letters/digits/underscore only)."
                }
            )
        return attrs


class ActivateRequestSerializer(serializers.Serializer):
    config_id = serializers.UUIDField(help_text="Prompt config id to activate for its label.")
