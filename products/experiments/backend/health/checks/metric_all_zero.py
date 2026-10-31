"""
Metrics that read zero in every variant, so the results page shows "Not enough data yet" or a bare "Error" at any sample
size. Pure functions, no I/O.

The stored result holds only the zero, so the check names a cause only where the metric's settings or the project's
event definitions show one, and needs no scan of the events. In every other case the words say what the zero means and
name the usual cause: the exposure and the event come from different SDKs under different ids, so the people who send
the event aren't the people who were exposed.
"""

from typing import assert_never

from posthog.schema import FunnelConversionWindowTimeUnit

from posthog.dataclasses import frozen

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.checks.events_received import joined, quoted
from products.experiments.backend.health.context import HealthContext, ZeroMetric
from products.experiments.backend.health.skips import (
    NOT_ON_ARCHIVED,
    RUNS_AFTER_LAUNCH,
    CheckOutcome,
    no_calculated_metric,
    not_applicable,
    not_checked,
)
from products.experiments.backend.health.split_changes import format_change_time
from products.experiments.backend.hogql_queries.base_query_utils import conversion_window_to_seconds

# pinned: the finding's subcodes. The page sends them as `finding_subcode` on the health finding events.
BLANK_EVENT = "blank_event"
EVENT_STOPPED = "event_stopped"
OUTLIER_BOUND = "outlier_bound"

# With less of either, most zeros are outcomes that take time, so neither gate works alone.
MIN_EXPOSURES = 1000
MIN_HOURS_OF_DATA = 72
# A bound that counts zeros clamps a rare outcome at any traffic, so its cause doesn't need the gates above.
MIN_EXPOSURES_WITH_OUTLIER_BOUND = 100
MIN_HOURS_WITH_OUTLIER_BOUND = 12

# A change to these settings recalculates the metric over the events up to the end, so they stay a warning after it.
_FIXED_BY_A_SETTING = frozenset({BLANK_EVENT, OUTLIER_BOUND})
_BOUND_LABEL = '"Ignore zeros when calculating upper bound"'
_SECONDS_PER_HOUR = 3600


@frozen
class _Worded:
    metric: ZeroMetric
    # None when the settings and the event definitions show no cause.
    cause: str | None
    # Without the usual causes, which the finding says once for all the metrics that have no cause.
    detail: str


def metric_all_zero(ctx: HealthContext) -> CheckOutcome:
    if ctx.archived:
        return not_applicable(NOT_ON_ARCHIVED)
    if not ctx.is_launched:
        return not_applicable(RUNS_AFTER_LAUNCH)
    calculation = ctx.latest_calculation
    if calculation is None:
        return not_checked("Couldn't check because the latest calculation couldn't be read")
    if calculation.metric_count == 0:
        return no_calculated_metric(ctx)
    hours_of_data = calculation.hours_of_data
    if calculation.finished_at is None or hours_of_data is None:
        return not_applicable("Runs once a calculation of the metrics has finished")
    worded = [
        item
        for metric in calculation.zero_metrics
        if not _explained_elsewhere(metric, ctx, hours_of_data)
        and (item := _word(metric, ctx, hours_of_data)) is not None
    ]
    if not worded:
        return None
    worded.sort(key=lambda item: (item.metric.role != "primary", item.cause is None))
    count = len(worded)
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.METRIC_ALL_ZERO,
        subcode=worded[0].cause,
        severity=_severity(worded, ctx),
        title=f"{count} metrics read zero in every variant" if count > 1 else "A metric reads zero in every variant",
        detail=_detail(worded),
        evidence=_evidence(worded),
        # No action opens a given metric.
        actions=(),
        diagnostic_ref=None,
    )


def _explained_elsewhere(metric: ZeroMetric, ctx: HealthContext, hours_of_data: float) -> bool:
    # `metric_event_not_ingested` reports an event the project never received. `metric_calculation_failed` and
    # `zero_exposures` need no rule here: a failed metric has no zero to read, and a result with exposures isn't zero
    # exposures.
    if any(ctx.events_received.get(event) is False for event in metric.events):
        return True
    return _retention_window_not_reached(metric, hours_of_data)


def _retention_window_not_reached(metric: ZeroMetric, hours_of_data: float) -> bool:
    """Whether nobody can have returned yet, because the data ends before the retention window of the first exposed
    user starts."""
    definition = metric.definition
    start = definition.get("retention_window_start")
    unit = definition.get("retention_window_unit")
    if definition.get("metric_type") != "retention" or start is None or unit is None:
        return False
    window_start = conversion_window_to_seconds(start, FunnelConversionWindowTimeUnit(unit))
    return hours_of_data * _SECONDS_PER_HOUR < window_start


def _upper_bound(metric: ZeroMetric) -> float | None:
    """The percentile of the upper outlier bound over the side that reads zero, when the bound counts zeros."""
    definition = metric.definition
    match metric.ratio_side:
        case None:
            handling = definition if definition.get("metric_type") == "mean" else None
        case "numerator":
            handling = definition.get("numerator_outlier_handling")
        case "denominator":
            handling = definition.get("denominator_outlier_handling")
        case _:
            assert_never(metric.ratio_side)
    if not handling or handling.get("ignore_zeros"):
        return None
    percentile = handling.get("upper_bound_percentile")
    # The percentile 1 is the largest value, so it clamps nothing.
    return percentile if percentile is not None and percentile < 1 else None


def _word(metric: ZeroMetric, ctx: HealthContext, hours_of_data: float) -> _Worded | None:
    """The cause and the words for a metric that passes the gate of its cause, or None."""
    reads_zero = _reads_zero(metric)
    passes_gates = metric.role == "primary" and metric.exposures >= MIN_EXPOSURES and hours_of_data >= MIN_HOURS_OF_DATA
    if metric.has_blank_event or metric.stopped_events:
        if not passes_gates:
            return None
        if metric.has_blank_event:
            detail = f"{reads_zero} It has an event with an empty name, which matches no events. Edit the metric and choose an event."
            return _Worded(metric=metric, cause=BLANK_EVENT, detail=detail)
        return _Worded(metric=metric, cause=EVENT_STOPPED, detail=f"{reads_zero} {_stopped(metric, ctx)}")
    percentile = _upper_bound(metric)
    if (
        percentile is not None
        and metric.exposures >= MIN_EXPOSURES_WITH_OUTLIER_BOUND
        and hours_of_data >= MIN_HOURS_WITH_OUTLIER_BOUND
    ):
        return _Worded(metric=metric, cause=OUTLIER_BOUND, detail=f"{reads_zero} {_bound(percentile)}")
    if passes_gates:
        return _Worded(metric=metric, cause=None, detail=reads_zero)
    return None


def _reads_zero(metric: ZeroMetric) -> str:
    subject = f'{metric.role} metric "{metric.name}"'
    subject = f"The {subject}" if metric.ratio_side is None else f"The {metric.ratio_side} of the {subject}"
    earlier = (
        f" {metric.reached_earlier_step:,} reached an earlier step, but nobody finished the funnel."
        if metric.reached_earlier_step
        else ""
    )
    return f"{subject} reads 0 for all {metric.exposures:,} exposures, in every variant.{earlier}"


def _stopped(metric: ZeroMetric, ctx: HealthContext) -> str:
    stopped = [
        (event, format_change_time(last_seen, ctx.team_timezone)) for event, last_seen in metric.stopped_events.items()
    ]
    if len(stopped) == 1:
        event, last_seen = stopped[0]
        return (
            f'The event "{event}" last arrived on {last_seen}, before the experiment started. Check that your code '
            "still sends it, or edit the metric to use an event that still arrives."
        )
    named = joined([f'"{event}" on {last_seen}' for event, last_seen in stopped])
    return (
        f"These events last arrived before the experiment started: {named}. Check that your code still sends them, or "
        "edit the metric to use events that still arrive."
    )


def _bound(percentile: float) -> str:
    share = round((1 - percentile) * 100, 2)
    return (
        f"Its upper outlier bound is taken over all exposures, including those with no value. When fewer than {share:g}% "
        f"have a value, the bound is 0, so every value becomes 0. Turn on {_BOUND_LABEL} on the metric."
    )


def _detail(worded: list[_Worded]) -> str:
    sentences = [item.detail for item in worded]
    without_a_cause = [item.metric for item in worded if item.cause is None]
    if without_a_cause:
        sentences.append(_usual_causes(without_a_cause))
    return " ".join(dict.fromkeys(sentences))


def _usual_causes(metrics: list[ZeroMetric]) -> str:
    events = tuple(dict.fromkeys(event for metric in metrics for event in metric.events))
    event = f"the event {quoted(events)}" if len(events) == 1 else "the metric events"
    filters = " Check that the metric filters match the events you send." if any(m.has_filters for m in metrics) else ""
    return (
        "PostHog counts an event only for the person or group that was exposed, and only after their first exposure. "
        f"Check that your code sends {event} with the same ID as the exposure, which a server-side event or another "
        f"SDK often doesn't.{filters} A rare outcome can also read 0 at this sample size."
    )


def _severity(worded: list[_Worded], ctx: HealthContext) -> ExperimentHealthFindingSeverity:
    primary = [item for item in worded if item.metric.role == "primary"]
    # After the end, no change to the code can add events. A setting can still bring back the results.
    if primary and (not ctx.has_ended or any(item.cause in _FIXED_BY_A_SETTING for item in primary)):
        return ExperimentHealthFindingSeverity.WARNING
    return ExperimentHealthFindingSeverity.INFO


def _evidence(worded: list[_Worded]) -> dict[str, str | int | None]:
    evidence: dict[str, str | int | None] = {}
    for number, item in enumerate(worded, start=1):
        evidence[f"metric_{number}"] = item.metric.name
        evidence[f"metric_{number}_role"] = item.metric.role
        evidence[f"metric_{number}_exposures"] = item.metric.exposures
        evidence[f"metric_{number}_cause"] = item.cause
    return evidence
