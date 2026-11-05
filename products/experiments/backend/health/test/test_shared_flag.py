from dataclasses import replace
from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest import TestCase

from parameterized import parameterized

from products.experiments.backend.facade.contracts import (
    ExperimentHealthCheckStatus,
    ExperimentHealthFinding,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.checks.shared_flag import flag_shared
from products.experiments.backend.health.context import ExperimentOnFlag, load_health_context, parse_flag_state
from products.experiments.backend.health.skips import CheckSkip
from products.experiments.backend.health.test.factories import DRAFT, ENDED, RUNNING, RUNNING_CONTEXT, Status
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag

LAUNCHED_AT = datetime(2026, 10, 1, tzinfo=UTC)
ENDED_AT = datetime(2026, 10, 10, tzinfo=UTC)

RUNNING_OTHER = ExperimentOnFlag(launched_at=LAUNCHED_AT, ended_at=None, archived=False)
DRAFT_OTHER = ExperimentOnFlag(launched_at=None, ended_at=None, archived=False)
ENDED_OTHER = ExperimentOnFlag(launched_at=LAUNCHED_AT, ended_at=ENDED_AT, archived=False)
ARCHIVED_DRAFT_OTHER = ExperimentOnFlag(launched_at=None, ended_at=None, archived=True)

WARNING = ExperimentHealthFindingSeverity.WARNING
INFO = ExperimentHealthFindingSeverity.INFO

CONTEXT = replace(
    RUNNING_CONTEXT,
    flag=parse_flag_state(
        active=True,
        deleted=False,
        groups=[{"properties": [], "rollout_percentage": 100}],
        variants=[{"key": "control", "rollout_percentage": 50}, {"key": "test", "rollout_percentage": 50}],
    ),
)


class TestFlagShared(TestCase):
    @parameterized.expand(
        [
            (
                "running_with_a_running_experiment",
                RUNNING,
                (RUNNING_OTHER,),
                ("running_flag_shared_with_running", WARNING, {"other_running_experiments": 1}),
            ),
            (
                "running_with_running_and_draft_experiments",
                RUNNING,
                (DRAFT_OTHER, RUNNING_OTHER, RUNNING_OTHER),
                ("running_flag_shared_with_running", WARNING, {"other_running_experiments": 2}),
            ),
            (
                "running_with_a_draft",
                RUNNING,
                (DRAFT_OTHER, ENDED_OTHER),
                ("running_flag_shared_with_draft", INFO, {"other_draft_experiments": 1}),
            ),
            ("running_after_an_ended_experiment", RUNNING, (ENDED_OTHER,), None),
            ("running_with_an_archived_draft", RUNNING, (ARCHIVED_DRAFT_OTHER,), None),
            (
                "draft_on_the_flag_of_a_running_experiment",
                DRAFT,
                (RUNNING_OTHER, DRAFT_OTHER),
                ("draft_flag_shared_with_running", WARNING, {"other_running_experiments": 1}),
            ),
            ("draft_with_another_draft", DRAFT, (DRAFT_OTHER, ENDED_OTHER), None),
        ]
    )
    def test_flag_shared(
        self,
        _name: str,
        status: Status,
        others: tuple[ExperimentOnFlag, ...],
        expected: tuple[str, ExperimentHealthFindingSeverity, dict[str, int]] | None,
    ) -> None:
        finding = flag_shared(replace(CONTEXT, **status, other_experiments_on_flag=others))

        if expected is None:
            self.assertIsNone(finding)
            return
        assert isinstance(finding, ExperimentHealthFinding)
        self.assertEqual((finding.subcode, finding.severity, dict(finding.evidence)), expected)

    def test_leaves_an_ended_experiment_to_the_flag_state_check(self) -> None:
        outcome = flag_shared(replace(CONTEXT, **ENDED, other_experiments_on_flag=(RUNNING_OTHER,)))

        assert isinstance(outcome, CheckSkip)
        self.assertEqual(outcome.status, ExperimentHealthCheckStatus.NOT_APPLICABLE)


class TestFlagSharedLoadsTheOtherExperiments(BaseTest):
    @parameterized.expand(
        [
            ("running_experiment_on_the_flag", False, "running_flag_shared_with_running"),
            ("deleted_experiment_on_the_flag", True, None),
        ]
    )
    def test_reads_the_other_experiments_of_a_running_experiment(
        self, _name: str, other_deleted: bool, expected_subcode: str | None
    ) -> None:
        flag = FeatureFlag.objects.create(team=self.team, key="checkout-test", created_by=self.user)
        experiment = Experiment.objects.create(team=self.team, name="exp", feature_flag=flag, start_date=LAUNCHED_AT)
        Experiment.objects.create(
            team=self.team, name="other", feature_flag=flag, start_date=LAUNCHED_AT, deleted=other_deleted
        )

        finding = flag_shared(load_health_context(experiment))

        self.assertEqual(finding.subcode if isinstance(finding, ExperimentHealthFinding) else finding, expected_subcode)
