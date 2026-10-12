"""The calculation keys of experiments' metrics, for callers outside the product.

These key each saved metric by its own definition, even when an inline metric has the same uuid. The daily
calculation hashes each metric from its own source, so its keys can differ from the keys of
`build_calculation_configs`.
"""

from collections.abc import Mapping

from django.db.models import Prefetch

import structlog

from products.experiments.backend.facade.contracts import DailyMetricCalculation, MetricCalculationKeys
from products.experiments.backend.metric_calculation.config import (
    ExperimentCalculationSettings,
    inline_metric_calculation_keys,
    saved_metric_calculation_keys,
    team_experiments_configs,
)
from products.experiments.backend.metric_resolution import is_scheduled_metric, saved_metric_links
from products.experiments.backend.models.experiment import Experiment, ExperimentToSavedMetric

logger = structlog.get_logger(__name__)


def _experiments_with_settings(
    team_id_by_experiment_id: Mapping[int, int], *, prefetch_saved_metrics: bool
) -> list[tuple[Experiment, ExperimentCalculationSettings]]:
    """The experiments with their calculation settings. An id that its team has no experiment for is
    left out."""
    if not team_id_by_experiment_id:
        return []
    # The read spans teams by design. `team_id__in` and the team check on each row keep every id to the
    # team that the caller named for it, but the IDOR rule only recognizes a single-team filter.
    rows = Experiment.objects.filter(  # nosemgrep: idor-lookup-without-team
        id__in=team_id_by_experiment_id, team_id__in=set(team_id_by_experiment_id.values())
    ).select_related("team", "feature_flag")
    if prefetch_saved_metrics:
        rows = rows.prefetch_related(
            Prefetch(
                "experimenttosavedmetric_set",
                queryset=ExperimentToSavedMetric.objects.select_related("saved_metric"),
            )
        )
    experiments = [experiment for experiment in rows if experiment.team_id == team_id_by_experiment_id[experiment.id]]
    team_configs = team_experiments_configs({experiment.team_id for experiment in experiments})
    return [
        (
            experiment,
            ExperimentCalculationSettings.from_experiment(experiment, team_config=team_configs[experiment.team_id]),
        )
        for experiment in experiments
    ]


def daily_inline_metric_calculations(team_id_by_experiment_id: Mapping[int, int]) -> list[DailyMetricCalculation]:
    """The inline metrics that the daily calculation computes for each experiment, with their keys.

    The argument maps each experiment id to its team, so the experiments can belong to many teams. The read
    takes two queries however many experiments and teams there are, because the daily discovery asks for
    every running experiment of the hour at once. The keys come from the same rows as the metrics, so every
    metric has a key.
    """
    calculations: list[DailyMetricCalculation] = []
    for experiment, settings in _experiments_with_settings(team_id_by_experiment_id, prefetch_saved_metrics=False):
        calculation_keys = inline_metric_calculation_keys(experiment, settings)
        for metric in (experiment.metrics or []) + (experiment.metrics_secondary or []):
            metric_uuid = metric.get("uuid")
            if not metric_uuid:
                logger.warning("Metric has no UUID, skipping", experiment_id=experiment.id)
                continue
            if not is_scheduled_metric(metric):
                continue
            calculations.append(
                DailyMetricCalculation(
                    experiment_id=experiment.id,
                    team_id=experiment.team_id,
                    metric_uuid=metric_uuid,
                    calculation_key=calculation_keys[metric_uuid],
                )
            )
    return calculations


def daily_saved_metric_calculations(team_id_by_experiment_id: Mapping[int, int]) -> list[DailyMetricCalculation]:
    """The saved metrics that the daily calculation computes for each experiment, with their keys.

    As `daily_inline_metric_calculations`, with one more query that reads the saved-metric links.
    """
    calculations: list[DailyMetricCalculation] = []
    for experiment, settings in _experiments_with_settings(team_id_by_experiment_id, prefetch_saved_metrics=True):
        calculation_keys = saved_metric_calculation_keys(experiment, settings)
        for link in saved_metric_links(experiment):
            saved_metric = link.saved_metric
            metric_uuid = saved_metric.query.get("uuid")
            if not metric_uuid:
                logger.warning(
                    "Saved metric has no UUID, skipping",
                    experiment_id=experiment.id,
                    saved_metric_id=saved_metric.id,
                )
                continue
            if not is_scheduled_metric(saved_metric.query):
                continue
            calculations.append(
                DailyMetricCalculation(
                    experiment_id=experiment.id,
                    team_id=experiment.team_id,
                    metric_uuid=metric_uuid,
                    calculation_key=calculation_keys[link.id],
                )
            )
    return calculations


def metric_calculation_keys(experiment_id: int, *, team_id: int) -> MetricCalculationKeys:
    """The key of every addressable metric of one experiment, including metrics that cannot be scheduled.
    The maps are empty when the team has no experiment with this id."""
    experiment = (
        Experiment.objects.select_related("team", "feature_flag").filter(id=experiment_id, team_id=team_id).first()
    )
    if experiment is None:
        return MetricCalculationKeys(inline={}, saved={})
    settings = ExperimentCalculationSettings.from_experiment(experiment)
    return MetricCalculationKeys(
        inline=inline_metric_calculation_keys(experiment, settings),
        saved=saved_metric_calculation_keys(experiment, settings),
    )
