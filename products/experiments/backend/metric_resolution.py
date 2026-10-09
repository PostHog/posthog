"""The effective metrics of an experiment, across inline and saved/shared metrics.

The effective definition of a saved metric includes the overrides of its experiment link. Calculation (daily
timeseries and recalculation), discovery, fingerprints and the API all read a metric's effective definition
from here, so that they calculate and hash the same metric. Workflows pass metric uuids between activities
and read the effective definition again at the point of use.
"""

import dataclasses
from typing import Any, Literal

from posthog.schema import (
    ExperimentDataWarehouseNode,
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
MetricSource = Literal["inline", "saved"]


@frozen
class EffectiveExperimentMetric:
    """A metric as it applies to one experiment: an inline definition, or a saved definition with the
    link's per-experiment overrides applied."""

    uuid: str
    role: MetricRole
    source: MetricSource
    # The effective definition. It is the only dict that may feed a calculation config or a query for
    # this metric. A caller that uses the raw saved query calculates a different metric and files or
    # looks up results under a different calculation key than every other caller.
    definition: dict[str, Any]


def apply_saved_metric_overrides(saved_query: dict[str, Any], metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Apply the per-experiment overrides from the link metadata to a saved query.

    - `breakdowns` always comes from the link. A link without breakdowns has none, whatever the saved
      query holds.
    - `breakdown_limit` replaces the saved value when the link sets it.
    - `breakdownAttributionType` and `breakdownAttributionValue` are one override: when the link sets a
      type, both come from the link, so a link type without a value drops the saved step value. Only
      funnel metrics have these fields.

    The limit and the attribution are breakdown settings, so a link without breakdowns applies neither.
    Applying them would change the calculation key of a metric whose results cannot change, and the stored
    results of that metric would become unreachable.

    A key that is absent or null is an omitted override. Step 0 is an explicit value.
    """
    metadata = metadata or {}
    effective = {**saved_query}

    breakdowns = metadata.get("breakdowns") or []
    breakdown_filter = {**(saved_query.get("breakdownFilter") or {}), "breakdowns": breakdowns}
    if breakdowns and metadata.get("breakdown_limit") is not None:
        breakdown_filter["breakdown_limit"] = metadata["breakdown_limit"]
    effective["breakdownFilter"] = breakdown_filter

    if (
        breakdowns
        and saved_query.get("metric_type") == "funnel"
        and metadata.get("breakdownAttributionType") is not None
    ):
        effective["breakdownAttributionType"] = metadata["breakdownAttributionType"]
        effective.pop("breakdownAttributionValue", None)
        if metadata.get("breakdownAttributionValue") is not None:
            effective["breakdownAttributionValue"] = metadata["breakdownAttributionValue"]

    return effective


def is_scheduled_metric(metric: dict[str, Any] | None) -> bool:
    """Recalculation and the canary address metrics by uuid, so a metric dict without one is
    never scheduled. Legacy Trends/Funnels definitions carry no metric_type and cannot be
    built, so they are excluded too. Shared with the enrollment census so its build-load
    count filters the same way."""
    return bool(metric and metric.get("uuid") and metric.get("metric_type") in METRIC_BUILDERS)


def _get_effective_inline_metrics(experiment: Experiment) -> list[EffectiveExperimentMetric]:
    """Inline primary metrics, then inline secondary metrics. Metrics without a uuid cannot be addressed
    and are skipped. Reads no rows."""
    sections: tuple[tuple[MetricRole, list | None], ...] = (
        ("primary", experiment.metrics),
        ("secondary", experiment.metrics_secondary),
    )
    effective_metrics: list[EffectiveExperimentMetric] = []
    for role, metrics in sections:
        for metric in metrics or []:
            if isinstance(metric, dict) and metric.get("uuid"):
                effective_metrics.append(
                    EffectiveExperimentMetric(uuid=metric["uuid"], role=role, source="inline", definition=metric)
                )
    return effective_metrics


def saved_metric_links(experiment: Experiment) -> list[ExperimentToSavedMetric]:
    """The experiment's links to saved/shared metrics, in id order. The join leaves the row order
    unspecified, and the link order is what puts the shared metrics in order on the experiment."""
    # Calling select_related on the manager would clone the queryset and discard a caller's
    # prefetch cache, re-querying per experiment. Join saved_metric only when nothing is prefetched.
    links = experiment.experimenttosavedmetric_set.all()
    if "experimenttosavedmetric_set" not in getattr(experiment, "_prefetched_objects_cache", {}):
        links = links.select_related("saved_metric")
    return sorted(links, key=lambda link: link.id)


def saved_metric_link_role(link: ExperimentToSavedMetric) -> MetricRole:
    """The role of a shared-metric link. The API accepts a link without metadata, and such a link is primary."""
    metadata = link.metadata if isinstance(link.metadata, dict) else {}
    return "secondary" if metadata.get("type") == "secondary" else "primary"


def _get_effective_saved_metrics(experiment: Experiment) -> list[EffectiveExperimentMetric]:
    """Saved/shared metrics linked to the experiment, with the link overrides applied."""
    effective_metrics: list[EffectiveExperimentMetric] = []
    for link in saved_metric_links(experiment):
        saved_query = link.saved_metric.query
        if not isinstance(saved_query, dict) or not saved_query.get("uuid"):
            continue
        metadata = link.metadata or {}
        effective_metrics.append(
            EffectiveExperimentMetric(
                uuid=saved_query["uuid"],
                role=saved_metric_link_role(link),
                source="saved",
                definition=apply_saved_metric_overrides(saved_query, metadata),
            )
        )
    return effective_metrics


def get_effective_experiment_metrics(experiment: Experiment) -> list[EffectiveExperimentMetric]:
    """Every addressable metric on the experiment: inline primary, inline secondary, then saved/shared.

    Callers apply their own eligibility, for example `is_scheduled_metric` or `is_daily_timeseries_metric`.
    """
    return _get_effective_inline_metrics(experiment) + _get_effective_saved_metrics(experiment)


def get_metrics_for_calculation(experiment: Experiment) -> list[EffectiveExperimentMetric]:
    """The metrics that the experiment calculates, in the order of `get_effective_experiment_metrics`,
    read with at most one query. A metric is calculated when `is_scheduled_metric` accepts its effective
    definition, and this function checks nothing else.

    Results are addressed by uuid, so metrics that share a uuid share one definition: the first in
    that order, which makes an inline metric win over a saved metric. Each of them still has its own
    entry, because `total_metrics` counts entries.
    """
    definitions: dict[str, dict[str, Any]] = {}
    scheduled: list[EffectiveExperimentMetric] = []
    for metric in get_effective_experiment_metrics(experiment):
        if is_scheduled_metric(metric.definition):
            definition = definitions.setdefault(metric.uuid, metric.definition)
            scheduled.append(dataclasses.replace(metric, definition=definition))
    return scheduled


def scheduled_metric_definitions(experiment: Experiment) -> dict[str, dict[str, Any]]:
    """The effective definition of each metric that `get_metrics_for_calculation` returns, keyed by uuid
    in that order. Use it instead of calling `find_metric_dict` once per metric."""
    return {metric.uuid: metric.definition for metric in get_metrics_for_calculation(experiment)}


def find_metric_dict(experiment: Experiment, metric_uuid: str) -> dict[str, Any] | None:
    """Resolve a scheduled metric_uuid to its effective definition, across inline AND saved/shared metrics."""
    return scheduled_metric_definitions(experiment).get(metric_uuid)


def build_metric(metric_dict: dict[str, Any]) -> ExperimentMetric:
    return METRIC_BUILDERS[metric_dict["metric_type"]](**metric_dict)


# A metric reads a data warehouse table when any of its source nodes is an ExperimentDataWarehouseNode.
# Such metrics never precompute (the precomputed table lacks the join keys). The source-bearing fields
# are the same across the two readers below: source, series[*], numerator, denominator, start_event,
# completion_event. Keep the pair in step — one reads the typed metric, the other a raw saved definition.
def metric_reads_data_warehouse(metric: ExperimentMetric) -> bool:
    """Typed check, for callers that already hold a built metric (the query runner)."""
    if isinstance(metric, ExperimentMeanMetric):
        nodes: list[Any] = [metric.source]
    elif isinstance(metric, ExperimentFunnelMetric):
        nodes = list(metric.series)
    elif isinstance(metric, ExperimentRatioMetric):
        nodes = [metric.numerator, metric.denominator]
    else:
        nodes = [metric.start_event, metric.completion_event]
    return any(isinstance(node, ExperimentDataWarehouseNode) for node in nodes)


def metric_dict_reads_data_warehouse(metric_dict: dict[str, Any]) -> bool:
    """Dict check, for callers that only hold a saved definition they may not be able to build (canary
    sampling). A field absent on a shape is simply missing from the dict."""
    nodes = [
        metric_dict.get("source"),
        *(metric_dict.get("series") or []),
        metric_dict.get("numerator"),
        metric_dict.get("denominator"),
        metric_dict.get("start_event"),
        metric_dict.get("completion_event"),
    ]
    return any(isinstance(node, dict) and node.get("kind") == "ExperimentDataWarehouseNode" for node in nodes)
