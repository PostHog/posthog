from django.db import models

from rest_framework import serializers


class ScoutOrigin(models.TextChoices):
    CANONICAL = "canonical", "canonical"
    CUSTOM = "custom", "custom"


class ScoutSuggestionConfidence(models.TextChoices):
    LOW = "low", "low"
    MEDIUM = "medium", "medium"
    HIGH = "high", "high"


class ScoutSuggestionProposedConfigSerializer(serializers.Serializer):
    run_cron_schedule = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Suggested five-field cron schedule in the project timezone, or null for an interval.",
    )
    run_interval_minutes = serializers.IntegerField(
        allow_null=True,
        required=False,
        help_text="Suggested minutes between runs when no cron is given; null means the daily default.",
    )
    emit = serializers.BooleanField(
        help_text="Whether the suggested scout should write to the inbox (false = dry run)."
    )


class ScoutSuggestionItemSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Stable id of this suggestion within the batch; use it to dismiss.")
    kind = serializers.ChoiceField(
        choices=ScoutOrigin.choices,
        help_text="`canonical`: enable a PostHog-authored scout that exists but is off. `custom`: create a drafted scout.",
    )
    skill_name = serializers.CharField(
        help_text="The scout's `signals-scout-*` skill name (existing for canonical, proposed for custom)."
    )
    title = serializers.CharField(help_text="Short sentence-case title: what the scout watches.")
    why_here = serializers.CharField(help_text="Project-specific evidence for this suggestion, in prose.")
    description = serializers.CharField(
        allow_blank=True, help_text="Custom only: the one-line description the scout would be created with."
    )
    draft_body = serializers.CharField(
        allow_blank=True, help_text="Custom only: the complete skill body the scout would be created with."
    )
    proposed_config = ScoutSuggestionProposedConfigSerializer(help_text="Suggested schedule and emit posture.")
    gap = serializers.BooleanField(help_text="True when nothing in the current fleet covers this.")
    confidence = serializers.ChoiceField(
        choices=ScoutSuggestionConfidence.choices, help_text="The producer's confidence."
    )
