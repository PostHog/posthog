"""Shared helpers for resolving experiment metric definitions across inline and saved/shared metrics.

Used by the recalculation workflow and the precompute canary workflow, which both pass metric uuids between
activities and re-resolve the definition at the point of use.
"""

from typing import Any

from posthog.schema import (
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
)

from products.experiments.backend.models.experiment import Experiment

ExperimentMetric = ExperimentMeanMetric | ExperimentFunnelMetric | ExperimentRatioMetric | ExperimentRetentionMetric

# Modern ExperimentMetric types (kind="ExperimentMetric"). Legacy Trends/Funnels metrics never enter these
# workflows, so there is no fallback — an unexpected metric_type surfaces as an error at the call site.
METRIC_BUILDERS: dict[str, type[ExperimentMetric]] = {
    "mean": ExperimentMeanMetric,
    "funnel": ExperimentFunnelMetric,
    "ratio": ExperimentRatioMetric,
    "retention": ExperimentRetentionMetric,
}


def _merge_saved_metric_breakdowns(saved_query: dict[str, Any], metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Merge per-experiment breakdowns from the M2M link metadata into the saved query, mirroring the
    daily-warming activity. Without this, callers would compute the unbroken-down version of a saved
    metric the experiment has configured with breakdowns."""
    metadata = metadata or {}
    return {
        **saved_query,
        "breakdownFilter": {
            **(saved_query.get("breakdownFilter") or {}),
            "breakdowns": metadata.get("breakdowns") or [],
        },
    }


def iter_metric_dicts(experiment: Experiment) -> list[dict[str, Any]]:
    """All metric definition dicts for an experiment: inline primary + secondary, then saved/shared metrics.

    Inline metrics are dicts in experiment.metrics / metrics_secondary. Saved metrics live on the M2M
    through-model and carry their definition (with uuid) in saved_metric.query; per-experiment breakdown
    overrides from the link metadata are merged in.
    """
    dicts: list[dict[str, Any]] = [
        metric for metric in (experiment.metrics or []) + (experiment.metrics_secondary or []) if metric.get("uuid")
    ]
    for link in experiment.experimenttosavedmetric_set.select_related("saved_metric").all():
        saved_query = link.saved_metric.query
        if saved_query and saved_query.get("uuid"):
            dicts.append(_merge_saved_metric_breakdowns(saved_query, link.metadata))
    return dicts


def find_metric_dict(experiment: Experiment, metric_uuid: str) -> dict[str, Any] | None:
    """Resolve a metric_uuid to its definition dict, across inline AND saved/shared metrics."""
    return next((metric for metric in iter_metric_dicts(experiment) if metric.get("uuid") == metric_uuid), None)


def build_metric(metric_dict: dict[str, Any]) -> ExperimentMetric:
    return METRIC_BUILDERS[metric_dict["metric_type"]](**metric_dict)
