"""
Metrics that read an event the project never received. Pure functions, no I/O.

Saving a metric checks its event names, but a caller can waive that check, a shared metric and a launch skip it, and
an update checks only the names it adds. A metric on such an event has no data to compare the variants.
"""

from products.experiments.backend.facade.contracts import ExperimentHealthFinding, ExperimentHealthFindingCode
from products.experiments.backend.health.checks.events_received import joined, not_received_severity, quoted
from products.experiments.backend.health.context import HealthContext, MetricEvents
from products.experiments.backend.health.skips import (
    NOT_AFTER_END,
    NOT_ON_ARCHIVED,
    CheckOutcome,
    not_applicable,
    not_checked,
)


def metric_event_not_ingested(ctx: HealthContext) -> CheckOutcome:
    if ctx.archived:
        return not_applicable(NOT_ON_ARCHIVED)
    if ctx.has_ended:
        return not_applicable(NOT_AFTER_END)
    names = {event for metric in ctx.metric_events for event in metric.events}
    if not names:
        return not_applicable("Runs once a metric uses an event")
    if not names & ctx.events_received.keys():
        return not_checked("Couldn't check because PostHog keeps no record of these event names")
    affected = [
        (metric, missing)
        for metric in ctx.metric_events
        if (missing := tuple(event for event in metric.events if ctx.events_received.get(event) is False))
    ]
    if not affected:
        return None
    events = sorted({event for _, missing in affected for event in missing})
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.METRIC_EVENT_NOT_INGESTED,
        subcode=None,
        severity=not_received_severity(ctx, affects_results=any(metric.role == "primary" for metric, _ in affected)),
        title=_title(len(affected), len(events)),
        detail=f"{_what(affected)} {_advice(ctx, len(events))}",
        evidence=_evidence(affected),
        # No action opens a given metric.
        actions=(),
        diagnostic_ref=None,
    )


def _evidence(affected: list[tuple[MetricEvents, tuple[str, ...]]]) -> dict[str, str]:
    evidence: dict[str, str] = {}
    for number, (metric, missing) in enumerate(affected, start=1):
        evidence[f"metric_{number}"] = metric.name
        evidence[f"metric_{number}_role"] = metric.role
        evidence[f"metric_{number}_events"] = ", ".join(missing)
    return evidence


def _title(metric_count: int, event_count: int) -> str:
    if metric_count > 1:
        return f"{metric_count} metrics use events this project hasn't received"
    return f"A metric uses {'an event' if event_count == 1 else 'events'} this project hasn't received"


def _what(affected: list[tuple[MetricEvents, tuple[str, ...]]]) -> str:
    if len(affected) == 1:
        metric, missing = affected[0]
        event, arrives = ("the event", "it arrives") if len(missing) == 1 else ("the events", "they arrive")
        return (
            f'The {metric.role} metric "{metric.name}" uses {event} {quoted(missing)}, which this project hasn\'t '
            f"received yet. Until {arrives}, the metric can't compare the variants."
        )
    uses = [f'the {metric.role} metric "{metric.name}" uses {quoted(missing)}' for metric, missing in affected]
    return (
        f"These metrics use events this project hasn't received yet: {joined(uses)}. Until those events arrive, "
        "these metrics can't compare the variants."
    )


def _advice(ctx: HealthContext, event_count: int) -> str:
    if not ctx.is_launched:
        return f"Launch the experiment after your code starts sending {'it' if event_count == 1 else 'them'}."
    names = "this name" if event_count == 1 else "these names"
    return f"Check that your code sends {'the event' if event_count == 1 else 'the events'} with exactly {names}."
