"""Resolve the metrics of an experiment across inline and saved/shared metrics.

Calculation (daily timeseries and recalculation), discovery, fingerprints and the API all read a metric's
effective definition from here, so that they calculate and hash the same metric. Workflows pass metric
uuids between activities and re-resolve the definition at the point of use.
"""

from typing import Any, Literal

from posthog.schema import (
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
)

from posthog.dataclasses import frozen

from products.experiments.backend.models.experiment import Experiment, ExperimentToSavedMetric

ExperimentMetric = ExperimentMeanMetric | ExperimentFunnelMetric | ExperimentRatioMetric | ExperimentRetentionMetric

# Modern ExperimentMetric types (kind="ExperimentMetric"). Legacy Trends/Funnels metrics carry no
# metric_type and are filtered out by is_scheduled_metric, so they never reach build_metric.
METRIC_BUILDERS: dict[str, type[ExperimentMetric]] = {
    "mean": ExperimentMeanMetric,
    "funnel": ExperimentFunnelMetric,
    "ratio": ExperimentRatioMetric,
    "retention": ExperimentRetentionMetric,
}

# The daily timeseries activities compute every buildable type. A type the recalculation computes but the
# daily run skips publishes nothing, so the results panel recomputes on first open every morning for the
# experiments that use it; a deliberate future exclusion must subtract from METRIC_BUILDERS explicitly.
DAILY_TIMESERIES_METRIC_TYPES: frozenset[str] = frozenset(METRIC_BUILDERS)


def is_daily_timeseries_metric(metric: dict[str, Any] | None) -> bool:
    return bool(metric and metric.get("metric_type") in DAILY_TIMESERIES_METRIC_TYPES)


MetricRole = Literal["primary", "secondary"]


@frozen
class ResolvedExperimentMetric:
    """A metric as it applies to one experiment: an inline definition, or a saved definition with the
    link's per-experiment overrides applied."""

    uuid: str
    role: MetricRole
    # The effective definition. It is the only dict that may feed `compute_metric_fingerprint` or a
    # query for this metric. A caller that uses the raw saved query calculates a different metric and
    # files or looks up results under a different hash than every other caller.
    definition: dict[str, Any]


def resolve_saved_metric_definition(saved_query: dict[str, Any], metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Apply the per-experiment overrides from the link metadata to a saved query.

    - `breakdowns` always comes from the link. A link without breakdowns has none, whatever the saved
      query holds.
    - `breakdown_limit` replaces the saved value when the link sets it.
    - `breakdownAttributionType` and `breakdownAttributionValue` are one override: when the link sets a
      type, both come from the link, so a link type without a value drops the saved step value. Only
      funnel metrics have these fields.

    The limit and the attribution are breakdown settings, so a link without breakdowns applies neither.
    Applying them would change the fingerprint of a metric whose results cannot change, and the stored
    results of that metric would become unreachable.

    A key that is absent or null is an omitted override. Step 0 is an explicit value.
    """
    metadata = metadata or {}
    resolved = {**saved_query}

    breakdowns = metadata.get("breakdowns") or []
    breakdown_filter = {**(saved_query.get("breakdownFilter") or {}), "breakdowns": breakdowns}
    if breakdowns and metadata.get("breakdown_limit") is not None:
        breakdown_filter["breakdown_limit"] = metadata["breakdown_limit"]
    resolved["breakdownFilter"] = breakdown_filter

    if (
        breakdowns
        and saved_query.get("metric_type") == "funnel"
        and metadata.get("breakdownAttributionType") is not None
    ):
        resolved["breakdownAttributionType"] = metadata["breakdownAttributionType"]
        resolved.pop("breakdownAttributionValue", None)
        if metadata.get("breakdownAttributionValue") is not None:
            resolved["breakdownAttributionValue"] = metadata["breakdownAttributionValue"]

    return resolved


def is_scheduled_metric(metric: dict[str, Any] | None) -> bool:
    """Recalculation and the canary address metrics by uuid, so a metric dict without one is
    never scheduled. Legacy Trends/Funnels definitions carry no metric_type and cannot be
    built, so they are excluded too. Shared with the enrollment census so its build-load
    count filters the same way."""
    return bool(metric and metric.get("uuid") and metric.get("metric_type") in METRIC_BUILDERS)


def _resolve_inline_metrics(experiment: Experiment) -> list[ResolvedExperimentMetric]:
    """Inline primary metrics, then inline secondary metrics. Metrics without a uuid cannot be addressed
    and are skipped. Reads no rows."""
    sections: tuple[tuple[MetricRole, list | None], ...] = (
        ("primary", experiment.metrics),
        ("secondary", experiment.metrics_secondary),
    )
    resolved: list[ResolvedExperimentMetric] = []
    for role, metrics in sections:
        for metric in metrics or []:
            if isinstance(metric, dict) and metric.get("uuid"):
                resolved.append(ResolvedExperimentMetric(uuid=metric["uuid"], role=role, definition=metric))
    return resolved


def saved_metric_links(experiment: Experiment) -> list[ExperimentToSavedMetric]:
    """The experiment's links to saved/shared metrics, in id order. The join leaves the row order
    unspecified, and the link order is what puts the shared metrics in order on the experiment."""
    # Calling select_related on the manager would clone the queryset and discard a caller's
    # prefetch cache, re-querying per experiment. Join saved_metric only when nothing is prefetched.
    links = experiment.experimenttosavedmetric_set.all()
    if "experimenttosavedmetric_set" not in getattr(experiment, "_prefetched_objects_cache", {}):
        links = links.select_related("saved_metric")
    return sorted(links, key=lambda link: link.id)


def _resolve_saved_metrics(experiment: Experiment) -> list[ResolvedExperimentMetric]:
    """Saved/shared metrics linked to the experiment, with the link overrides applied. The link's
    metadata["type"] holds the role, and a missing type means primary."""
    resolved: list[ResolvedExperimentMetric] = []
    for link in saved_metric_links(experiment):
        saved_query = link.saved_metric.query
        if not isinstance(saved_query, dict) or not saved_query.get("uuid"):
            continue
        metadata = link.metadata or {}
        resolved.append(
            ResolvedExperimentMetric(
                uuid=saved_query["uuid"],
                role="secondary" if metadata.get("type") == "secondary" else "primary",
                definition=resolve_saved_metric_definition(saved_query, metadata),
            )
        )
    return resolved


def resolve_experiment_metrics(experiment: Experiment) -> list[ResolvedExperimentMetric]:
    """Every addressable metric on the experiment: inline primary, inline secondary, then saved/shared.

    Callers apply their own eligibility, for example `is_scheduled_metric` or `is_daily_timeseries_metric`.
    """
    return _resolve_inline_metrics(experiment) + _resolve_saved_metrics(experiment)


def resolve_scheduled_metrics(experiment: Experiment) -> list[ResolvedExperimentMetric]:
    """The scheduled metrics of the experiment in resolution order, resolved with at most one query.

    Results are addressed by uuid, so metrics that share a uuid share one definition: the first in
    resolution order, which makes an inline metric win over a saved metric. Each of them still has
    its own entry, because `total_metrics` counts entries.
    """
    definitions: dict[str, dict[str, Any]] = {}
    scheduled: list[ResolvedExperimentMetric] = []
    for metric in resolve_experiment_metrics(experiment):
        if is_scheduled_metric(metric.definition):
            definition = definitions.setdefault(metric.uuid, metric.definition)
            scheduled.append(ResolvedExperimentMetric(uuid=metric.uuid, role=metric.role, definition=definition))
    return scheduled


def scheduled_metric_definitions(experiment: Experiment) -> dict[str, dict[str, Any]]:
    """The effective definition of each scheduled metric, keyed by uuid in resolution order. Use it
    instead of calling `find_metric_dict` once per metric."""
    return {metric.uuid: metric.definition for metric in resolve_scheduled_metrics(experiment)}


def find_metric_dict(experiment: Experiment, metric_uuid: str) -> dict[str, Any] | None:
    """Resolve a scheduled metric_uuid to its effective definition, across inline AND saved/shared metrics."""
    return scheduled_metric_definitions(experiment).get(metric_uuid)


def build_metric(metric_dict: dict[str, Any]) -> ExperimentMetric:
    return METRIC_BUILDERS[metric_dict["metric_type"]](**metric_dict)
