from django.db import models

from rest_framework import serializers

from products.logs.backend.presentation.views.agent_fields import LogsAgentNextCallSerializer, LogsAgentWindowSerializer


class PatternsDiffSource(models.TextChoices):
    STORED_PATTERNS = "stored_patterns"
    BODY_MINING = "body_mining"


class PatternsDiffBodyFields(serializers.Serializer):
    limit = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        max_value=500,
        help_text="Return at most this many entries, most interesting first. Omit for all. Sets `truncated`.",
    )


class PatternDiffEntryFields(serializers.Serializer):
    masked_example = serializers.CharField(help_text="The template with variable parts masked.")
    services = serializers.ListField(child=serializers.CharField(), help_text="Up to 4 services with this pattern.")
    first_seen_ever = serializers.CharField(
        allow_null=True,
        help_text="Earliest 5-minute bucket (UTC) with this pattern, up to 14 days back. Null on body mining.",
    )


class PatternsDiffResponseFields(serializers.Serializer):
    window = LogsAgentWindowSerializer(help_text="Absolute UTC bounds of the current and baseline windows.")
    source = serializers.ChoiceField(  # type: ignore[assignment]  # field named `source` shadows DRF Field.source
        choices=PatternsDiffSource.choices,
        help_text="stored_patterns when both windows have ≥99% of rows on the same stored version, else body_mining.",
    )
    pattern_version = serializers.IntegerField(allow_null=True, help_text="Stored pattern version, null for mining.")
    sampled = serializers.BooleanField(help_text="True on the body-mining fallback: counts are sample estimates.")
    truncated = serializers.BooleanField(help_text="True when `limit` cut the entry list.")
    notes = serializers.ListField(child=serializers.CharField(), help_text="Caveats that limit what the diff shows.")
    next = LogsAgentNextCallSerializer(
        many=True, help_text="Prefilled query-logs calls for the top new or shifted patterns."
    )
