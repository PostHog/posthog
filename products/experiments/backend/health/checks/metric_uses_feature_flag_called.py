"""
Metrics that read `$feature_flag_called` events. Pure functions, no I/O.

PostHog is reducing how long it keeps these events, so a metric on them loses its earlier data. A metric that matches
the event through an action step isn't found, because the context carries no action definitions.
"""

from posthog.hogql.constants import FLAG_CALLED_EVENT

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthValueKey,
)
from products.experiments.backend.health.checks.events_received import joined
from products.experiments.backend.health.context import HealthContext, MetricEvents
from products.experiments.backend.health.skips import (
    NEEDS_METRIC_EVENT,
    NOT_AFTER_END,
    NOT_ON_ARCHIVED,
    CheckOutcome,
    CheckValues,
    not_applicable,
)
from products.experiments.backend.hogql_queries.exposure_query_logic import EXPERIMENT_EXPOSURE_EVENT


def metric_uses_feature_flag_called_values(ctx: HealthContext) -> CheckValues:
    if not ctx.flag_calls_kept_shorter or ctx.archived or ctx.has_ended:
        return {}
    return {
        ExperimentHealthValueKey.PRIMARY_METRIC_COUNT: ctx.primary_metric_count,
        ExperimentHealthValueKey.SECONDARY_METRIC_COUNT: ctx.secondary_metric_count,
    }


def metric_uses_feature_flag_called(ctx: HealthContext) -> CheckOutcome:
    if not ctx.flag_calls_kept_shorter:
        return not_applicable("Runs only on PostHog Cloud")
    if ctx.archived:
        return not_applicable(NOT_ON_ARCHIVED)
    # An experiment that ran before EXPERIMENT_EXPOSURE_EVENT_CUTOFF has no `$experiment_exposure` events, so after the
    # end the advice to switch can leave the metric without data.
    if ctx.has_ended:
        return not_applicable(NOT_AFTER_END)
    if not ctx.metric_events:
        return not_applicable(NEEDS_METRIC_EVENT)
    affected = [metric for metric in ctx.metric_events if FLAG_CALLED_EVENT in metric.events]
    if not affected:
        return None
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.METRIC_USES_FEATURE_FLAG_CALLED,
        subcode=None,
        severity=ExperimentHealthFindingSeverity.WARNING
        if any(metric.role == "primary" for metric in affected)
        else ExperimentHealthFindingSeverity.INFO,
        title=_title(len(affected)),
        detail=_detail(affected),
        evidence=_evidence(affected),
        # No action opens a given metric.
        actions=(),
        diagnostic_ref=None,
    )


def _evidence(affected: list[MetricEvents]) -> dict[str, str]:
    evidence: dict[str, str] = {}
    for number, metric in enumerate(affected, start=1):
        evidence[f"metric_{number}"] = metric.name
        evidence[f"metric_{number}_role"] = metric.role
    return evidence


def _title(metric_count: int) -> str:
    if metric_count > 1:
        return f'{metric_count} metrics use the event "{FLAG_CALLED_EVENT}"'
    return f'A metric uses the event "{FLAG_CALLED_EVENT}"'


def _detail(affected: list[MetricEvents]) -> str:
    if len(affected) == 1:
        metric = affected[0]
        return (
            f'The {metric.role} metric "{metric.name}" uses the event "{FLAG_CALLED_EVENT}". PostHog is reducing how '
            "long it keeps this event, so the metric can lose its earlier data. Switch the metric to the event "
            f'"{EXPERIMENT_EXPOSURE_EVENT}" to keep it working.'
        )
    names = joined([f'the {metric.role} metric "{metric.name}"' for metric in affected])
    return (
        f'These metrics use the event "{FLAG_CALLED_EVENT}": {names}. PostHog is reducing how long it keeps this '
        "event, so these metrics can lose their earlier data. Switch them to the event "
        f'"{EXPERIMENT_EXPOSURE_EVENT}" to keep them working.'
    )
