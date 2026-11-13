"""Experiment writes for the tests of the flag cache receivers.

Both flag caches rebuild on the same experiment writes, so their receiver tests share one set of them.
"""

from collections.abc import Callable

from posthog.models import Team, User

from products.experiments.backend.facade.testing import create_experiment, delete_experiment, update_experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag

EXPERIMENT_CHANGES = ("create", "update", "soft_delete", "delete")


def seed_experiment_change(action: str, *, team: Team, user: User) -> Callable[[], object]:
    """Seed a flag, and an experiment on it unless `action` is "create", and return the experiment write that
    `action` names. Reset the receiver mocks before calling it, so the seeding writes do not count."""
    flag = FeatureFlag.objects.create(
        team=team,
        key="exp-flag",
        created_by=user,
        filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
    )
    if action == "create":
        return lambda: create_experiment(team_id=team.id, feature_flag_id=flag.id, name="My experiment")

    experiment_id = create_experiment(team_id=team.id, feature_flag_id=flag.id, name="My experiment")
    writes: dict[str, Callable[[], object]] = {
        "update": lambda: update_experiment(team_id=team.id, experiment_id=experiment_id, name="Renamed experiment"),
        "soft_delete": lambda: update_experiment(team_id=team.id, experiment_id=experiment_id, deleted=True),
        "delete": lambda: delete_experiment(team_id=team.id, experiment_id=experiment_id),
    }
    return writes[action]
