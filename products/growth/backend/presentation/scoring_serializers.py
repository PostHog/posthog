from django.core.exceptions import ValidationError as DjangoValidationError

from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers

from products.growth.backend.facade.scoring import validate_scoring_source


@extend_schema_field(
    {
        "type": "object",
        "required": ["company", "signup", "enrichments", "lists"],
        "properties": {
            "company": {"type": "object", "nullable": True, "additionalProperties": True},
            "signup": {
                "type": "object",
                "required": ["role", "domain", "wizard_ai_sdk"],
                "properties": {
                    "role": {"type": "string"},
                    "domain": {"type": "string"},
                    "wizard_ai_sdk": {"type": "boolean"},
                },
            },
            "enrichments": {
                "type": "object",
                "additionalProperties": {"type": "object", "additionalProperties": True},
            },
            "lists": {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "string"}}},
        },
    }
)
class ScoringInputsField(serializers.JSONField):
    pass


@extend_schema_field(
    {
        "type": "object",
        "additionalProperties": {
            "oneOf": [{"type": "boolean"}, {"type": "number"}, {"type": "string"}],
            "nullable": True,
        },
    }
)
class ScoringFlagsField(serializers.JSONField):
    pass


class ScoringConfigSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Saved scoring configuration identifier.")
    version = serializers.CharField(help_text="Name of this immutable scoring version.")
    source = serializers.CharField(read_only=True, help_text="Editable Hog scoring formula.")  # type: ignore[assignment]
    is_active = serializers.BooleanField(help_text="Whether scoring uses this version.")
    created_at = serializers.DateTimeField(help_text="When this version was saved.")
    created_by_email = serializers.EmailField(
        read_only=True, allow_null=True, help_text="Author email, or null for imported configurations."
    )


@extend_schema_serializer(many=False)
class ScoringConfigListResponseSerializer(serializers.Serializer):
    results = ScoringConfigSerializer(many=True, help_text="Saved configurations, newest first.")
    default_source = serializers.CharField(help_text="Hog source for the default ICP scoring policy.")


class ScoringSourceSerializer(serializers.Serializer):
    source = serializers.CharField(  # type: ignore[assignment]
        max_length=30_000, trim_whitespace=False, help_text="Hog formula to compile and execute."
    )

    def validate_source(self, value: str) -> str:
        try:
            validate_scoring_source(value)
        except (DjangoValidationError, ValueError) as error:
            raise serializers.ValidationError(str(error)) from error
        return value


class ScoringPreviewRequestSerializer(ScoringSourceSerializer):
    base_config_id = serializers.UUIDField(
        help_text="Configuration whose curated tags and investors to use for the draft."
    )
    sample = serializers.IntegerField(
        default=10, min_value=1, max_value=10, help_text="Number of recent companies to preview."
    )


class ScoringSaveRequestSerializer(ScoringSourceSerializer):
    version = serializers.CharField(max_length=128, help_text="Unique name for the new scoring version.")
    base_config_id = serializers.UUIDField(help_text="Configuration whose curated tags and investors to retain.")


class ScoringActivateRequestSerializer(serializers.Serializer):
    config_id = serializers.UUIDField(help_text="Saved scoring version to activate for subsequent evaluations.")


class ScoringOutcomeSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="Scored, disqualified, missing-company, or insufficient-data status.")
    score = serializers.IntegerField(
        allow_null=True, help_text="Total ICP score, or null when the company cannot be scored."
    )
    components = serializers.DictField(
        child=serializers.IntegerField(), allow_null=True, help_text="Points for each scoring component."
    )
    flags = ScoringFlagsField(help_text="Named diagnostic values returned by the formula.")
    dq_reason = serializers.CharField(allow_null=True, help_text="Reason for disqualification, or null when absent.")


class ScoringPreviewRowSerializer(serializers.Serializer):
    company = serializers.CharField(help_text="Company name from the archived enrichment.")
    domain = serializers.CharField(allow_null=True, help_text="Company signup domain.")
    inputs = ScoringInputsField(
        help_text="Saved company facts, signup answers, enrichment outputs, and curated lists supplied to the formula."
    )
    active = ScoringOutcomeSerializer(allow_null=True, help_text="Result from the active formula on these inputs.")
    preview = ScoringOutcomeSerializer(allow_null=True, help_text="Result from the draft formula, or null on failure.")
    error = serializers.CharField(allow_null=True, help_text="Formula error for this company, or null on success.")


class ScoringPreviewSummarySerializer(serializers.Serializer):
    evaluated = serializers.IntegerField(help_text="Number of companies in the sample.")
    changed = serializers.IntegerField(help_text="Companies whose draft result differs from the active formula.")
    errors = serializers.IntegerField(help_text="Companies whose active or draft formula failed.")  # type: ignore[assignment]


@extend_schema_serializer(many=False)
class ScoringPreviewResponseSerializer(serializers.Serializer):
    results = ScoringPreviewRowSerializer(
        many=True, help_text="Read-only comparison using saved company facts and labels."
    )
    summary = ScoringPreviewSummarySerializer(help_text="Counts for this preview.")
