"""Input checks that the experiments API runs before it hands the input to a write."""

from products.experiments.backend.models.experiment import ExperimentHoldout


def holdout_exists(*, team_id: int, holdout_id: int) -> bool:
    """Whether the project of the team has a holdout with the id. Holdouts belong to a project, not to one of its
    environments."""
    return ExperimentHoldout.objects.filter(team_id=team_id, pk=holdout_id).exists()
