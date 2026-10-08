from rest_framework import serializers

from products.signals.backend.scout_harness.limits import MAX_RUN_NOTE_CHARS, MAX_TRIAL_REPEATS, MAX_TRIAL_VARIANTS
from products.signals.backend.scout_harness.trial_evaluation_serializers import ScoutTrialEvaluationSerializer


class ScoutTrialComparisonVariantRequestSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Stable variant identity within this comparison.")
    label = serializers.CharField(max_length=100, help_text="Variant name shown in the report.")  # type: ignore[assignment]
    launch_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=MAX_TRIAL_REPEATS,
        help_text="Stable run IDs for this variant's repeats.",
    )
    model = serializers.CharField(max_length=200, help_text="Scout model to run.")
    reasoning_effort = serializers.CharField(max_length=20, help_text="Reasoning effort supported by this model.")
    skill_body = serializers.CharField(
        required=False,
        max_length=100_000,
        trim_whitespace=False,
        help_text="Replacement scout instructions. Omit to use the saved source instructions.",
    )


class ScoutTrialComparisonRequestSerializer(serializers.Serializer):
    comparison_id = serializers.UUIDField(help_text="Stable comparison ID. Reuse for an exact request retry.")
    baseline_variant_id = serializers.UUIDField(help_text="Variant used as the comparison baseline.")
    variants: serializers.ListSerializer[dict[str, object]] = serializers.ListSerializer(
        child=ScoutTrialComparisonVariantRequestSerializer(),
        min_length=1,
        max_length=MAX_TRIAL_VARIANTS,
        help_text=f"Up to {MAX_TRIAL_VARIANTS} variants, each with up to {MAX_TRIAL_REPEATS} scout runs.",
    )
    note = serializers.CharField(
        required=False, allow_blank=True, max_length=MAX_RUN_NOTE_CHARS, help_text="Shared investigation note."
    )
    expected_skill_version = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Source version shown in the editor. Refuse a new trial if the instructions changed since setup.",
    )


class ScoutTrialComparisonQuerySerializer(serializers.Serializer):
    comparison_id = serializers.UUIDField(help_text="Saved comparison identity.")


class ScoutTrialComparisonVariantSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Variant identity.")
    label = serializers.CharField(help_text="Saved variant name.")  # type: ignore[assignment]
    launch_ids = serializers.ListField(child=serializers.UUIDField(), help_text="Scout runs in this variant.")
    model = serializers.CharField(help_text="Saved scout model.")
    reasoning_effort = serializers.CharField(help_text="Saved reasoning effort.")
    skill_body_sha256 = serializers.CharField(help_text="Hash of the saved scout instructions.")


class ScoutTrialComparisonSerializer(serializers.Serializer):
    comparison_id = serializers.UUIDField(help_text="Comparison and automatic evaluation identity.")
    config_id = serializers.UUIDField(help_text="Source scout configuration.")
    context_id = serializers.UUIDField(help_text="Frozen starting context shared by every run.")
    created_at = serializers.DateTimeField(help_text="Time the comparison was saved.")
    baseline_variant_id = serializers.UUIDField(help_text="Baseline variant identity.")
    rubric_revision = serializers.IntegerField(help_text="Reviewed rubric revision frozen before the runs started.")
    variants = ScoutTrialComparisonVariantSerializer(many=True, help_text="Saved variant groups and runtime settings.")
    status = serializers.ChoiceField(
        choices=["not_started", "starting", "running", "judging", "completed", "failed", "unknown"],
        help_text="Comparison lifecycle, including automatic judging.",
    )
    error = serializers.CharField(allow_null=True, help_text="Sanitized comparison error, if any.")
    evaluation = ScoutTrialEvaluationSerializer(
        allow_null=True, help_text="Saved evaluation and report when available."
    )


class ScoutTrialComparisonHistorySerializer(serializers.Serializer):
    results = ScoutTrialComparisonSerializer(many=True, help_text="This operator's most recent saved comparisons.")
    has_more = serializers.BooleanField(help_text="Whether more comparisons exist than the requested limit.")
