from datetime import UTC, datetime, timedelta

import time_machine
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.errors import ExposedHogQLError

from posthog.errors import ClickHouseAtCapacity, ClickHouseQueryTimeOut, ExposedCHQueryError

from products.logs.backend.alert_check_query import BucketedCount, resolve_alert_date_to
from products.logs.backend.alert_comparison import compare_logs_alert_cohort
from products.logs.backend.alert_evaluation import evaluate_logs_alert
from products.logs.backend.alert_state_machine import AlertState, NotificationAction
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.temporal.activities import (
    _AlertCohort,
    _CohortQueryResult,
    _evaluate_single_alert,
    _PrefetchedQuery,
)

NOW = datetime(2026, 6, 1, 12, tzinfo=UTC)


class TestLogsAlertEvaluation(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(time_machine.travel(NOW, tick=False))
        self.effects = [
            self.enterContext(patch(target))
            for target in (
                "products.logs.backend.alert_check_query.execute_hogql_query",
                "products.logs.backend.temporal.activities.produce_alert_internal_event",
                "products.logs.backend.temporal.activities.capture_exception",
                "products.logs.backend.temporal.activities.record_clickhouse_duration",
                "products.logs.backend.temporal.activities.record_scheduler_lag",
                "products.logs.backend.temporal.activities.increment_check_errors",
            )
        ]

    def tearDown(self) -> None:
        for effect in self.effects:
            effect.assert_not_called()
        super().tearDown()

    def alert(self, **overrides: object) -> LogsAlertConfiguration:
        fields: dict[str, object] = {
            "team_id": 1,
            "name": "Example service alert",
            "threshold_count": 100,
            "next_check_at": NOW,
            "evaluation_periods": 3,
            "datapoints_to_alarm": 2,
        }
        fields.update(overrides)
        return LogsAlertConfiguration(**fields)

    def buckets(self, counts: list[int], date_to: datetime = NOW) -> list[BucketedCount]:
        return [
            BucketedCount(timestamp=date_to - timedelta(minutes=5 * (len(counts) - i)), count=count)
            for i, count in enumerate(counts)
        ]

    @parameterized.expand(
        [
            ("above", [101, 101, 100], (False, True, True), NotificationAction.FIRE),
            ("above", [0, 100, 101], (True, False, False), NotificationAction.NONE),
            ("below", [99, 0, 100], (False, True, True), NotificationAction.FIRE),
            ("below", [100, 101, 0], (True, False, False), NotificationAction.NONE),
            ("above", [], (False, False, False), NotificationAction.NONE),
            ("below", [], (True, True, True), NotificationAction.FIRE),
            ("below", [100], (False, True, True), NotificationAction.FIRE),
        ]
    )
    def test_shared_comparator_preserves_bucket_evidence(
        self, operator: str, counts: list[int], breaches: tuple[bool, ...], action: NotificationAction
    ) -> None:
        alert = self.alert(threshold_operator=operator)
        cohort = _AlertCohort(alerts=(alert,), date_to=NOW, projection_eligible=True)
        query = _CohortQueryResult(per_alert={str(alert.id): _PrefetchedQuery(buckets=self.buckets(counts))})
        comparison = compare_logs_alert_cohort(cohort, query, now=NOW, checkpoint=None)[0]

        assert comparison.adapted.breaches == breaches
        assert [r.value for r in comparison.adapted.bucket_results] == list(reversed(counts)) + [0] * (3 - len(counts))
        assert comparison.adapted.check.result_count == (counts[-1] if counts else 0)
        assert comparison.proposed_outcome.notification == action
        assert comparison.proposed_outcome.new_state == (
            AlertState.FIRING if action == NotificationAction.FIRE else AlertState.NOT_FIRING
        )
        assert comparison.counts_match and comparison.evidence_matches and comparison.errors_match
        assert comparison.lifecycle_matches and comparison.notifications_match and comparison.windows_match
        assert alert.state == AlertState.NOT_FIRING
        assert alert.next_check_at == NOW

    @parameterized.expand(
        [
            (RuntimeError("synthetic failure"), "unknown", 2, 2, NotificationAction.NONE),
            (ClickHouseAtCapacity("synthetic capacity limit"), "server_busy", 2, 2, NotificationAction.NONE),
            (ClickHouseQueryTimeOut("synthetic timeout"), "query_performance", 0, 1, NotificationAction.ERROR),
            (ExposedHogQLError("Invalid example filter"), "invalid_query", 4, 5, NotificationAction.BROKEN),
            (
                ExposedCHQueryError(
                    "DB::Exception: Invalid example identifier\nStack trace: synthetic",
                    code=47,
                    code_name="unknown_identifier",
                    nested=RuntimeError("synthetic nested failure"),
                ),
                "invalid_query",
                0,
                1,
                NotificationAction.ERROR,
            ),
        ]
    )
    def test_repeated_shared_query_errors_preserve_input_and_classification(
        self, error: Exception, code: str, failures: int, expected_failures: int, action: NotificationAction
    ) -> None:
        alerts = tuple(self.alert(state=AlertState.FIRING, consecutive_failures=failures) for _ in range(2))
        cohort = _AlertCohort(alerts=alerts, date_to=NOW, projection_eligible=True)
        query = _CohortQueryResult(per_alert={str(alert.id): _PrefetchedQuery(error=error) for alert in alerts})
        for with_traceback in (False, True):
            if with_traceback:
                try:
                    raise error
                except Exception:
                    pass
            original_traceback = error.__traceback__
            original_attributes = vars(error).copy()
            for _ in range(3):
                results = compare_logs_alert_cohort(cohort, query, now=NOW, checkpoint=None)
                assert error.__traceback__ is original_traceback
                assert vars(error) == original_attributes
                for result in results:
                    assert result.adapted.error_code == code
                    assert result.adapted.check.result_count is None
                    assert result.adapted.bucket_results == ()
                    assert result.adapted.breaches == ()
                    assert result.proposed_outcome.consecutive_failures == expected_failures
                    assert result.proposed_outcome.notification == action
                    assert result.proposed_outcome.new_state == (
                        AlertState.BROKEN if action == NotificationAction.BROKEN else AlertState.FIRING
                    )
                    assert result.errors_match and result.lifecycle_matches and result.notifications_match
                    if isinstance(error, ExposedCHQueryError):
                        assert result.legacy.check_result.error_message == "Invalid example identifier"

    @parameterized.expand(
        [
            (AlertState.FIRING, [0, 0, 0], 0, None, AlertState.NOT_FIRING, NotificationAction.RESOLVE),
            (AlertState.NOT_FIRING, [101, 101, 0], 10, None, AlertState.FIRING, NotificationAction.NONE),
            (
                AlertState.SNOOZED,
                [101, 101, 0],
                0,
                NOW + timedelta(minutes=5),
                AlertState.SNOOZED,
                NotificationAction.NONE,
            ),
        ]
    )
    def test_proposed_lifecycle_is_not_a_delivery(
        self,
        state: AlertState,
        counts: list[int],
        cooldown: int,
        snooze: datetime | None,
        expected_state: AlertState,
        action: NotificationAction,
    ) -> None:
        alert = self.alert(state=state, cooldown_minutes=cooldown, last_notified_at=NOW, snooze_until=snooze)
        result = compare_logs_alert_cohort(
            _AlertCohort(alerts=(alert,), date_to=NOW, projection_eligible=True),
            _CohortQueryResult(per_alert={str(alert.id): _PrefetchedQuery(buckets=self.buckets(counts))}),
            now=NOW,
            checkpoint=None,
        )[0]
        assert result.proposed_outcome.new_state == expected_state
        assert result.proposed_outcome.notification == action
        assert result.lifecycle_matches and result.notifications_match
        assert alert.state == state

    @parameterized.expand([(None, True), (timedelta(minutes=6), True), (timedelta(minutes=2), False)])
    def test_frozen_batch_retries_expose_legacy_reported_window_mismatch(
        self, lag: timedelta | None, windows_match: bool
    ) -> None:
        checkpoint = NOW - lag if lag else None
        date_to = resolve_alert_date_to(NOW, checkpoint)
        alerts = (self.alert(), self.alert(threshold_operator="below"))
        cohort = _AlertCohort(alerts=alerts, date_to=date_to, projection_eligible=True)
        query = _CohortQueryResult(
            per_alert={
                str(alerts[0].id): _PrefetchedQuery(buckets=self.buckets([101, 101, 0], date_to)),
                str(alerts[1].id): _PrefetchedQuery(buckets=self.buckets([101, 101, 101], date_to)),
            }
        )
        first = compare_logs_alert_cohort(cohort, query, now=NOW, checkpoint=checkpoint)
        with time_machine.travel(NOW + timedelta(days=10), tick=False):
            retry = compare_logs_alert_cohort(cohort, query, now=NOW, checkpoint=checkpoint)
        assert first == retry
        assert [c.proposed_outcome.notification for c in first] == [NotificationAction.FIRE, NotificationAction.NONE]
        for result in first:
            assert result.windows_match is windows_match
            assert result.legacy.date_to == NOW
            assert result.query_date_to == date_to
            assert result.query_date_from == date_to - timedelta(minutes=15)
            assert result.counts_match and result.evidence_matches
        alerts[0].filters["serviceNames"] = ["changed-after-comparison"]
        assert first[0].legacy.alert.filters == {}

    def test_missing_result_fails_closed_instead_of_querying(self) -> None:
        alert = self.alert()
        cohort = _AlertCohort(alerts=(alert,), date_to=NOW, projection_eligible=True)
        for per_alert in (
            {},
            {str(alert.id): _PrefetchedQuery()},
            {str(alert.id): _PrefetchedQuery(buckets=self.buckets([1], NOW + timedelta(minutes=1)))},
            {str(alert.id): _PrefetchedQuery(buckets=list(reversed(self.buckets([1, 2]))))},
            {str(alert.id): _PrefetchedQuery(buckets=self.buckets([1]) * 2)},
        ):
            with self.assertRaises(ValueError):
                compare_logs_alert_cohort(cohort, _CohortQueryResult(per_alert=per_alert), now=NOW, checkpoint=None)
        with self.assertRaises(ValueError):
            compare_logs_alert_cohort(
                cohort,
                _CohortQueryResult(per_alert={str(alert.id): _PrefetchedQuery(buckets=[])}),
                now=NOW,
                checkpoint=NOW - timedelta(minutes=1),
            )
        with self.assertRaises(ValueError):
            evaluate_logs_alert(alert, buckets=None)

    def test_legacy_diagnostics_remain_enabled_by_default(self) -> None:
        alert = self.alert(next_check_at=NOW - timedelta(minutes=1))
        _evaluate_single_alert(alert, NOW, prefetched=_PrefetchedQuery(buckets=[], query_duration_ms=7))
        self.effects[3].assert_called_once_with(7)
        self.effects[4].assert_called_once_with(60_000)
        self.effects[3].reset_mock()
        self.effects[4].reset_mock()
        error = ClickHouseQueryTimeOut("synthetic timeout")
        _evaluate_single_alert(alert, NOW, prefetched=_PrefetchedQuery(error=error))
        self.effects[2].assert_called_once_with(
            error, {"alert_id": str(alert.id), "classification": "query_performance"}
        )
        self.effects[5].assert_called_once_with("query_performance")
        for effect in self.effects:
            effect.reset_mock()
