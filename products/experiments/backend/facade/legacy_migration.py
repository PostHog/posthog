"""Legacy migration capability for callers outside the experiments internals."""

from posthog.models.team.team import Team

from products.experiments.backend import legacy_migration
from products.experiments.backend.models.experiment import Experiment, experiment_has_legacy_metrics

from .contracts import ExperimentRef

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


def migrate_experiment(experiment_id: int, team_id: int, *, migrate_shared_metrics: bool = False) -> ExperimentRef:
    """The new-engine copy of the team's legacy experiment, made now or by an earlier call. With
    `migrate_shared_metrics`, the legacy shared metrics of the experiment get new-engine copies in the same call.

    Raises LegacyMigrationError when the experiment can't move onto the new engine.
    """
    migrated = legacy_migration.migrate_experiment(
        experiment_id, team_id, migrate_shared_metrics=migrate_shared_metrics
    ).experiment
    return ExperimentRef(id=migrated.id, team_id=migrated.team_id, created_by_id=migrated.created_by_id)
