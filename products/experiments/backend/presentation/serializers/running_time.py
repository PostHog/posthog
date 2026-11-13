"""Serializers for the running time calculator and the running time target of an experiment."""

import math
from typing import Any

from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from products.experiments.backend.facade.contracts import RunningTimeMode
from products.experiments.backend.running_time_calculator import METRIC_TYPE_CHOICES


class FiniteFloatField(serializers.FloatField):
    """A float field that rejects "nan" and "inf". `FloatField` accepts both, no estimate can use them, and JSON can't
    carry them back."""

    def to_internal_value(self, data: Any) -> float:
        value = super().to_internal_value(data)
        if not math.isfinite(value):
            self.fail("invalid")
        return value


class RunningTimeBaselineStatsSerializer(serializers.Serializer):
    """Raw control-group statistics the calculator uses to derive a baseline value and variance.

    Supply this when you want the server to compute the baseline value and (for ratio/retention)
    the delta-method variance, instead of passing `baseline_value`/`variance` directly.
    """

    number_of_samples = serializers.IntegerField(
        min_value=0, help_text="Number of control-group samples (users/units) observed."
    )
    sum = FiniteFloatField(
        help_text="Sum of the metric values across the control group (for funnels, the numerator/conversions)."
    )
    sum_squares = FiniteFloatField(
        required=False,
        default=0.0,
        help_text=(
            "Sum of squared metric values. Mean metrics read their variance from it, and ratio/retention metrics need "
            "it. Without it, a mean metric's variance is approximated from the baseline value."
        ),
    )
    denominator_sum = FiniteFloatField(
        required=False,
        allow_null=True,
        help_text="Sum of the denominator values. Required for ratio/retention metrics.",
    )
    denominator_sum_squares = FiniteFloatField(
        required=False, allow_null=True, help_text="Sum of squared denominator values (ratio/retention variance)."
    )
    numerator_denominator_sum_product = FiniteFloatField(
        required=False,
        allow_null=True,
        help_text="Sum of numerator×denominator products, used for the delta-method covariance term.",
    )
    step_counts = serializers.ListField(
        child=FiniteFloatField(),
        required=False,
        help_text="Per-step counts for funnel metrics; the last entry is the final-step count.",
    )


class RunningTimeCalculationInputSerializer(serializers.Serializer):
    """Inputs for estimating the recommended sample size and running time of an experiment."""

    metric_type = serializers.ChoiceField(
        choices=METRIC_TYPE_CHOICES,
        help_text=(
            "Metric type to size for. 'funnel' for conversion rates, 'mean_count' for event counts per user, "
            "'mean_sum_or_avg' for summed property values per user, 'ratio' and 'retention' for ratio-style metrics "
            "(both require baseline_stats or an explicit variance)."
        ),
    )
    minimum_detectable_effect = FiniteFloatField(
        min_value=0,
        help_text="Smallest relative change to detect, as a percentage (e.g. 5 means a 5% lift). Must be > 0.",
    )
    number_of_variants = serializers.IntegerField(
        required=False,
        default=2,
        min_value=2,
        max_value=100,
        help_text="Total number of variants including control (default 2, at most 100).",
    )
    exposure_rate_per_day = FiniteFloatField(
        required=False,
        allow_null=True,
        min_value=0,
        help_text="Expected exposures per day. When provided, the response includes the recommended running time.",
    )
    baseline_value = FiniteFloatField(
        required=False,
        allow_null=True,
        help_text=(
            "Baseline metric value: conversion rate as a fraction 0-1 (funnel), average per user (mean), or the ratio "
            "(ratio/retention). Provide this or baseline_stats."
        ),
    )
    variance = FiniteFloatField(
        required=False,
        allow_null=True,
        help_text=(
            "Pre-computed variance per user. Provide this or baseline_stats when metric_type is ratio/retention and "
            "baseline_value is given directly. When given, it replaces the variance the calculator derives for any "
            "metric type, including p(1-p) for funnels."
        ),
    )
    baseline_stats = RunningTimeBaselineStatsSerializer(
        required=False,
        allow_null=True,
        help_text="Raw control-group statistics. When provided, the server derives baseline_value and variance.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("minimum_detectable_effect", 0) <= 0:
            raise ValidationError({"minimum_detectable_effect": "Must be greater than 0."})

        has_baseline_value = attrs.get("baseline_value") is not None
        has_baseline_stats = attrs.get("baseline_stats") is not None
        if not has_baseline_value and not has_baseline_stats:
            raise ValidationError("Provide either baseline_value or baseline_stats.")

        if attrs["metric_type"] in ("ratio", "retention"):
            # A baseline value and variance must both be available. Pass them directly, or supply
            # baseline_stats with denominator_sum so the server can derive them — without it both
            # derivations return None and the endpoint silently responds with all-null results.
            has_variance = attrs.get("variance") is not None
            if not (has_baseline_value and has_variance):
                stats = attrs.get("baseline_stats")
                if not stats:
                    raise ValidationError(
                        "Ratio and retention metrics require baseline_stats, or both baseline_value and variance."
                    )
                if not stats.get("denominator_sum"):
                    raise ValidationError(
                        {"baseline_stats": {"denominator_sum": "Required to size ratio and retention metrics."}}
                    )

        return attrs


class RunningTimeCalculationResultSerializer(serializers.Serializer):
    """Estimated sample size and running time for the given inputs."""

    baseline_value = serializers.FloatField(
        allow_null=True, help_text="Baseline metric value used in the calculation (echoed or derived from stats)."
    )
    variance = serializers.FloatField(
        allow_null=True, help_text="Variance used in the calculation; null for funnel metrics (implicit in p(1-p))."
    )
    recommended_sample_size = serializers.IntegerField(
        allow_null=True, help_text="Total recommended sample size across all variants. Null if inputs are insufficient."
    )
    recommended_running_time_days = serializers.IntegerField(
        allow_null=True,
        help_text="Estimated days to reach the recommended sample size. Null when exposure_rate_per_day is omitted.",
    )


class RunningTimeTargetQuerySerializer(serializers.Serializer):
    mode = serializers.ChoiceField(
        required=False,
        choices=RunningTimeMode.choices,
        help_text=(
            "The running time mode to size the target for. Defaults to the experiment's saved mode. 'automatic' sizes "
            "it from the results, also for an experiment saved in manual mode."
        ),
    )


class DetectableEffectCheckpointSerializer(serializers.Serializer):
    weeks_since_launch = serializers.IntegerField(help_text="The week mark, in whole weeks since launch.")
    detectable_effect = serializers.FloatField(
        help_text="The smallest relative change, as a percentage, that the exposures by this week mark can detect."
    )


class RunningTimeOutlookSerializer(serializers.Serializer):
    """What the experiment can detect over time, at its exposure rate so far."""

    days_since_launch = serializers.FloatField(help_text="Days since the experiment launched, with fractions.")
    exposures_per_day = serializers.FloatField(
        help_text=(
            "Exposures that count toward the target, per day from launch to the end of the window the current "
            "results cover."
        )
    )
    detectable_effect_now = serializers.FloatField(
        help_text="The smallest relative change, as a percentage, that the exposures so far can detect."
    )
    upcoming_checkpoints = DetectableEffectCheckpointSerializer(
        many=True,
        help_text=(
            "Up to three week marks after today, out of weeks 1, 2, 4, 6, 8, 12, 16, 26 and 52, with the change each "
            "can detect at the exposure rate so far."
        ),
    )
    reachable_effect = serializers.FloatField(
        help_text=(
            "The smallest relative change, as a percentage, that the experiment can detect within four weeks from "
            "today. A target for a smaller change is out of reach."
        )
    )


class RunningTimeTargetSerializer(serializers.Serializer):
    """The target sample of the experiment's running time estimate."""

    minimum_detectable_effect = serializers.FloatField(
        help_text="The relative change, as a percentage, that the target sample is sized to detect."
    )
    recommended_sample_size = serializers.IntegerField(
        allow_null=True,
        help_text=(
            "Exposures needed across the analyzed variants, so that the comparison of each variant with the control "
            "can detect the minimum detectable effect at the analysis's confidence level and 80% power. In manual running time mode, "
            "the saved target. Otherwise sized from the first primary metric's current result, with the variance the "
            "analysis uses and the flag's traffic split. Null when no result can size it yet. The variances come from "
            "the result and don't depend on the effect, so the sample scales with 1 / effect²: the target for another "
            "effect is recommended_sample_size × (minimum_detectable_effect / effect)²."
        ),
    )
    current_sample_size = serializers.IntegerField(
        allow_null=True,
        help_text=(
            "Exposures so far that count toward the target: the control's and those of the variants that get "
            "traffic. A variant at 0% does not count. Null in manual mode, and when no result can size the target."
        ),
    )
    outlook = RunningTimeOutlookSerializer(
        allow_null=True,
        help_text=(
            "What the experiment can detect over time, on the same curve the target is sized on. Null in manual mode, "
            "before launch, when the current results cover less than 0.1 days, and when no result can size the target."
        ),
    )
