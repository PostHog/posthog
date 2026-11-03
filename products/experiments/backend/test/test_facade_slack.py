from datetime import UTC, datetime

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.team import Team

from products.experiments.backend.facade import testing
from products.experiments.backend.facade.contracts import ExperimentUnfurl, ExperimentUnfurlVariant
from products.experiments.backend.facade.slack import get_experiment_unfurl
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestGetExperimentUnfurl(BaseTest):
    @parameterized.expand(
        [
            ("live", False, False, True),
            ("deleted", False, True, False),
            ("another_team", True, False, False),
        ]
    )
    def test_finds_only_a_live_experiment_of_the_team(
        self, _name: str, other_team: bool, deleted: bool, found: bool
    ) -> None:
        team = Team.objects.create(organization=self.organization, name="Other") if other_team else self.team
        flag = FeatureFlag.objects.create(team=team, key="experiment-flag", created_by=self.user)
        experiment_id = testing.create_experiment(team_id=team.id, feature_flag_id=flag.id, deleted=deleted)

        unfurl = get_experiment_unfurl(team_id=self.team.id, experiment_id=experiment_id)

        assert (unfurl is not None) is found

    def test_reads_what_the_preview_shows(self) -> None:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="checkout-copy",
            created_by=self.user,
            active=False,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 30},
                        {"key": "test", "rollout_percentage": 70},
                    ]
                },
            },
        )
        start_date = datetime(2026, 9, 1, tzinfo=UTC)
        updated_at = datetime(2026, 9, 2, tzinfo=UTC)
        experiment_id = testing.create_experiment(
            team_id=self.team.id,
            feature_flag_id=flag.id,
            name="Checkout copy",
            description="Shorter copy converts better.",
            created_by_id=self.user.id,
            start_date=start_date,
            metrics=[{"kind": "ExperimentMetric", "metric_type": "funnel", "name": "Completed checkout"}],
            updated_at=updated_at,
        )

        unfurl = get_experiment_unfurl(team_id=self.team.id, experiment_id=experiment_id)

        assert unfurl == ExperimentUnfurl(
            id=experiment_id,
            created_by_id=self.user.id,
            name="Checkout copy",
            description="Shorter copy converts better.",
            status="paused",
            start_date=start_date,
            end_date=None,
            updated_at=updated_at,
            primary_metric_name="Completed checkout",
            variants=(
                ExperimentUnfurlVariant(key="control", rollout_percentage=30),
                ExperimentUnfurlVariant(key="test", rollout_percentage=70),
            ),
        )
