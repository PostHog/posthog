"""Experiment reads for Pulse, which links the experiments a brief cites."""

from collections.abc import Collection

from products.experiments.backend.models.experiment import Experiment


def existing_experiment_ids(*, team_id: int, experiment_ids: Collection[int]) -> set[int]:
    """Which of the given experiment ids the team has. Deleted and archived experiments count."""
    return set(Experiment.objects.filter(team_id=team_id, id__in=experiment_ids).values_list("id", flat=True))
