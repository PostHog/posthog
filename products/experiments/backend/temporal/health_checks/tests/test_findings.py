from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import call, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.models.health_issue import HealthIssue

from products.experiments.backend.health.checks.flag_state import flag_state
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.temporal.health_checks.findings import (
    LIVE_GATE_FLAG,
    detect_experiment_findings,
    live_gate_team_ids,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag

FLAG_READ_TARGET = "products.experiments.backend.temporal.health_checks.findings.get_feature_flag_or_none"

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

    @parameterized.expand([("not_deleted", False), ("deleted_unset", None)])
    def test_a_finding_becomes_one_issue_per_experiment_and_subcode(self, _name: str, deleted: bool | None) -> None:
        experiment = self._experiment(flag_active=False, deleted=deleted)

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

    def test_a_failing_check_fails_the_batch_so_open_issues_stay_open(self) -> None:
        self._experiment()

        def failing_check(_ctx: Any) -> None:
            raise ValueError("broken check")

        with self.assertRaises(ValueError):
            detect_experiment_findings([self.team.id], failing_check)

    def test_experiments_of_teams_outside_the_batch_are_not_read(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"), name="Other")
        self._experiment(team=other_team, flag_active=False)

        assert detect_experiment_findings([self.team.id], flag_state) == {}


class TestExperimentHealthLiveGate(BaseTest):
    @parameterized.expand(
        [
            ("enabled", True, True),
            ("deliberately_disabled", False, False),
            ("flag_absent", None, False),
            ("a_variant_is_not_enabled", "control", False),
        ]
    )
    def test_the_gate_keeps_a_team_only_when_the_flag_answers_true(self, _name: str, answer: Any, kept: bool) -> None:
        with (
            patch.multiple("posthoganalytics", disabled=False, feature_flag_definitions=lambda: [{"key": "x"}]),
            patch(FLAG_READ_TARGET, return_value=answer) as flag_read,
        ):
            assert live_gate_team_ids([self.team.id]) == ([self.team.id] if kept else [])

        assert flag_read.call_args == call(
            LIVE_GATE_FLAG,
            str(self.team.uuid),
            groups={"organization": str(self.organization.id), "project": str(self.team.id)},
            group_properties={
                "organization": {"id": str(self.organization.id)},
                "project": {"id": str(self.team.id), "uuid": str(self.team.uuid)},
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )

    @parameterized.expand(
        [
            ("sdk_off_by_configuration", True, [{"key": "x"}]),
            ("no_definitions_loaded", False, None),
        ]
    )
    def test_the_gate_reads_no_flag_when_the_sdk_cannot_answer(
        self, _name: str, disabled: bool, definitions: Any
    ) -> None:
        with (
            patch.multiple("posthoganalytics", disabled=disabled, feature_flag_definitions=lambda: definitions),
            patch(FLAG_READ_TARGET) as flag_read,
        ):
            assert live_gate_team_ids([self.team.id]) == []

        flag_read.assert_not_called()
