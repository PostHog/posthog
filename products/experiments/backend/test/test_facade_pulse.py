from posthog.test.base import BaseTest

from posthog.models.team import Team

from products.experiments.backend.facade import testing
from products.experiments.backend.facade.pulse import existing_experiment_ids
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestExistingExperimentIds(BaseTest):
    def test_returns_the_listed_ids_the_team_has(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        ids: dict[str, int] = {}
        for key, team, deleted, archived in [
            ("live", self.team, False, False),
            ("archived", self.team, False, True),
            ("deleted", self.team, True, False),
            ("not_listed", self.team, False, False),
            ("other_team", other_team, False, False),
        ]:
            flag = FeatureFlag.objects.create(team=team, key=key, created_by=self.user)
            ids[key] = testing.create_experiment(
                team_id=team.id, feature_flag_id=flag.id, name=key, deleted=deleted, archived=archived
            )
        unknown_id = max(ids.values()) + 1

        found = existing_experiment_ids(
            team_id=self.team.id,
            experiment_ids=[ids["live"], ids["archived"], ids["deleted"], ids["other_team"], unknown_id],
        )

        assert found == {ids["live"], ids["archived"], ids["deleted"]}
