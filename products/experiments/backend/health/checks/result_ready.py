"""
A running experiment whose primary metric has its answer: a variant that every stored result has shown as significant
for some days, or the planned sample without a significant variant. Pure functions, no I/O.

The finding states what the stored results show and offers to end the experiment. It doesn't judge the statistics: the
early significance check does that, and this check stays quiet while that check asks to wait.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from posthog.dataclasses import frozen

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthValueKey,
)
from products.experiments.backend.health.checks.early_significance import early_significance
from products.experiments.backend.health.context import HealthContext, PrimaryMetric
from products.experiments.backend.health.skips import (
    NEEDS_PRIMARY_METRIC,
    NEEDS_PRIMARY_METRIC_RESULTS,
    NOT_AFTER_END,
    NOT_ON_ARCHIVED,
    PRIMARY_METRIC_UNREADABLE,
    RUNS_AFTER_LAUNCH,
    CheckOutcome,
    CheckSkip,
    CheckValues,
    not_applicable,
    not_checked,
)
from products.experiments.backend.logic.result_stats import MetricResultStats
from products.experiments.backend.metric_calculation.results import SignificanceHistory

# pinned: sent as `finding_subcode` on the health finding events.
STAYED_SIGNIFICANT = "stayed_significant"
TARGET_REACHED_NOT_SIGNIFICANT = "target_reached_not_significant"

SIGNIFICANT_DAYS = 3
REPORTED_BY_EARLY_SIGNIFICANCE = "The early significance check asks to wait for the planned sample"


@frozen
class _Readout:
    metric: PrimaryMetric
    result: MetricResultStats
    samples: int
    significance: SignificanceHistory


def result_ready_values(ctx: HealthContext) -> CheckValues:
    readout = _readout(ctx)
    if isinstance(readout, CheckSkip):
        return {}
    earliest = min(readout.significance.significant_since.values(), default=None)
    return {
        ExperimentHealthValueKey.METRIC_NAME: readout.metric.name,
        ExperimentHealthValueKey.SAMPLE_COUNT: readout.samples,
        ExperimentHealthValueKey.PLANNED_SAMPLE_COUNT: readout.metric.target.recommended_sample_size,
        **(
            {ExperimentHealthValueKey.SIGNIFICANT_SINCE_AT: earliest.astimezone(UTC).isoformat()}
            if earliest is not None
            else {}
        ),
    }


def _readout(ctx: HealthContext) -> _Readout | CheckSkip:
    """The current result of the primary metric and its significance history, or why the check doesn't look."""
    if ctx.archived:
        return not_applicable(NOT_ON_ARCHIVED)
    if not ctx.is_launched:
        return not_applicable(RUNS_AFTER_LAUNCH)
    if ctx.has_ended:
        return not_applicable(NOT_AFTER_END)
    if ctx.primary_metric_count == 0:
        return not_applicable(NEEDS_PRIMARY_METRIC)
    metric = ctx.primary_metric
    if metric is None:
        return not_checked(PRIMARY_METRIC_UNREADABLE)
    samples = metric.samples
    if metric.result is None or metric.significance is None or samples is None:
        return not_applicable(NEEDS_PRIMARY_METRIC_RESULTS)
    return _Readout(metric=metric, result=metric.result, samples=samples, significance=metric.significance)


def result_ready(ctx: HealthContext) -> CheckOutcome:
    readout = _readout(ctx)
    if isinstance(readout, CheckSkip):
        return readout
    if isinstance(early_significance(ctx), ExperimentHealthFinding):
        return not_applicable(REPORTED_BY_EARLY_SIGNIFICANCE)
    if readout.significance.significant_since:
        return _stayed_significant(ctx, readout)
    return _target_reached_not_significant(readout)


def _stayed_significant(ctx: HealthContext, readout: _Readout) -> ExperimentHealthFinding | None:
    variant, since = min(readout.significance.significant_since.items(), key=lambda item: (item[1], item[0]))
    duration = readout.significance.current_until - since
    if duration < timedelta(days=SIGNIFICANT_DAYS):
        return None
    days = duration // timedelta(days=1)
    metric = readout.metric
    return _finding(
        subcode=STAYED_SIGNIFICANT,
        title=f'The variant "{variant}" has been significant for {days} days',
        sentences=[
            f'Every result of the primary metric "{metric.name}" since {_format_date(since, ctx.team_timezone)} shows '
            f'the variant "{variant}" as significant.',
            *_sample_sentences(readout),
        ],
        evidence={
            "variant": variant,
            "significant_since": since.astimezone(UTC).isoformat(),
            "days_significant": days,
            **_sample_evidence(readout),
        },
        diagnostic_ref="C9",
    )


def _target_reached_not_significant(readout: _Readout) -> ExperimentHealthFinding | None:
    planned_samples = readout.metric.target.recommended_sample_size
    if planned_samples is None or readout.samples < planned_samples:
        return None
    # A null means that validation stopped the analysis of the variant, so the results don't say it isn't significant.
    variants = readout.result.variants
    if not variants or any(variant.significant is not False for variant in variants):
        return None
    metric = readout.metric
    return _finding(
        subcode=TARGET_REACHED_NOT_SIGNIFICANT,
        title="The planned sample is reached and no variant is significant",
        sentences=[
            f'The current result of the primary metric "{metric.name}" shows no variant as significant.',
            *_sample_sentences(readout),
            f"To detect a difference smaller than {metric.target.minimum_detectable_effect:g}%, keep it running. The "
            "running time settings show what it can detect at each date.",
        ],
        evidence=_sample_evidence(readout),
        diagnostic_ref="C12",
    )


def _sample_sentences(readout: _Readout) -> list[str]:
    target = readout.metric.target
    return [
        f"The results count {readout.samples:,} users"
        + (
            f", and the running time estimate needs about {target.recommended_sample_size:,} to detect a "
            f"{target.minimum_detectable_effect:g}% difference."
            if target.recommended_sample_size is not None
            else "."
        ),
        "If this answers your question, end the experiment. When you end it, you choose whether to roll out a variant.",
    ]


def _sample_evidence(readout: _Readout) -> dict[str, int | float | None]:
    return {
        "samples": readout.samples,
        "planned_samples": readout.metric.target.recommended_sample_size,
        "minimum_detectable_effect": readout.metric.target.minimum_detectable_effect,
    }


def _finding(
    *,
    subcode: str,
    title: str,
    sentences: list[str],
    evidence: Mapping[str, str | int | float | None],
    diagnostic_ref: str,
) -> ExperimentHealthFinding:
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.RESULT_READY,
        subcode=subcode,
        severity=ExperimentHealthFindingSeverity.INFO,
        title=title,
        detail=" ".join(sentences),
        evidence=evidence,
        actions=(ExperimentHealthFindingActionKind.END_EXPERIMENT,),
        diagnostic_ref=diagnostic_ref,
    )


def _format_date(value: datetime, team_timezone: str) -> str:
    return value.astimezone(ZoneInfo(team_timezone)).strftime("%B %-d, %Y")
