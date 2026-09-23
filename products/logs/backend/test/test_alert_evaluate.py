from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.alerts.backend.facade.contracts import SourceBatchEvaluation
from products.alerts.backend.facade.platform_alerts import record_outcomes
from products.alerts.backend.facade.temporal import SOURCE_EVALUATION_TIMEOUT
from products.alerts.backend.models import PlatformAlert, PlatformAlertConfiguration
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

    def _configuration(self, **overrides) -> PlatformAlertConfiguration:
        defaults = {
            "team": self.team,
            "name": "API errors",
            "source_kind": PlatformAlertConfiguration.SourceKind.LOGS,
            "source_config": {},
            "threshold_count": 10,
            "threshold_operator": "above",
            "window_minutes": 5,
            "check_interval_minutes": 10,
            "next_check_at": self.cutoff - timedelta(minutes=1),
        }
        defaults.update(overrides)
        with team_scope(self.team.id):
            return PlatformAlertConfiguration.objects.create(**defaults)

    def _run(self, *configurations: PlatformAlertConfiguration):
        breaching = {str(c.id): [BucketedCount(timestamp=self.cutoff, count=500)] for c in configurations}
        with (
            patch(f"{_MODULE}.fetch_live_logs_checkpoint", return_value=None),
            patch(f"{_MODULE}.BatchedAlertCheckQuery") as query,
        ):
            query.return_value.execute_rolling_checks.return_value = BatchedBucketedResult(
                per_alert=breaching, query_duration_ms=1
            )
            slot = (configurations[0].next_check_at or self.cutoff).replace(second=0, microsecond=0).isoformat()
            return evaluate_logs_batch(self.team.id, slot, self.cutoff), query

    def _record(self, evaluation: SourceBatchEvaluation) -> None:
        """The write the platform's own activity runs after the evaluation returns.

        Deliberately outside `team_scope`: that activity has no ambient scope, and these models
        are fail-closed, so a write here through a bare manager raises.
        """
        record_outcomes(self.team.id, evaluation.outcomes, self.cutoff, team_timezone=self.team.timezone)

    def test_a_breaching_configuration_fires_and_records_its_own_state(self) -> None:
        configuration = self._configuration()

        evaluation, _ = self._run(configuration)
        self._record(evaluation)

        assert [t.notification for preview in evaluation.previews for t in preview.transitions] == ["fire"]
        with team_scope(self.team.id):
            alert = PlatformAlert.objects.get(configuration=configuration, grouping_key="")
            configuration.refresh_from_db()
        assert alert.state == PlatformAlert.State.FIRING
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

        assert evaluation.previews
        with team_scope(self.team.id):
            configuration.refresh_from_db()
            assert not PlatformAlert.objects.filter(configuration=configuration).exists()
        assert configuration.next_check_at == self.cutoff - timedelta(minutes=1)

    def test_a_delivery_the_batch_cannot_carry_leaves_its_alert_due(self) -> None:
        configurations = [self._configuration(), self._configuration()]

        with patch(f"{_MODULE}.MAX_PREVIEWS_PER_CYCLE", 1):
            evaluation, _ = self._run(*configurations)
        self._record(evaluation)

        # A firing alert does not fire again, so recording the second outcome would retire its
        # breach with no delivery to announce it.
        assert len(evaluation.previews) == 1
        assert evaluation.omitted == 1
        with team_scope(self.team.id):
            still_due = PlatformAlertConfiguration.objects.filter(
                id__in=[c.id for c in configurations], next_check_at__lte=self.cutoff
            ).count()
        assert still_due == 1

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

    def test_the_evaluation_key_comes_from_the_tick_occasion_not_the_clock(self) -> None:
        configuration = self._configuration(next_check_at=None)

        evaluation, _ = self._run(configuration)

        assert [p.evaluation_key for p in evaluation.previews] == [
            f"{configuration.id}:window:{self.cutoff.isoformat()}"
        ]


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
