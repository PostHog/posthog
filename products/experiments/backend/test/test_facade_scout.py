from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest

from posthog.models.team import Team

from products.experiments.backend.facade import testing
from products.experiments.backend.facade.contracts import RecentExperiment
from products.experiments.backend.facade.scout import experiment_orientation
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestExperimentOrientation(BaseTest):
    def test_counts_and_lists_the_live_experiments_of_the_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        updated = datetime(2026, 10, 1, tzinfo=UTC)
        day = timedelta(days=1)
        started = updated - 10 * day
        ids: dict[str, int] = {}
        for key, team, end_date, archived, deleted, days_before_update in [
            ("running", self.team, None, False, False, 1),
            ("archived", self.team, None, True, False, 2),
            ("stopped", self.team, updated - 5 * day, False, False, 3),
            ("deleted_unset", self.team, None, False, False, 4),
            ("deleted", self.team, None, False, True, 0),
            ("other_team", other_team, None, False, False, 0),
        ]:
            flag = FeatureFlag.objects.create(team=team, key=f"flag-{key}", created_by=self.user)
            ids[key] = testing.create_experiment(
                team_id=team.id,
                feature_flag_id=flag.id,
                name=key,
                start_date=started,
                end_date=end_date,
                archived=archived,
                deleted=deleted,
                updated_at=updated - days_before_update * day,
            )
        Experiment.objects.filter(id=ids["deleted_unset"]).update(deleted=None)
        draft_flag = FeatureFlag.objects.create(team=self.team, key="flag-draft", created_by=self.user)
        testing.create_experiment(
            team_id=self.team.id, feature_flag_id=draft_flag.id, name="draft", updated_at=updated - 9 * day
        )

        orientation = experiment_orientation(team_id=self.team.id, recent_limit=3)

        assert orientation.total_count == 5
        assert orientation.running_count == 2
        assert [experiment.id for experiment in orientation.recent] == [ids["running"], ids["archived"], ids["stopped"]]
        assert orientation.recent[2] == RecentExperiment(
            id=ids["stopped"],
            name="stopped",
            archived=False,
            start_date=started,
            end_date=updated - 5 * day,
            feature_flag_key="flag-stopped",
            updated_at=updated - 3 * day,
        )
