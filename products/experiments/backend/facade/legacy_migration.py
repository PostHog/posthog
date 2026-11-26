"""Legacy migration capability for callers outside the experiments internals."""

from posthog.models.team.team import Team

from products.experiments.backend.legacy_migration import migrate_experiment
from products.experiments.backend.models.experiment import Experiment, experiment_has_legacy_metrics

__all__ = [
    "experiment_uses_legacy_metrics",
    "migrate_experiment",
]


def experiment_uses_legacy_metrics(*, team: Team, experiment_id: int) -> bool:
    """Whether the project's experiment with the id has a metric in a legacy format, inline or through a shared
    metric. False when the project has no experiment with the id."""
    experiment = (
        Experiment.objects.filter(team__project_id=team.project_id, pk=experiment_id)
        .only("id", "metrics", "metrics_secondary")
        .first()
    )
    return experiment is not None and experiment_has_legacy_metrics(experiment)
