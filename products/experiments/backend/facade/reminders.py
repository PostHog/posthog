"""Experiment reads for reminders, which can point a reminder at an experiment."""

from products.experiments.backend.facade.contracts import ExperimentRef
from products.experiments.backend.models.experiment import Experiment


def get_experiment_ref(*, team_id: int, experiment_id: int) -> ExperimentRef | None:
    """The experiment with this id on this exact team, or None. A deleted experiment is returned too."""
    experiment = (
        Experiment.objects.on_exact_team(team_id)
        .including_deleted()
        .filter(id=experiment_id)
        .only("id", "team_id", "created_by_id")
        .first()
    )
    if experiment is None:
        return None
    return ExperimentRef(id=experiment.id, team_id=experiment.team_id, created_by_id=experiment.created_by_id)
