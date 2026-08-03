"""Request and response serializers for the staff AI enrichment API (see ai_enrichment.py).

These are the source of truth for the generated frontend types and MCP tool schemas, so every
field carries help_text and every response shape is a declared serializer rather than a raw dict.
"""

from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers

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

_PROMPT_TEXT_HELP = "System prompt; {email} is replaced with the signup email domain at runtime."

_INPUT_FIELDS_HELP = (
    "Dotted paths into the archived Harmonic payload fed to the prompt, e.g. funding.fundingStage. Restricted to "
    "the allow-list served by GET /input_fields/, because every selected value reaches the LLM and is then stored "
    "on the result indefinitely."
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
