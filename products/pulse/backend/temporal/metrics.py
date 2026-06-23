"""Prometheus counters for the Pulse pipeline. No-op outside Temporal context."""

from temporalio import activity, workflow
from temporalio.common import MetricMeter

Attributes = dict[str, str | int | float | bool]


def _meter(attributes: Attributes | None = None) -> MetricMeter | None:
    """Return the active meter, or None when called outside a workflow/activity."""
    if activity.in_activity():
        meter = activity.metric_meter()
    elif workflow.in_workflow():
        meter = workflow.metric_meter()
    else:
        return None
    return meter.with_additional_attributes(attributes) if attributes else meter


def increment_dispatch_outcome(outcome: str, *, count: int = 1) -> None:
    """Dispatcher counters: eligible / dispatched / deduped / failed."""
    meter = _meter({"outcome": outcome})
    if meter is None:
        return
    meter.create_counter("pulse_dispatch_outcome", "Pulse dispatcher team outcomes").add(count)


def increment_scan_outcome(outcome: str, *, count: int = 1) -> None:
    """Per-team scan counters: delivered / failed."""
    meter = _meter({"outcome": outcome})
    if meter is None:
        return
    meter.create_counter("pulse_scan_outcome", "Pulse scan delivery outcomes").add(count)


def increment_detection_outcome(outcome: str, *, count: int = 1) -> None:
    """Per-candidate detection counters: failed (a candidate's query or evaluation raised).

    Lets an all-candidates-errored scan be told apart from a genuinely quiet one — both surface
    zero findings, but only the former increments here.
    """
    meter = _meter({"outcome": outcome})
    if meter is None:
        return
    meter.create_counter("pulse_detection_outcome", "Pulse per-candidate detection outcomes").add(count)


def increment_scout_anomaly_outcome(outcome: str, *, count: int = 1) -> None:
    """Per-anomaly adapter outcomes.

    resolved — built a Finding. unresolvable_insight — best-effort short_id missing or doesn't load (the
    signal that the scout emit contract should be hardened later). unsupported_query_kind — insight loaded
    but isn't a TrendsQuery, so it can't be re-scored. query_failed — the trends re-score raised. no_series —
    insufficient data. zero_baseline — the re-scored baseline median is 0, so a percentage change is
    undefined. adapter_error — an unexpected per-anomaly failure the loop caught so the scan could
    continue."""
    meter = _meter({"outcome": outcome})
    if meter is None:
        return
    meter.create_counter("pulse_scout_anomaly_outcome", "Pulse scout-anomaly adapter outcomes").add(count)


def increment_anomaly_source_failure(source: str, *, count: int = 1) -> None:
    """A whole AnomalySource failed and the scan degraded to the remaining sources' findings.

    Without this, a half-degraded digest (e.g. the scout source threw but deterministic findings still
    delivered) is metrically indistinguishable from a healthy scan — scan_outcome stays "delivered"."""
    meter = _meter({"source": source})
    if meter is None:
        return
    meter.create_counter("pulse_anomaly_source_failure", "Pulse whole-source failures (scan degraded)").add(count)


def record_finding_count(count: int) -> None:
    """Number of findings persisted in a delivered digest."""
    meter = _meter()
    if meter is None:
        return
    meter.create_counter("pulse_finding_count", "Findings persisted per delivered digest").add(count)
