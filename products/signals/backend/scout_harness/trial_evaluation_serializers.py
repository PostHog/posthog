from __future__ import annotations

from django.db import models

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from products.signals.backend.scout_harness.trial_evaluation_types import TrialComparisonReport


class TrialEvaluationStatus(models.TextChoices):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    NOT_STARTED = "not_started"


class TrialRubricSource(models.TextChoices):
    MOCK = "mock"


class ScoutTrialEvaluationVariantSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Stable identity for this variant, independent of its display label.")
    label = serializers.CharField(  # type: ignore[assignment]  # field name intentionally shadows Field.label
        max_length=100, help_text="Name shown in the comparison report."
    )
    launch_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=20,
        help_text="Trial launches forming this variant's repeats.",
    )


class ScoutTrialEvaluationRequestSerializer(serializers.Serializer):
    evaluation_id = serializers.UUIDField(
        help_text="Stable evaluation identity. Reuse for retries of this exact request."
    )
    baseline_variant_id = serializers.UUIDField(help_text="Variant to use as the baseline for descriptive differences.")
    variants: serializers.ListSerializer[dict[str, object]] = serializers.ListSerializer(
        child=ScoutTrialEvaluationVariantSerializer(),
        min_length=1,
        max_length=10,
        help_text="Explicit variant groups containing at most 20 total trial runs.",
    )
    rubric_source = serializers.ChoiceField(
        choices=TrialRubricSource.choices, help_text="Explicit rubric input source."
    )


class ScoutTrialEvaluationQuerySerializer(serializers.Serializer):
    evaluation_id = serializers.UUIDField(help_text="Saved evaluation identity to inspect without starting a judge.")


@extend_schema_field(TrialComparisonReport)  # type: ignore[arg-type]
class ScoutTrialComparisonReportField(serializers.JSONField):
    pass


class ScoutTrialEvaluationSerializer(serializers.Serializer):
    request = ScoutTrialEvaluationRequestSerializer(
        help_text="Immutable request for exact retries, including saved variant labels."
    )
    evaluation_id = serializers.UUIDField(help_text="Stable identity for this saved evaluation.")
    context_id = serializers.UUIDField(help_text="Starting context shared by every evaluated run.")
    status = serializers.ChoiceField(choices=TrialEvaluationStatus.choices, help_text="Evaluation workflow status.")
    error = serializers.CharField(
        allow_null=True, help_text="Sanitized execution error, separate from quality verdicts."
    )
    report = ScoutTrialComparisonReportField(
        allow_null=True, help_text="Saved comparison scores and their supporting evidence."
    )
