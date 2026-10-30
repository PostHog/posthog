from dataclasses import replace
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog

from products.experiments.backend.facade.contracts import ExperimentHealthReaderAccess
from products.experiments.backend.health.context import PauseHistory
from products.experiments.backend.health.pause_history import load_pause_history
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag

LAUNCHED_AT = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
FULL_ACCESS = ExperimentHealthReaderAccess(
    can_read_flag_history=True, can_query_events=True, denied_event_properties=frozenset()
)


def _history(paused_after_hours: int | None) -> PauseHistory:
    return PauseHistory(
        launched_at=LAUNCHED_AT,
        team_timezone="UTC",
        paused_at=None if paused_after_hours is None else LAUNCHED_AT + timedelta(hours=paused_after_hours),
    )


class TestLoadPauseHistory(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="paused-flag", active=False)
        self.experiment = Experiment.objects.create(
            team=self.team, name="Paused", feature_flag=flag, start_date=LAUNCHED_AT
        )
        self.other_experiment = Experiment.objects.create(
            team=self.team, name="Other", feature_flag=flag, start_date=LAUNCHED_AT
        )

    @parameterized.expand(
        [
            (
                "latest_entry_is_a_pause",
                [("paused", 1, True), ("resumed", 2, True), ("paused", 3, True)],
                FULL_ACCESS,
                _history(3),
            ),
            ("latest_entry_is_a_resume", [("paused", 1, True), ("resumed", 2, True)], FULL_ACCESS, _history(None)),
            ("pause_before_this_launch", [("paused", -1, True)], FULL_ACCESS, _history(None)),
            ("pause_of_another_experiment", [("resumed", 2, True), ("paused", 3, False)], FULL_ACCESS, _history(None)),
            (
                "reader_without_history_access",
                [("paused", 1, True)],
                replace(FULL_ACCESS, can_read_flag_history=False),
                None,
            ),
        ]
    )
    def test_reads_the_latest_pause_or_resume_since_launch(
        self,
        _name: str,
        entries: list[tuple[str, int, bool]],
        reader_access: ExperimentHealthReaderAccess,
        expected: PauseHistory | None,
    ) -> None:
        for activity, hours_after_launch, own in entries:
            ActivityLog.objects.create(
                team_id=self.team.id,
                organization_id=self.organization.id,
                scope="Experiment",
                item_id=str((self.experiment if own else self.other_experiment).id),
                activity=activity,
                created_at=LAUNCHED_AT + timedelta(hours=hours_after_launch),
            )

        self.assertEqual(load_pause_history(self.experiment, reader_access=reader_access), expected)
