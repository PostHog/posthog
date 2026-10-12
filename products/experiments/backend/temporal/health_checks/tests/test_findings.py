from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.models.health_issue import HealthIssue

from products.experiments.backend.health.checks.flag_state import flag_state
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.temporal.health_checks.findings import detect_experiment_findings
from products.feature_flags.backend.models.feature_flag import FeatureFlag

METRIC = {"kind": "ExperimentMetric", "metric_type": "mean", "source": {"kind": "EventsNode", "event": "$pageview"}}


class TestExperimentHealthFindings(BaseTest):
    def _experiment(self, *, team: Team | None = None, flag_active: bool = True, **fields: Any) -> Experiment:
        team = team or self.team
        flag = FeatureFlag.objects.create(
            team=team,
            key=f"flag-{FeatureFlag.objects.count()}",
            created_by=self.user,
            active=flag_active,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            },
        )
        defaults: dict[str, Any] = {
            "name": "Checkout test",
            "start_date": timezone.now() - timedelta(days=3),
            "metrics": [METRIC],
        }
        return Experiment.objects.create(team=team, feature_flag=flag, **{**defaults, **fields})

    def test_a_finding_becomes_one_issue_per_experiment_and_subcode(self) -> None:
        experiment = self._experiment(flag_active=False)

        results = detect_experiment_findings([self.team.id], flag_state)

        assert list(results) == [self.team.id]
        [result] = results[self.team.id]
        assert result.severity == HealthIssue.Severity.WARNING
        assert result.hash_keys == ["experiment_id", "subcode"]
        assert result.payload["experiment_id"] == experiment.id
        assert result.payload["experiment_name"] == "Checkout test"
        assert result.payload["feature_flag_id"] == experiment.feature_flag_id
        assert result.payload["code"] == "flag_off_while_running"
        assert result.payload["subcode"] == "running_but_flag_disabled"
        assert result.payload["actions"] == ["open_feature_flag"]

    @parameterized.expand(
        [
            ("archived", {"archived": True}),
            ("deleted", {"deleted": True}),
        ]
    )
    def test_hidden_experiments_produce_no_issue_so_their_open_issues_resolve(
        self, _name: str, fields: dict[str, Any]
    ) -> None:
        self._experiment(flag_active=False, **fields)

        assert detect_experiment_findings([self.team.id], flag_state) == {}

    def test_experiments_of_teams_outside_the_batch_are_not_read(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"), name="Other")
        self._experiment(team=other_team, flag_active=False)

        assert detect_experiment_findings([self.team.id], flag_state) == {}
