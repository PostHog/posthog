from posthog.test.base import BaseTest

from posthog.models.team import Team

from products.experiments.backend.facade import testing
from products.experiments.backend.facade.pulse import existing_experiment_ids
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestExistingExperimentIds(BaseTest):
    def _create_experiment(self, team: Team, key: str, *, deleted: bool = False, archived: bool = False) -> int:
        flag = FeatureFlag.objects.create(team=team, key=key, created_by=self.user)
        return testing.create_experiment(
            team_id=team.id, feature_flag_id=flag.id, name=key, deleted=deleted, archived=archived
        )

    def test_returns_the_listed_ids_the_team_has(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        live = self._create_experiment(self.team, "live")
        archived = self._create_experiment(self.team, "archived", archived=True)
        deleted = self._create_experiment(self.team, "deleted", deleted=True)
        not_listed = self._create_experiment(self.team, "not_listed")
        of_other_team = self._create_experiment(other_team, "other_team")
        unknown_id = max(live, archived, deleted, not_listed, of_other_team) + 1

        found = existing_experiment_ids(
            team_id=self.team.id, experiment_ids=[live, archived, deleted, of_other_team, unknown_id]
        )

        assert found == {live, archived, deleted}
