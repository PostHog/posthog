"""The calculation keys of experiments' metrics, for callers outside the product.

Unlike `build_calculation_configs`, these keep metrics that cannot be scheduled, and they key each saved
metric by its own definition even when an inline metric has the same uuid. The daily discoveries hash each
metric from its own source, so they need these keys.
"""

from collections.abc import Collection

from products.experiments.backend.facade.contracts import MetricCalculationKeys
from products.experiments.backend.metric_calculation.config import (
    ExperimentCalculationSettings,
    inline_metric_calculation_keys,
    saved_metric_calculation_keys,
    team_experiments_configs,
)
from products.experiments.backend.models.experiment import Experiment


def _calculation_settings(
    experiments: Collection[Experiment],
) -> list[tuple[Experiment, ExperimentCalculationSettings]]:
    team_configs = team_experiments_configs({experiment.team_id for experiment in experiments})
    return [
        (
            experiment,
            ExperimentCalculationSettings.from_experiment(experiment, team_config=team_configs[experiment.team_id]),
        )
        for experiment in experiments
    ]


def inline_metric_calculation_keys_for_experiments(experiments: Collection[Experiment]) -> dict[int, dict[str, str]]:
    """The key of each inline metric by metric uuid, for each experiment by id.

    The experiments can belong to many teams. Load them with `select_related("team", "feature_flag")`,
    and this reads one query however many experiments and teams there are, because the daily inline
    discovery passes every running experiment of the hour.
    """
    return {
        experiment.id: inline_metric_calculation_keys(experiment, settings)
        for experiment, settings in _calculation_settings(experiments)
    }


def saved_metric_calculation_keys_for_experiments(experiments: Collection[Experiment]) -> dict[int, dict[int, str]]:
    """The key of each saved metric by link id, for each experiment by id.

    Load the experiments as for `inline_metric_calculation_keys_for_experiments`, and also prefetch
    `experimenttosavedmetric_set` with its saved metrics. Without the prefetch, this reads the links of
    each experiment with a separate query.
    """
    return {
        experiment.id: saved_metric_calculation_keys(experiment, settings)
        for experiment, settings in _calculation_settings(experiments)
    }


def metric_calculation_keys(experiment_id: int, *, team_id: int) -> MetricCalculationKeys:
    """The keys of one experiment, with empty maps when the team has no experiment with this id."""
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
