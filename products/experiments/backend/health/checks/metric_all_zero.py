"""
Metrics that read zero in every variant, so the results page shows "Not enough data yet" at any sample size. Pure
functions, no I/O.

The stored result holds only the zero, so the check names a cause only where the metric's settings or the project's
event definitions show one, and needs no scan of the events. In every other case the words say what the zero means and
name the usual cause: the exposure and the event come from different SDKs under different ids, so the people who send
the event aren't the people who were exposed.
"""

from collections.abc import Mapping
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
from products.experiments.backend.hogql_queries.base_query_utils import (
    conversion_window_to_seconds,
    quantile_exact_position,
)

# pinned: the subcodes and `evidence.metric_N_cause`. The page sends the subcode as `finding_subcode` on its events.
BLANK_EVENT = "blank_event"
EVENT_STOPPED = "event_stopped"
OUTLIER_BOUND = "outlier_bound"

# With less of either, most zeros are outcomes that take time, so neither gate works alone.
MIN_EXPOSURES = 1000
MIN_HOURS_OF_DATA = 72
# An empty event name or a bound of 0 reads 0 at any traffic, so these causes need only enough data to read.
MIN_EXPOSURES_WITH_A_SETTING_CAUSE = 100
MIN_HOURS_WITH_A_SETTING_CAUSE = 12

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
        if not _explained_elsewhere(metric, ctx) and (item := _word(metric, ctx, hours_of_data)) is not None
    ]
    if not worded:
        return None
    worded.sort(key=lambda item: (item.metric.role != "primary", item.cause is None))
    # Both sides of a ratio can read zero, and each is its own item.
    count = len({item.metric.metric_id for item in worded})
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


def _explained_elsewhere(metric: ZeroMetric, ctx: HealthContext) -> bool:
    # `metric_event_not_ingested` reports an event the project never received, until the experiment ends.
    # `metric_calculation_failed` and `zero_exposures` need no rule here: a failed metric has no zero to read, and a
    # result with exposures isn't zero exposures.
    return not ctx.has_ended and any(ctx.events_received.get(event) is False for event in metric.events)


def _hours_that_count(metric: ZeroMetric, hours_of_data: float) -> float:
    """The hours of data in which the metric can count an outcome. A retention metric counts a return only from the
    start of its retention window after the start event, so its hours begin there."""
    definition = metric.definition
    start = definition.get("retention_window_start")
    unit = definition.get("retention_window_unit")
    if definition.get("metric_type") != "retention" or start is None or unit is None:
        return hours_of_data
    return hours_of_data - conversion_window_to_seconds(start, FunnelConversionWindowTimeUnit(unit)) / _SECONDS_PER_HOUR


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
    return handling.get("upper_bound_percentile")


def _values_a_zero_bound_hides(metric: ZeroMetric) -> int:
    """How many exposures can have a value while the upper outlier bound is still 0. Zero without a bound that counts
    zeros, and when the bound picks the largest value."""
    percentile = _upper_bound(metric)
    # The queries compute one bound per breakdown group, and the stored totals don't hold the size of each group.
    if percentile is None or _has_breakdowns(metric):
        return 0
    return metric.exposures - quantile_exact_position(percentile, metric.exposures) - 1


def _has_breakdowns(metric: ZeroMetric) -> bool:
    breakdown_filter = metric.definition.get("breakdownFilter")
    return isinstance(breakdown_filter, Mapping) and bool(breakdown_filter.get("breakdowns"))


def _word(metric: ZeroMetric, ctx: HealthContext, hours_of_data: float) -> _Worded | None:
    """The cause and the words for a metric that passes the gate of its cause, or None."""
    hours = _hours_that_count(metric, hours_of_data)
    reads_zero = _reads_zero(metric)
    readable = metric.exposures >= MIN_EXPOSURES_WITH_A_SETTING_CAUSE and hours >= MIN_HOURS_WITH_A_SETTING_CAUSE
    passes_gates = metric.role == "primary" and metric.exposures >= MIN_EXPOSURES and hours >= MIN_HOURS_OF_DATA
    if metric.has_blank_event:
        if not readable:
            return None
        detail = f"{reads_zero} It has an event with an empty name, which matches no events. Edit the metric and choose an event."
        return _Worded(metric=metric, cause=BLANK_EVENT, detail=detail)
    if metric.stopped_events:
        # An event that stopped before launch sends no value for a bound to clamp, so the bound is no cause here.
        if not passes_gates:
            return None
        return _Worded(metric=metric, cause=EVENT_STOPPED, detail=f"{reads_zero} {_stopped(metric, ctx)}")
    hidden = _values_a_zero_bound_hides(metric)
    if hidden > 0 and readable:
        return _Worded(metric=metric, cause=OUTLIER_BOUND, detail=f"{reads_zero} {_bound(hidden, metric.exposures)}")
    if passes_gates:
        return _Worded(metric=metric, cause=None, detail=reads_zero)
    return None


def _reads_zero(metric: ZeroMetric) -> str:
    subject = f'{metric.role} metric "{metric.name}"'
    subject = f"The {subject}" if metric.ratio_side is None else f"The {metric.ratio_side} of the {subject}"
    # A retention result counts only the exposed users who did its start event.
    counted = "users who did its start event" if metric.definition.get("metric_type") == "retention" else "exposures"
    earlier = (
        f" {metric.reached_earlier_step:,} reached an earlier step, but nobody finished the funnel."
        if metric.reached_earlier_step
        else ""
    )
    return f"{subject} reads 0 for all {metric.exposures:,} {counted}, in every variant.{earlier}"


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


def _bound(hidden: int, exposures: int) -> str:
    return (
        f"Its upper outlier bound is taken over all {exposures:,} exposures, including those with no value. When at "
        f"most {hidden:,} of them have a value, the bound is 0, so every value becomes 0. Turn on {_BOUND_LABEL} on "
        "the metric."
    )


def _detail(worded: list[_Worded]) -> str:
    sentences = [item.detail for item in worded]
    without_a_cause = [item.metric for item in worded if item.cause is None]
    if without_a_cause:
        sentences.extend(_usual_causes(without_a_cause))
    return " ".join(dict.fromkeys(sentences))


def _usual_causes(metrics: list[ZeroMetric]) -> list[str]:
    events = tuple(dict.fromkeys(event for metric in metrics for event in metric.events))
    tables = tuple(dict.fromkeys(table for metric in metrics for table in metric.warehouse_tables))
    # A metric on actions names no event, but it still reads events.
    reads_events = bool(events) or any(not metric.warehouse_tables for metric in metrics)
    counted = joined([*(["an event"] if reads_events else []), *(["a warehouse row"] if tables else [])], "or")
    sentences = [
        f"PostHog counts {counted} only for the person or group that was exposed, and only after their first exposure."
    ]
    if reads_events:
        event = f"the event {quoted(events)}" if len(events) == 1 else "the metric events"
        sentences.append(
            f"Check that your code sends {event} with the same ID as the exposure, which a server-side event or another "
            "SDK often doesn't."
        )
    if tables:
        sentences.append(
            f"Check that the data warehouse join key of {quoted(tables)} holds the same ID as the exposure."
        )
    if any(metric.has_filters for metric in metrics):
        sentences.append("Check that the metric filters match the data you send.")
    thresholds = [
        f'"{metric.name}" ({threshold:g})'
        for metric in metrics
        if (threshold := metric.definition.get("threshold")) is not None
        and metric.definition.get("metric_type") == "mean"
    ]
    if thresholds:
        sentences.append(f"Check that the exposed people or groups can reach the threshold of {joined(thresholds)}.")
    sentences.append("A rare outcome can also read 0 at this sample size.")
    return sentences


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
        evidence[f"metric_{number}_side"] = item.metric.ratio_side
        evidence[f"metric_{number}_exposures"] = item.metric.exposures
        evidence[f"metric_{number}_cause"] = item.cause
    return evidence
