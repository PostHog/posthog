from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.team import Team

from products.experiments.backend.facade import testing
from products.experiments.backend.facade.contracts import ExperimentRef
from products.experiments.backend.facade.reminders import get_experiment_ref
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestGetExperimentRef(BaseTest):
    @parameterized.expand(
        [
            ("live", False, False, True),
            ("deleted", False, True, True),
            ("another_team", True, False, False),
        ]
    )
    def test_finds_an_experiment_of_the_team(self, _name: str, other_team: bool, deleted: bool, found: bool) -> None:
        team = Team.objects.create(organization=self.organization, name="Other") if other_team else self.team
        flag = FeatureFlag.objects.create(team=team, key="experiment-flag", created_by=self.user)
        experiment_id = testing.create_experiment(
            team_id=team.id, feature_flag_id=flag.id, created_by_id=self.user.id, deleted=deleted
        )

        ref = get_experiment_ref(team_id=self.team.id, experiment_id=experiment_id)

        assert ref == (
            ExperimentRef(id=experiment_id, team_id=self.team.id, created_by_id=self.user.id) if found else None
        )
