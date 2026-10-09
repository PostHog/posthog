"""The calculation keys of experiments' metrics, for callers outside the product."""

from collections.abc import Mapping

from django.db.models import Prefetch

from products.experiments.backend.facade.contracts import MetricCalculationKeys
from products.experiments.backend.metric_calculation.config import (
    ExperimentCalculationSettings,
    inline_metric_calculation_keys,
    saved_metric_calculation_keys,
    team_experiments_configs,
)
from products.experiments.backend.models.experiment import Experiment, ExperimentToSavedMetric


def metric_calculation_keys_for_experiments(
    team_id_by_experiment_id: Mapping[int, int],
) -> dict[int, MetricCalculationKeys]:
    """The calculation key of every addressable metric of each experiment, by source.

    The argument maps each experiment id to its team, so the experiments can belong to many teams. The
    read takes three queries however many experiments and teams there are, because the daily discoveries
    ask for every running experiment at once. Every requested id is in the result, with empty maps when
    the team has no experiment with that id.

    Unlike `build_calculation_configs`, this keeps metrics that cannot be scheduled, and it keys each saved
    metric by its own definition even when an inline metric has the same uuid. The daily discoveries hash
    each metric from its own source, so they need these keys.
    """
    keys = {experiment_id: MetricCalculationKeys(inline={}, saved={}) for experiment_id in team_id_by_experiment_id}
    if not keys:
        return keys
    # The read spans teams by design. `team_id__in` and the team check on each row keep every id to the
    # team that the caller named for it, but the IDOR rule only recognizes a single-team filter.
    rows = (
        Experiment.objects.filter(  # nosemgrep: idor-lookup-without-team
            id__in=team_id_by_experiment_id, team_id__in=set(team_id_by_experiment_id.values())
        )
        .select_related("team", "feature_flag")
        .prefetch_related(
            Prefetch(
                "experimenttosavedmetric_set",
                queryset=ExperimentToSavedMetric.objects.select_related("saved_metric"),
            )
        )
    )
    experiments = [experiment for experiment in rows if experiment.team_id == team_id_by_experiment_id[experiment.id]]
    team_configs = team_experiments_configs({experiment.team_id for experiment in experiments})
    for experiment in experiments:
        settings = ExperimentCalculationSettings.from_experiment(
            experiment, team_config=team_configs[experiment.team_id]
        )
        keys[experiment.id] = MetricCalculationKeys(
            inline=inline_metric_calculation_keys(experiment, settings),
            saved=saved_metric_calculation_keys(experiment, settings),
        )
    return keys


def metric_calculation_keys(experiment_id: int, *, team_id: int) -> MetricCalculationKeys:
    """The keys of one experiment, as `metric_calculation_keys_for_experiments` returns them."""
    return metric_calculation_keys_for_experiments({experiment_id: team_id})[experiment_id]
