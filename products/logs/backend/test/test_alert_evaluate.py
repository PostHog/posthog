from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.errors import ExposedHogQLError

from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import due_checks, record_outcomes, slot_of
from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    PlatformConfigurationSnapshot,
    SourceBatchEvaluation,
    SourceKind,
)
from products.alerts_platform.backend.facade.lifecycle import AlertState
from products.alerts_platform.backend.facade.temporal import SOURCE_EVALUATION_TIMEOUT
from products.logs.backend.alert_check_query import BatchedBucketedResult, BucketedCount
from products.logs.backend.alert_source_cycle import BATCH_QUERY_BUDGET_SECONDS, MAX_QUERY_SECONDS, evaluate_logs_batch
from products.logs.backend.models import LogsAlertConfiguration, LogsAlertEvent
from products.logs.backend.temporal.alert_evaluate import (
    EVALUATE_SCHEDULE_TO_CLOSE,
    EVALUATE_START_TO_CLOSE,
    EVALUATION_BUDGET,
)

_MODULE = "products.logs.backend.alert_source_cycle"
_LOGS_OWNED_FIELDS = ("state", "consecutive_failures", "next_check_at", "last_notified_at", "snooze_until")


class TestLogsAlertEvaluation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.cutoff = datetime(2026, 9, 16, 10, tzinfo=UTC)

    def _configuration(self, **overrides: Any) -> PlatformConfigurationSnapshot:
        defaults: dict[str, Any] = {
            "team_id": self.team.id,
            "name": "API errors",
            "source_kind": SourceKind.LOGS,
            "source_config": {},
            "threshold_count": 10,
            "threshold_operator": "above",
            "window_minutes": 5,
            "check_interval_minutes": 10,
            "next_check_at": self.cutoff - timedelta(minutes=1),
        }
        defaults.update(overrides)
        with team_scope(self.team.id):
            return platform_testing.create_configuration(**defaults)

    def _run(
        self,
        *configurations: PlatformConfigurationSnapshot,
        query_error: Exception | None = None,
        now: datetime | None = None,
    ) -> tuple[SourceBatchEvaluation, MagicMock]:
        now = now or self.cutoff
        breaching = {str(c.id): [BucketedCount(timestamp=now, count=500)] for c in configurations}
        with (
            patch(f"{_MODULE}.fetch_live_logs_checkpoint", return_value=None),
            patch(f"{_MODULE}.BatchedAlertCheckQuery") as query,
        ):
            if query_error is not None:
                query.return_value.execute_rolling_checks.side_effect = query_error
            else:
                query.return_value.execute_rolling_checks.return_value = BatchedBucketedResult(
                    per_alert=breaching, query_duration_ms=1
                )
            slot = slot_of(configurations[0].next_check_at, now)
            return evaluate_logs_batch(self.team.id, slot, now), query

    def _slot(self) -> str:
        return slot_of(self.cutoff - timedelta(minutes=1), self.cutoff)

    def _record(self, evaluation: SourceBatchEvaluation) -> None:
        """The write the platform's own activity runs after the evaluation returns.

        Deliberately outside `team_scope`: that activity has no ambient scope, and these models
        are fail-closed, so a write here through a bare manager raises.
        """
        record_outcomes(self.team.id, evaluation.outcomes, self.cutoff)

    def test_a_breaching_configuration_fires_and_records_its_own_state(self) -> None:
        configuration = self._configuration()

        evaluation, _ = self._run(configuration)
        self._record(evaluation)

        assert [(o.kind, o.value) for o in evaluation.outcomes] == [(AlertEventKind.FIRING, 500.0)]
        with team_scope(self.team.id):
            alert = platform_testing.alert_for(configuration.id)
            assert alert is not None
            configuration = platform_testing.configuration(configuration.id)
        assert alert.state == AlertState.FIRING
        assert alert.last_notified_at is not None
        # The schedule advanced, so the next tick does not rediscover this configuration.
        assert configuration.next_check_at is not None
        assert configuration.next_check_at > self.cutoff

    def test_a_cohort_query_is_capped_below_the_batch_budget(self) -> None:
        _, query = self._run(self._configuration())

        # An uncapped query runs to the class default, which is above the whole batch's budget.
        capped = query.call_args.kwargs["max_execution_time"]
        assert 0 < capped <= MAX_QUERY_SECONDS

    def test_the_evaluation_writes_nothing_until_its_outcomes_are_recorded(self) -> None:
        configuration = self._configuration()

        evaluation, _ = self._run(configuration)

        assert evaluation.deliveries
        with team_scope(self.team.id):
            configuration = platform_testing.configuration(configuration.id)
            assert platform_testing.alert_for(configuration.id) is None
        assert configuration.next_check_at == self.cutoff - timedelta(minutes=1)

    def test_a_delivery_the_batch_cannot_carry_leaves_its_alert_due(self) -> None:
        configurations = [self._configuration(), self._configuration()]

        with patch(f"{_MODULE}.MAX_DELIVERIES_PER_CYCLE", 1):
            evaluation, _ = self._run(*configurations)
        self._record(evaluation)

        # A firing alert does not fire again, so recording the second outcome would retire its
        # breach with no delivery to announce it.
        assert len(evaluation.deliveries) == 1
        assert evaluation.omitted == 1
        with team_scope(self.team.id):
            still_due = platform_testing.count_still_due([c.id for c in configurations], at=self.cutoff)
        assert still_due == 1

    def test_two_scheduled_checks_clamped_to_one_window_keep_distinct_keys(self) -> None:
        # `resolve_alert_date_to` clamps the window end to the ingestion checkpoint, so a
        # checkpoint that has not moved gives two consecutive checks the same window. Keyed on the
        # window alone they read as one evaluation, and a reader deduplicating on the key drops
        # the second.
        configuration = self._configuration()
        # Inside CHECKPOINT_MAX_STALENESS and behind both scheduled times, so both checks clamp
        # their window end to it.
        frozen_checkpoint = self.cutoff - timedelta(minutes=3)

        def run_at(next_check_at: datetime) -> str:
            with team_scope(self.team.id):
                platform_testing.set_due_at(configuration.id, next_check_at)
            with (
                patch(f"{_MODULE}.fetch_live_logs_checkpoint", return_value=frozen_checkpoint),
                patch(f"{_MODULE}.BatchedAlertCheckQuery") as query,
            ):
                query.return_value.execute_rolling_checks.return_value = BatchedBucketedResult(
                    per_alert={str(configuration.id): [BucketedCount(timestamp=self.cutoff, count=500)]},
                    query_duration_ms=1,
                )
                slot = slot_of(next_check_at, self.cutoff)
                evaluation = evaluate_logs_batch(self.team.id, slot, self.cutoff)
            return evaluation.outcomes[0].evaluation_key

        first = run_at(self.cutoff - timedelta(minutes=2))
        second = run_at(self.cutoff - timedelta(minutes=1))

        assert first != second

    def test_a_check_inside_quiet_hours_runs_and_holds_its_announcement(self) -> None:
        configuration = self._configuration(
            schedule_restriction={"blocked_windows": [{"start": "09:00", "end": "12:00"}]}
        )

        evaluation, query = self._run(configuration)
        self._record(evaluation)

        query.assert_called_once()
        assert evaluation.deliveries == ()
        with team_scope(self.team.id):
            alert = platform_testing.alert_for(configuration.id)
            assert alert is not None
            configuration = platform_testing.configuration(configuration.id)
        # An incident wholly inside the window must still leave a trace, and must not move the cooldown.
        assert alert.state == AlertState.FIRING
        assert alert.last_notified_at is None
        assert alert.firing_started_at == self.cutoff
        # Parked at the end of the window would leave the alert unevaluated until noon.
        assert configuration.next_check_at is not None
        assert self.cutoff < configuration.next_check_at < datetime(2026, 9, 16, 11, tzinfo=UTC)

        # The first check after the window announces the fire the mute held. Without the held
        # firing reaching it, a FIRING alert does not fire again on its own and stays silent.
        unmuted, _ = self._run(configuration, now=datetime(2026, 9, 16, 12, 30, tzinfo=UTC))

        assert [o.kind for o in unmuted.outcomes] == [AlertEventKind.FIRING]

    def test_a_broken_filter_config_stops_being_discovered(self) -> None:
        configuration = self._configuration(source_config={"filterGroup": {"type": "nonsense"}})

        evaluation, query = self._run(configuration)
        self._record(evaluation)

        query.assert_not_called()
        with team_scope(self.team.id):
            alert = platform_testing.alert_for(configuration.id)
            assert alert is not None
        assert alert.state == AlertState.BROKEN
        assert due_checks(self.team.id, SourceKind.LOGS.value, self._slot(), self.cutoff + timedelta(hours=1)) == ()

    @parameterized.expand(
        [
            ("a_transient_error_holds_the_counter", ValueError("cluster busy"), 4, "not_firing"),
            ("an_invalid_query_escalates", ExposedHogQLError("unknown field"), 5, "broken"),
        ]
    )
    def test_a_failed_query_advances_the_schedule_instead_of_leaving_the_check_due(
        self, _name: str, error: Exception, expected_failures: int, expected_state: str
    ) -> None:
        configuration = self._configuration(consecutive_failures=4)

        evaluation, _ = self._run(configuration, query_error=error)
        self._record(evaluation)

        assert [o.consecutive_failures for o in evaluation.outcomes] == [expected_failures]
        with team_scope(self.team.id):
            alert = platform_testing.alert_for(configuration.id)
            assert alert is not None
            configuration = platform_testing.configuration(configuration.id)
        assert alert.state == expected_state
        assert configuration.next_check_at is not None
        assert configuration.next_check_at > self.cutoff

    def test_a_failure_the_batch_cannot_record_leaves_the_whole_batch_due(self) -> None:
        configuration = self._configuration(consecutive_failures=4)

        with patch(f"{_MODULE}._delivery", side_effect=RuntimeError("something after the query failed")):
            with pytest.raises(RuntimeError):
                self._run(configuration, query_error=ExposedHogQLError("unknown field"))

        with team_scope(self.team.id):
            configuration = platform_testing.configuration(configuration.id)
            assert platform_testing.alert_for(configuration.id) is None
        assert configuration.next_check_at == self.cutoff - timedelta(minutes=1)

    def test_the_logs_product_rows_are_never_written(self) -> None:
        legacy = LogsAlertConfiguration.objects.create(
            team=self.team,
            name="API errors",
            threshold_count=10,
            threshold_operator="above",
            window_minutes=5,
            filters={},
            next_check_at=self.cutoff - timedelta(minutes=1),
        )
        before = LogsAlertConfiguration.objects.values(*_LOGS_OWNED_FIELDS).get(id=legacy.id)

        evaluation, _ = self._run(self._configuration(legacy_configuration_id=legacy.id))
        self._record(evaluation)

        # The logs fleet evaluates this same alert on its own queue. Writing its rows here would
        # transition an alert twice and notify a person twice for one breach.
        assert LogsAlertConfiguration.objects.values(*_LOGS_OWNED_FIELDS).get(id=legacy.id) == before
        assert not LogsAlertEvent.objects.filter(alert=legacy).exists()

    @parameterized.expand([("single_period", 1, 5), ("three_periods", 3, 25)])
    def test_the_scanned_range_covers_every_rolling_window(
        self, _name: str, evaluation_periods: int, expected_lookback_minutes: int
    ) -> None:
        configuration = self._configuration(evaluation_periods=evaluation_periods, check_interval_minutes=10)

        _, query = self._run(configuration)

        kwargs = query.call_args.kwargs
        assert kwargs["date_to"] - kwargs["date_from"] == timedelta(minutes=expected_lookback_minutes)

    def test_a_preview_and_its_recorded_outcome_name_the_same_evaluation(self) -> None:
        configuration = self._configuration(next_check_at=None)

        evaluation, _ = self._run(configuration)

        # A preview carries the recorded key unchanged, so a delivery can address the row the
        # check wrote. The slot is in the key because two checks of one alert can clamp to the
        # same window end, and a key without it makes them one evaluation to any reader.
        expected = f"slot:{self.cutoff.isoformat()}|window:{self.cutoff.isoformat()}"
        assert evaluation.outcomes[0].evaluation_key == expected
        assert [d.evaluation_key for d in evaluation.deliveries] == [expected]


class TestEvaluationTimeoutLadder(SimpleTestCase):
    """Constants only, so this takes no database."""

    def test_the_evaluation_timeout_ladder_holds(self) -> None:
        # Each bound here has been wrong once. The activity sat under the query, and two
        # activities declared eighty seconds inside a forty-second workflow. A timeout that
        # lands between deciding and recording loses a batch that decided to fire, and nothing
        # else in the tree notices.
        # ClickHouse ends a slow query, not the activity timing out with the query still running.
        assert EVALUATE_START_TO_CLOSE.total_seconds() > BATCH_QUERY_BUDGET_SECONDS > MAX_QUERY_SECONDS
        # Temporal bounds an attempt by whichever timeout expires first, so queue time must not be
        # what shortens the run below the query budget.
        assert EVALUATE_SCHEDULE_TO_CLOSE > EVALUATE_START_TO_CLOSE
        assert (EVALUATE_SCHEDULE_TO_CLOSE - EVALUATE_START_TO_CLOSE).total_seconds() >= BATCH_QUERY_BUDGET_SECONDS / 2
        # The platform's own timeout holds both activities and still leaves room for the deliveries.
        assert SOURCE_EVALUATION_TIMEOUT > EVALUATION_BUDGET
