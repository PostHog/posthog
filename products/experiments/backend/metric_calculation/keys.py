"""The calculation keys of an experiment's metrics, for callers outside the product."""

from products.experiments.backend.facade.contracts import MetricCalculationKeys
from products.experiments.backend.metric_calculation.spec import ExperimentCalculationSettings
from products.experiments.backend.metric_resolution import (
    resolve_experiment_metrics,
    resolve_saved_metric_definition,
    saved_metric_links,
    saved_metric_role,
)
from products.experiments.backend.models.experiment import Experiment


def metric_calculation_keys(experiment_id: int, *, team_id: int) -> MetricCalculationKeys:
    """The calculation key of every addressable metric of the experiment, by source.

    Unlike `plan`, this keeps metrics that cannot be scheduled, and it keys each saved metric by its own
    definition even when an inline metric has the same uuid. The daily discoveries and the saved-metric
    `fingerprint` in the API response hash each metric from its own source, so they need these keys.
    Both maps are empty when the experiment does not exist.
    """
    experiment = (
        Experiment.objects.select_related("team", "feature_flag")
        .prefetch_related("experimenttosavedmetric_set__saved_metric")
        .filter(id=experiment_id, team_id=team_id)
        .first()
    )
    if experiment is None:
        return MetricCalculationKeys(inline={}, saved={})
    settings = ExperimentCalculationSettings.of_experiment(experiment)
    inline: dict[str, str] = {}
    for metric in resolve_experiment_metrics(experiment):
        if metric.source == "inline" and metric.uuid not in inline:
            spec = settings.spec_for(metric_id=metric.uuid, role=metric.role, definition=metric.definition)
            inline[metric.uuid] = spec.calculation_key()
    saved: dict[int, str] = {}
    for link in saved_metric_links(experiment):
        query = link.saved_metric.query
        if isinstance(query, dict):
            spec = settings.spec_for(
                metric_id=query.get("uuid") or "",
                role=saved_metric_role(link.metadata),
                definition=resolve_saved_metric_definition(query, link.metadata),
            )
            saved[link.id] = spec.calculation_key()
    return MetricCalculationKeys(inline=inline, saved=saved)
