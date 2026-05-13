import json
import time
import asyncio
import datetime as dt
import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import unittest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import MagicMock, patch

from hypothesis import (
    given,
    settings,
    strategies as st,
)
from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.errors import QueryErrorCategory

from products.logs.backend.alert_check_query import AlertCheckQuery, BatchedBucketedResult, BucketedCount
from products.logs.backend.alert_state_machine import AlertState, NotificationAction
from products.logs.backend.models import LogsAlertConfiguration, LogsAlertEvent
from products.logs.backend.temporal.activities import (
    _AlertCohort,
    _derive_breaches,
    _dispatch_for_alert,
    _evaluate_single_alert,
    _finalize_alert,
    _save_cohort_outcomes,
)


def _evaluate_and_save_one(
    alert: LogsAlertConfiguration,
    now: datetime,
    stats: dict[str, int],
    *,
    checkpoint: datetime | None = None,
) -> None:
    """Test helper: run the full per-alert pipeline (eval → dispatch → save → finalize).

    Tests in `TestEvaluateSingleAlert` previously called the all-in-one
    `_evaluate_single_alert`, which is now eval-only. This helper composes the
    same end-to-end behaviour using the cohort save helpers (with a one-alert
    cohort) so test assertions on saved state and stats keep working.
    """
    eval_start = time.perf_counter()
    evaluation = _evaluate_single_alert(alert, now, checkpoint=checkpoint)
    dispatched = _dispatch_for_alert(evaluation, now)
    elapsed_ms = int((time.perf_counter() - eval_start) * 1000)
    saved, _failed = _save_cohort_outcomes([dispatched], now)
    if saved:
        _finalize_alert(saved[0], elapsed_ms, stats)
    else:
        stats["checked"] += 1
        stats["errored"] += 1


def _make_stats() -> dict[str, int]:
    return {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}


def _bucket_counts_for(counts: list[int]) -> list[BucketedCount]:
    """Build BucketedCount entries oldest-first matching `counts`."""
    base = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
    return [BucketedCount(timestamp=base + timedelta(minutes=i * 5), count=c) for i, c in enumerate(counts)]


def _mock_buckets(mock_query_cls: MagicMock, counts: list[int]) -> None:
    """Set AlertCheckQuery().execute_rolling_checks to return `counts` (oldest-first)."""
    mock_query_cls.return_value.execute_rolling_checks.return_value = _bucket_counts_for(counts)


def _mock_batched_buckets(mock_run_batched: MagicMock, counts: list[int]) -> None:
    """Set `_run_batched_query` to return a BatchedBucketedResult with `counts` for every alert in any cohort."""

    def fake(cohort: _AlertCohort) -> BatchedBucketedResult:
        return BatchedBucketedResult(
            per_alert={str(a.id): _bucket_counts_for(counts) for a in cohort.alerts},
            query_duration_ms=0,
        )

    mock_run_batched.side_effect = fake


class TestSaveCohortOutcomesFallback(APIBaseTest):
    """Bulk save fallback semantics: IntegrityError → per-alert UPDATE; other errors → propagate."""

    def setUp(self):
        super().setUp()
        for target in (
            "products.logs.backend.temporal.activities.record_cohort_save_duration",
            "products.logs.backend.temporal.activities.record_cohort_event_insert_duration",
            "products.logs.backend.temporal.activities.record_cohort_update_duration",
            "products.logs.backend.temporal.activities.increment_cohort_save_fallback",
        ):
            p = patch(target)
            p.start()
            self.addCleanup(p.stop)

    def _make_alert(self, **kwargs) -> LogsAlertConfiguration:
        defaults = {
            "team": self.team,
            "name": "Test Alert",
            "threshold_count": 10,
            "threshold_operator": "above",
            "window_minutes": 5,
            "filters": {},
        }
        defaults.update(kwargs)
        return LogsAlertConfiguration.objects.create(**defaults)

    def _make_dispatched(self, alert: LogsAlertConfiguration):
        from products.logs.backend.alert_state_machine import AlertCheckOutcome, CheckResult
        from products.logs.backend.temporal.activities import _AlertEvaluation, _DispatchedAlert

        outcome = AlertCheckOutcome(
            new_state=AlertState.NOT_FIRING,
            notification=NotificationAction.NONE,
            consecutive_failures=0,
            update_last_notified_at=False,
            error_message=None,
        )
        evaluation = _AlertEvaluation(
            alert=alert,
            outcome=outcome,
            check_result=CheckResult(result_count=0, threshold_breached=False, query_duration_ms=10),
            date_from=datetime(2025, 1, 1, 0, 0, tzinfo=UTC),
            date_to=datetime(2025, 1, 1, 0, 5, tzinfo=UTC),
            state_before=alert.state,
        )
        return _DispatchedAlert(evaluation=evaluation, notification_failed=False)

    @patch("products.logs.backend.temporal.activities.LogsAlertConfiguration.objects.bulk_update")
    def test_integrity_error_falls_back_to_per_alert(self, mock_bulk_update):
        # First call raises IntegrityError (bulk path); per-alert fallback then saves each alert.
        from django.db.utils import IntegrityError

        mock_bulk_update.side_effect = IntegrityError("constraint violation")
        alerts = [self._make_alert(name=f"a{i}") for i in range(3)]
        dispatched = [self._make_dispatched(a) for a in alerts]
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        # Should not raise.
        _save_cohort_outcomes(dispatched, now)

        # All three alerts should have been saved via per-alert fallback —
        # advance_next_check_at writes a future next_check_at, so we can verify
        # the fallback ran by checking each alert was persisted.
        for alert in alerts:
            alert.refresh_from_db()
            assert alert.last_checked_at == now

    @patch("products.logs.backend.temporal.activities.LogsAlertConfiguration.objects.bulk_update")
    def test_operational_error_propagates(self, mock_bulk_update):
        # Cluster-level failure — fallback would just retry against the same broken cluster.
        from django.db.utils import OperationalError

        mock_bulk_update.side_effect = OperationalError("connection lost")
        alerts = [self._make_alert(name=f"a{i}") for i in range(2)]
        dispatched = [self._make_dispatched(a) for a in alerts]
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        with self.assertRaises(OperationalError):
            _save_cohort_outcomes(dispatched, now)


class TestRunCohortQueryFallback(unittest.TestCase):
    @staticmethod
    def _make_cohort(n: int) -> _AlertCohort:
        alerts = tuple(MagicMock(id=f"alert-{i}", team_id=1, name=f"alert-{i}") for i in range(n))
        for a in alerts:
            a.window_minutes = 5
            a.evaluation_periods = 1
            a.check_interval_minutes = 5
        return _AlertCohort(
            alerts=alerts,
            date_to=datetime(2025, 1, 1, 0, 5, 0, tzinfo=UTC),
            projection_eligible=True,
        )

    @patch("products.logs.backend.temporal.activities.increment_cohort_query_fallback")
    @patch("products.logs.backend.temporal.activities.classify_alert_error")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities._run_batched_query")
    def test_falls_back_to_per_alert_on_non_transient_failure(
        self, mock_batched, mock_alert_check_query_cls, mock_classify, mock_fallback_counter
    ):
        from products.logs.backend.temporal.activities import _run_cohort_query

        # Non-transient classification → fallback runs.
        mock_batched.side_effect = RuntimeError("query_performance error")
        mock_classify.return_value = MagicMock(is_transient=False, code="query_performance")

        # Per-alert AlertCheckQuery: alert-0 succeeds, alert-1 raises (the bad one).
        def make_query_instance(*, team, alert, **_kwargs):
            instance = MagicMock()
            if alert.id == "alert-1":
                instance.execute_rolling_checks.side_effect = RuntimeError("alert-1 also bad")
            else:
                instance.execute_rolling_checks.return_value = [
                    BucketedCount(timestamp=datetime(2025, 1, 1, 0, 0, tzinfo=UTC), count=42)
                ]
            return instance

        mock_alert_check_query_cls.side_effect = make_query_instance

        cohort = self._make_cohort(2)
        result = _run_cohort_query(cohort)

        # Fallback counter fired with the "batched_failure" reason (non-transient → fallback ran).
        mock_fallback_counter.assert_called_once_with("batched_failure")

        # Good alert has buckets, bad alert has the per-alert error captured.
        good = result.per_alert["alert-0"]
        bad = result.per_alert["alert-1"]
        assert good.buckets is not None and good.buckets[0].count == 42
        assert good.error is None
        assert bad.buckets is None
        assert bad.error is not None and "alert-1 also bad" in str(bad.error)

    @patch("products.logs.backend.temporal.activities.increment_cohort_query_fallback")
    @patch("products.logs.backend.temporal.activities.classify_alert_error")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities._run_batched_query")
    def test_skips_fallback_on_transient_error(
        self, mock_batched, mock_alert_check_query_cls, mock_classify, mock_fallback_counter
    ):
        # Transient classification → no fallback. Don't hammer a sick cluster.
        from products.logs.backend.temporal.activities import _run_cohort_query

        mock_batched.side_effect = RuntimeError("server busy")
        mock_classify.return_value = MagicMock(is_transient=True, code="server_busy")

        cohort = self._make_cohort(3)
        result = _run_cohort_query(cohort)

        # Fallback counter fired with the "transient_no_fallback" reason.
        mock_fallback_counter.assert_called_once_with("transient_no_fallback")
        # AlertCheckQuery is never instantiated because we don't run the fallback.
        mock_alert_check_query_cls.assert_not_called()

        # Every alert in the cohort gets the same error — no isolation needed
        # because the next cycle will retry once the cluster recovers.
        for alert in cohort.alerts:
            prefetched = result.per_alert[str(alert.id)]
            assert prefetched.buckets is None
            assert prefetched.error is not None and "server busy" in str(prefetched.error)

    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities._run_batched_query")
    def test_single_alert_cohort_skips_fallback(self, mock_batched, mock_alert_check_query_cls):
        from products.logs.backend.temporal.activities import _run_cohort_query

        mock_batched.side_effect = RuntimeError("query failed")

        cohort = self._make_cohort(1)
        result = _run_cohort_query(cohort)

        # No fallback for single-alert cohorts — the per-alert path would just hit the same error.
        mock_alert_check_query_cls.assert_not_called()
        assert "alert-0" in result.per_alert
        prefetched = result.per_alert["alert-0"]
        assert prefetched.error is not None and "query failed" in str(prefetched.error)

    @patch("products.logs.backend.temporal.activities._run_batched_query")
    def test_batched_success_skips_fallback(self, mock_batched):
        from products.logs.backend.alert_check_query import BatchedBucketedResult
        from products.logs.backend.temporal.activities import _run_cohort_query

        cohort = self._make_cohort(3)
        mock_batched.return_value = BatchedBucketedResult(
            per_alert={
                str(a.id): [BucketedCount(timestamp=datetime(2025, 1, 1, tzinfo=UTC), count=i)]
                for i, a in enumerate(cohort.alerts)
            },
            query_duration_ms=42,
        )

        result = _run_cohort_query(cohort)

        for i, alert in enumerate(cohort.alerts):
            prefetched = result.per_alert[str(alert.id)]
            assert prefetched.error is None
            assert prefetched.buckets is not None and prefetched.buckets[0].count == i
            assert prefetched.query_duration_ms == 42

    @patch("products.logs.backend.temporal.activities.increment_cohort_query_fallback")
    @patch("products.logs.backend.temporal.activities.classify_alert_error")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities._run_batched_query")
    def test_one_cohorts_failure_isolated_from_others(
        self, mock_batched, mock_alert_check_query_cls, mock_classify, _mock_fallback_counter
    ):
        # With cohort splitting at _cohort_manifests_from_alerts time, each post-split cohort is an
        # independent unit. _run_cohort_query operates on one bounded cohort at a time.
        # This test confirms a single cohort's batched failure → per-alert fallback works
        # as before. Cross-cohort isolation is structural (separate tasks, separate calls).
        from products.logs.backend.temporal.activities import _run_cohort_query

        cohort = self._make_cohort(2)
        mock_classify.return_value = MagicMock(is_transient=False, code="query_performance")
        mock_batched.side_effect = RuntimeError("batched failure")

        # Per-alert fallback returns synthetic buckets.
        def make_query_instance(*, team, alert, **_kwargs):
            instance = MagicMock()
            instance.execute_rolling_checks.return_value = [
                BucketedCount(timestamp=datetime(2025, 1, 1, tzinfo=UTC), count=7)
            ]
            return instance

        mock_alert_check_query_cls.side_effect = make_query_instance

        result = _run_cohort_query(cohort)

        for alert_id in ("alert-0", "alert-1"):
            prefetched = result.per_alert[alert_id]
            assert prefetched.buckets is not None and prefetched.buckets[0].count == 7


class TestRunCohortQueryFallbackEndToEnd(ClickhouseTestMixin, APIBaseTest):
    """CH-backed integration test for the per-alert fallback path."""

    def setUp(self):
        super().setUp()
        rows = [
            {
                "uuid": f"fallback-{i}",
                "team_id": self.team.id,
                "timestamp": ts,
                "body": "",
                "severity_text": "info",
                "severity_number": 9,
                "service_name": service,
                "resource_attributes": {},
                "attributes_map_str": {},
            }
            for i, (ts, service) in enumerate(
                [
                    ("2026-01-01 10:00:30", "fallback_service_a"),
                    ("2026-01-01 10:01:00", "fallback_service_a"),
                    ("2026-01-01 10:00:45", "fallback_service_a"),
                    ("2026-01-01 10:02:30", "fallback_service_b"),
                    ("2026-01-01 10:03:30", "fallback_service_b"),
                ]
            )
        ]
        sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in rows))

    def _make_alert(self, *, name: str, service: str) -> LogsAlertConfiguration:
        return LogsAlertConfiguration.objects.create(
            team=self.team,
            name=name,
            threshold_count=10,
            threshold_operator="above",
            window_minutes=5,
            evaluation_periods=1,
            filters={"serviceNames": [service]},
        )

    @freeze_time("2026-01-01T10:05:00Z")
    @patch("products.logs.backend.temporal.activities.classify_alert_error")
    @patch("products.logs.backend.temporal.activities.increment_cohort_query_fallback")
    @patch("products.logs.backend.temporal.activities._run_batched_query")
    def test_fallback_runs_per_alert_queries_against_real_clickhouse(self, mock_batched, _mock_counter, mock_classify):
        from products.logs.backend.temporal.activities import _AlertCohort, _run_cohort_query

        # Non-transient classification → fallback runs against real CH.
        mock_batched.side_effect = RuntimeError("batched query timed out")
        mock_classify.return_value = MagicMock(is_transient=False, code="query_performance")

        alert_a = self._make_alert(name="A", service="fallback_service_a")
        alert_b = self._make_alert(name="B", service="fallback_service_b")
        cohort = _AlertCohort(
            alerts=(alert_a, alert_b),
            date_to=datetime(2026, 1, 1, 10, 5, 0, tzinfo=UTC),
            projection_eligible=True,
        )

        result = _run_cohort_query(cohort)

        # Both alerts evaluated successfully via the per-alert fallback.
        prefetch_a = result.per_alert[str(alert_a.id)]
        prefetch_b = result.per_alert[str(alert_b.id)]
        assert prefetch_a.error is None and prefetch_a.buckets is not None
        assert prefetch_b.error is None and prefetch_b.buckets is not None

        # Bucket counts match the seeded data: 3 logs for service_a, 2 for service_b.
        assert sum(b.count for b in prefetch_a.buckets) == 3
        assert sum(b.count for b in prefetch_b.buckets) == 2

        # Per-alert query duration is captured (not the batched duration, which never
        # ran). Should be a non-negative integer for each.
        assert prefetch_a.query_duration_ms is not None and prefetch_a.query_duration_ms >= 0
        assert prefetch_b.query_duration_ms is not None and prefetch_b.query_duration_ms >= 0

    @freeze_time("2026-01-01T10:05:00Z")
    @patch("products.logs.backend.temporal.activities.classify_alert_error")
    @patch("products.logs.backend.temporal.activities.increment_cohort_query_fallback")
    @patch("products.logs.backend.temporal.activities._run_batched_query")
    def test_fallback_isolates_one_alerts_per_alert_failure(self, mock_batched, _mock_counter, mock_classify):
        # Force batched to fail with a non-transient classification (so fallback
        # runs); force ONE alert's per-alert query to also fail. Verify the other
        # alert still evaluates correctly against real CH and the bad alert's
        # error is captured per-alert (not propagated to the cohort).
        from products.logs.backend.temporal.activities import _AlertCohort, _run_cohort_query

        mock_batched.side_effect = RuntimeError("batched query timed out")
        mock_classify.return_value = MagicMock(is_transient=False, code="query_performance")

        good_alert = self._make_alert(name="good", service="fallback_service_a")
        bad_alert = self._make_alert(name="bad", service="fallback_service_b")
        cohort = _AlertCohort(
            alerts=(good_alert, bad_alert),
            date_to=datetime(2026, 1, 1, 10, 5, 0, tzinfo=UTC),
            projection_eligible=True,
        )

        # Selectively fail the per-alert query for bad_alert; let good_alert hit real CH.
        original_execute_rolling_checks = AlertCheckQuery.execute_rolling_checks

        def maybe_fail(self, *args, **kwargs):
            if self.alert.id == bad_alert.id:
                raise RuntimeError("simulated per-alert query failure")
            return original_execute_rolling_checks(self, *args, **kwargs)

        with patch.object(AlertCheckQuery, "execute_rolling_checks", maybe_fail):
            result = _run_cohort_query(cohort)

        # Good alert: real buckets, no error.
        good_prefetch = result.per_alert[str(good_alert.id)]
        assert good_prefetch.error is None
        assert good_prefetch.buckets is not None
        assert sum(b.count for b in good_prefetch.buckets) == 3

        # Bad alert: error captured per-alert, no buckets.
        bad_prefetch = result.per_alert[str(bad_alert.id)]
        assert bad_prefetch.buckets is None
        assert bad_prefetch.error is not None
        assert "simulated per-alert query failure" in str(bad_prefetch.error)
        assert bad_prefetch.query_duration_ms is not None and bad_prefetch.query_duration_ms >= 0


class TestEvaluateSingleAlert(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Silence the per-alert metric helpers at class level — they raise outside
        # Temporal context and the try/except in activities.py swallows the first raise,
        # skipping later helpers that individual tests want to assert on.
        for target in (
            "products.logs.backend.temporal.activities.record_check_duration",
            "products.logs.backend.temporal.activities.record_scheduler_lag",
            "products.logs.backend.temporal.activities.record_clickhouse_duration",
            "products.logs.backend.temporal.activities.record_cohort_save_duration",
            "products.logs.backend.temporal.activities.record_cohort_event_insert_duration",
            "products.logs.backend.temporal.activities.record_cohort_update_duration",
            "products.logs.backend.temporal.activities.record_cohort_size",
            "products.logs.backend.temporal.activities.increment_checks_total",
            "products.logs.backend.temporal.activities.increment_check_errors",
        ):
            p = patch(target)
            p.start()
            self.addCleanup(p.stop)

    def _make_alert(self, **kwargs) -> LogsAlertConfiguration:
        defaults = {
            "team": self.team,
            "name": "Test Alert",
            "threshold_count": 10,
            "threshold_operator": "above",
            "window_minutes": 5,
            "filters": {"serviceNames": ["test-service"]},
        }
        defaults.update(kwargs)
        return LogsAlertConfiguration.objects.create(**defaults)

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_threshold_breached_transitions_to_firing(self, mock_produce, mock_query_cls):
        _mock_buckets(mock_query_cls, [50])
        alert = self._make_alert()
        stats = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        _evaluate_and_save_one(alert, now, stats)

        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.FIRING
        assert stats["checked"] == 1
        assert stats["fired"] == 1
        mock_produce.assert_called_once()
        assert mock_produce.call_args.kwargs["event"].event == "$logs_alert_firing"

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_threshold_not_breached_stays_not_firing(self, mock_produce, mock_query_cls):
        _mock_buckets(mock_query_cls, [5])
        alert = self._make_alert()
        stats = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        _evaluate_and_save_one(alert, now, stats)

        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.NOT_FIRING
        assert stats["checked"] == 1
        assert stats["fired"] == 0
        mock_produce.assert_not_called()

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_steady_state_writes_no_alert_event(self, _mock_produce, mock_query_cls):
        _mock_buckets(mock_query_cls, [5])  # below threshold → stays NOT_FIRING
        alert = self._make_alert()

        _evaluate_and_save_one(alert, datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats())

        assert LogsAlertEvent.objects.filter(alert=alert).count() == 0

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_creates_event_row(self, mock_produce, mock_query_cls):
        _mock_buckets(mock_query_cls, [50])
        alert = self._make_alert()
        stats = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        _evaluate_and_save_one(alert, now, stats)

        check = LogsAlertEvent.objects.get(alert=alert)
        assert check.result_count == 50
        assert check.threshold_breached is True
        assert check.state_before == "not_firing"
        assert check.state_after == "firing"
        # Stateless eval times the bucketed CH call via perf_counter — exact value
        # depends on real clock (mocked CH returns instantly, so duration is tiny).
        assert check.query_duration_ms is not None and check.query_duration_ms >= 0
        assert check.error_message is None

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_advances_next_check_at(self, mock_produce, mock_query_cls):
        _mock_buckets(mock_query_cls, [5])
        alert = self._make_alert(next_check_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC))
        stats = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        _evaluate_and_save_one(alert, now, stats)

        alert.refresh_from_db()
        assert alert.next_check_at is not None and alert.next_check_at > now

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    @patch(
        "products.logs.backend.alert_error_classifier.classify_query_error",
        return_value=QueryErrorCategory.QUERY_PERFORMANCE_ERROR,
    )
    def test_clickhouse_failure_creates_error_event_row(self, _mock_classify, mock_produce, mock_query_cls):
        # Force the classifier to treat this as a performance error so the assertion
        # doesn't depend on whether the raw message hits one of the shared classifier's
        # recognized shapes.
        mock_query_cls.return_value.execute_rolling_checks.side_effect = Exception(
            "Code: 160. DB::Exception: Estimated query execution time is too long"
        )
        alert = self._make_alert()
        stats = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        _evaluate_and_save_one(alert, now, stats)

        check = LogsAlertEvent.objects.get(alert=alert)
        assert check.result_count is None
        assert check.threshold_breached is False
        assert check.error_message == "Query is too expensive. Try narrower filters or a shorter window."
        assert "DB::Exception" not in (check.error_message or "")
        assert stats["errored"] == 1

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_emit_event_uses_team_distinct_id(self, mock_produce, mock_query_cls):
        _mock_buckets(mock_query_cls, [50])
        alert = self._make_alert()
        stats = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        _evaluate_and_save_one(alert, now, stats)

        event = mock_produce.call_args.kwargs["event"]
        assert event.distinct_id == f"team_{self.team.id}"

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_last_notified_at_set_after_kafka_success(self, mock_produce, mock_query_cls):
        _mock_buckets(mock_query_cls, [50])
        alert = self._make_alert()
        stats = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        _evaluate_and_save_one(alert, now, stats)

        alert.refresh_from_db()
        assert alert.last_notified_at == now

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event", side_effect=Exception("Kafka down"))
    @patch("products.logs.backend.temporal.activities.capture_exception")
    def test_last_notified_at_not_set_on_kafka_failure(self, mock_capture, mock_produce, mock_query_cls):
        _mock_buckets(mock_query_cls, [50])
        alert = self._make_alert()
        stats = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        _evaluate_and_save_one(alert, now, stats)

        alert.refresh_from_db()
        assert alert.last_notified_at is None
        mock_capture.assert_called_once()

    @parameterized.expand(
        [
            ("above_breached", "above", 50, True),
            ("above_not_breached", "above", 5, False),
            ("below_breached", "below", 5, True),
            ("below_not_breached", "below", 50, False),
        ]
    )
    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_threshold_operators(self, _name, operator, count, should_fire, mock_produce, mock_query_cls):
        _mock_buckets(mock_query_cls, [count])
        alert = self._make_alert(threshold_operator=operator, threshold_count=10)
        stats = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        _evaluate_and_save_one(alert, now, stats)

        alert.refresh_from_db()
        if should_fire:
            assert alert.state == LogsAlertConfiguration.State.FIRING
            assert stats["fired"] == 1
        else:
            assert alert.state == LogsAlertConfiguration.State.NOT_FIRING
            assert stats["fired"] == 0

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_resolution_emits_resolved_event(self, mock_produce, mock_query_cls):
        alert = self._make_alert(state=LogsAlertConfiguration.State.FIRING)
        # First check breached to create an event row for get_recent_breaches
        _mock_buckets(mock_query_cls, [50])
        _evaluate_and_save_one(alert, datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC), _make_stats())
        alert.refresh_from_db()
        mock_produce.reset_mock()

        # Second check not breached — should resolve
        _mock_buckets(mock_query_cls, [0])
        stats = _make_stats()
        _evaluate_and_save_one(alert, datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), stats)

        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.NOT_FIRING
        assert stats["resolved"] == 1
        mock_produce.assert_called_once()
        assert mock_produce.call_args.kwargs["event"].event == "$logs_alert_resolved"

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_cooldown_suppresses_notification(self, mock_produce, mock_query_cls):
        _mock_buckets(mock_query_cls, [50])
        alert = self._make_alert(
            state=LogsAlertConfiguration.State.FIRING,
            cooldown_minutes=60,
            last_notified_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
        stats = _make_stats()
        # 1 minute after last notification, within 60-min cooldown
        _evaluate_and_save_one(alert, datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), stats)

        alert.refresh_from_db()
        # State transitions still happen, but no notification emitted
        assert alert.state == LogsAlertConfiguration.State.FIRING
        mock_produce.assert_not_called()

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_n_of_m_requires_multiple_breaches_to_fire(self, mock_produce, mock_query_cls):
        # Stateless eval: a single bucketed query returns the M-bucket history.
        # State machine derives the N-of-M decision from those buckets directly.
        # Buckets are oldest-first; the activity reverses internally.
        alert = self._make_alert(evaluation_periods=3, datapoints_to_alarm=2)

        # 1-of-3 breach (newest=breach, older two ok) → not enough
        _mock_buckets(mock_query_cls, [0, 0, 50])
        _evaluate_and_save_one(alert, datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC), _make_stats())
        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.NOT_FIRING

        # 1-of-3 still (oldest breach, newer two ok) → not enough
        _mock_buckets(mock_query_cls, [50, 0, 0])
        _evaluate_and_save_one(alert, datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats())
        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.NOT_FIRING

        # 2-of-3 (oldest ok, two newer breach) → fire
        _mock_buckets(mock_query_cls, [0, 50, 50])
        stats = _make_stats()
        _evaluate_and_save_one(alert, datetime(2025, 1, 1, 0, 2, 0, tzinfo=UTC), stats)
        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.FIRING
        assert stats["fired"] == 1
        mock_produce.assert_called_once()

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_event_properties_include_logs_url_params(self, mock_produce, mock_query_cls):
        alert = self._make_alert(
            threshold_count=5,
            filters={"severityLevels": ["error"], "serviceNames": ["api-server"]},
        )
        _mock_buckets(mock_query_cls, [10])

        _evaluate_and_save_one(alert, datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats())

        assert mock_produce.called
        props = mock_produce.call_args.kwargs["event"].properties
        assert "logs_url_params" in props
        assert "severityLevels" in props["logs_url_params"]
        assert "api-server" in props["logs_url_params"]
        assert props["service_names"] == ["api-server"]
        assert props["severity_levels"] == ["error"]
        assert props["triggered_at"] == "2025-01-01T00:01:00+00:00"

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_logs_url_params_includes_absolute_date_range(self, mock_produce, mock_query_cls):
        alert = self._make_alert(
            threshold_count=5,
            window_minutes=10,
            filters={"severityLevels": ["error"]},
        )
        _mock_buckets(mock_query_cls, [10])

        _evaluate_and_save_one(alert, datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats())

        props = mock_produce.call_args.kwargs["event"].properties
        assert "dateRange" in props["logs_url_params"]
        # Window is 10m, check time is 00:01 — so date_from should be 23:51 (previous day)
        assert "2024-12-31T23%3A51%3A00" in props["logs_url_params"] or "23:51:00" in props["logs_url_params"]
        assert "2025-01-01T00%3A01%3A00" in props["logs_url_params"] or "00:01:00" in props["logs_url_params"]

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_resolution_within_cooldown_suppresses_resolved_event(self, mock_produce, mock_query_cls):
        _mock_buckets(mock_query_cls, [0])
        alert = self._make_alert(
            state=LogsAlertConfiguration.State.FIRING,
            cooldown_minutes=60,
            last_notified_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
        # Create an event row so get_recent_breaches has data
        LogsAlertEvent.objects.create(
            alert=alert,
            result_count=50,
            threshold_breached=True,
            state_before="not_firing",
            state_after="firing",
        )

        stats = _make_stats()
        _evaluate_and_save_one(alert, datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), stats)

        alert.refresh_from_db()
        # State transitions to NOT_FIRING regardless of cooldown
        assert alert.state == LogsAlertConfiguration.State.NOT_FIRING
        # But notification is suppressed by cooldown
        mock_produce.assert_not_called()

    @parameterized.expand(
        [
            (
                "hits_threshold",
                4,
                LogsAlertConfiguration.State.NOT_FIRING,
                LogsAlertConfiguration.State.BROKEN,
                5,
                1,
            ),
            (
                "below_threshold",
                3,
                LogsAlertConfiguration.State.NOT_FIRING,
                LogsAlertConfiguration.State.ERRORED,
                4,
                0,
            ),
            (
                "already_broken",
                5,
                LogsAlertConfiguration.State.BROKEN,
                LogsAlertConfiguration.State.BROKEN,
                5,
                0,
            ),
        ]
    )
    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_break_on_consecutive_failures(
        self,
        _name,
        initial_failures,
        initial_state,
        expected_state,
        expected_failures,
        expected_events,
        mock_produce,
        mock_query_cls,
    ):
        alert = self._make_alert(
            threshold_count=5,
            consecutive_failures=initial_failures,
            state=initial_state,
        )
        mock_query_cls.return_value.execute_rolling_checks.side_effect = Exception(
            "Code: 160. DB::Exception: Estimated query execution time is too long"
        )

        with patch(
            "products.logs.backend.alert_error_classifier.classify_query_error",
            return_value=QueryErrorCategory.QUERY_PERFORMANCE_ERROR,
        ):
            _evaluate_and_save_one(alert, datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats())

        alert.refresh_from_db()
        assert alert.state == expected_state
        assert alert.consecutive_failures == expected_failures
        auto_disabled_calls = [
            c
            for c in mock_produce.call_args_list
            if c.kwargs.get("event") and c.kwargs["event"].event == "$logs_alert_auto_disabled"
        ]
        assert len(auto_disabled_calls) == expected_events
        if expected_events:
            props = auto_disabled_calls[0].kwargs["event"].properties
            assert props["consecutive_failures"] == expected_failures
            # Auto-disabled event surfaces the classified user message, never the raw CH exception.
            assert props["last_error_message"] == "Query is too expensive. Try narrower filters or a shorter window."
            assert "DB::Exception" not in props["last_error_message"]

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.increment_state_transition")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_state_transition_counter_fires_on_state_change(self, _mock_produce, mock_query_cls, mock_transition):
        _mock_buckets(mock_query_cls, [50])
        alert = self._make_alert()

        _evaluate_and_save_one(alert, datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats())

        mock_transition.assert_called_once_with(AlertState.NOT_FIRING, AlertState.FIRING)

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.increment_state_transition")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_state_transition_counter_silent_when_state_unchanged(self, _mock_produce, mock_query_cls, mock_transition):
        _mock_buckets(mock_query_cls, [5])
        self._make_alert()

        _evaluate_and_save_one(
            LogsAlertConfiguration.objects.get(), datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats()
        )

        mock_transition.assert_not_called()

    @parameterized.expand(
        [
            ("fire", 50, LogsAlertConfiguration.State.NOT_FIRING),
            ("resolve", 0, LogsAlertConfiguration.State.FIRING),
        ]
    )
    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.increment_notification_failures")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event", side_effect=Exception("Kafka down"))
    @patch("products.logs.backend.temporal.activities.capture_exception")
    def test_notification_failures_counter(
        self,
        expected_action_name,
        result_count,
        initial_state,
        _mock_capture,
        _mock_produce,
        mock_query_cls,
        mock_notif_failures,
    ):
        _mock_buckets(mock_query_cls, [result_count])
        self._make_alert(state=initial_state)

        _evaluate_and_save_one(
            LogsAlertConfiguration.objects.get(), datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats()
        )

        mock_notif_failures.assert_called_once_with(NotificationAction(expected_action_name))

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.increment_notification_failures")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_notification_failures_silent_on_success(self, _mock_produce, mock_query_cls, mock_notif_failures):
        _mock_buckets(mock_query_cls, [50])
        self._make_alert()

        _evaluate_and_save_one(
            LogsAlertConfiguration.objects.get(), datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats()
        )

        mock_notif_failures.assert_not_called()

    @parameterized.expand(
        [
            ("server_busy", QueryErrorCategory.RATE_LIMITED),
            ("query_performance", QueryErrorCategory.QUERY_PERFORMANCE_ERROR),
            ("cancelled", QueryErrorCategory.CANCELLED),
            ("unknown", QueryErrorCategory.ERROR),
        ]
    )
    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.increment_check_errors")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_check_errors_counter_labelled_by_classifier(
        self,
        expected_category,
        classifier_category,
        _mock_produce,
        mock_query_cls,
        mock_check_errors,
    ):
        mock_query_cls.return_value.execute_rolling_checks.side_effect = Exception("boom")
        self._make_alert()

        with patch(
            "products.logs.backend.alert_error_classifier.classify_query_error",
            return_value=classifier_category,
        ):
            _evaluate_and_save_one(
                LogsAlertConfiguration.objects.get(), datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats()
            )

        mock_check_errors.assert_called_once_with(expected_category)

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.increment_check_errors")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_check_errors_counter_silent_on_success(self, _mock_produce, mock_query_cls, mock_check_errors):
        _mock_buckets(mock_query_cls, [5])
        self._make_alert()

        _evaluate_and_save_one(
            LogsAlertConfiguration.objects.get(), datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats()
        )

        mock_check_errors.assert_not_called()

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_query_uses_checkpoint_as_date_to_when_in_past(self, _mock_produce, mock_query_cls):
        _mock_buckets(mock_query_cls, [5])
        alert = self._make_alert(window_minutes=5)
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)
        checkpoint = datetime(2025, 1, 1, 0, 0, 30, tzinfo=UTC)  # 30s behind now

        _evaluate_and_save_one(alert, now, _make_stats(), checkpoint=checkpoint)

        kwargs = mock_query_cls.call_args.kwargs
        assert kwargs["date_to"] == checkpoint
        assert kwargs["date_from"] == checkpoint - dt.timedelta(minutes=5)

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_query_uses_now_when_checkpoint_is_in_future(self, _mock_produce, mock_query_cls):
        # Defensive case: if clocks are skewed so checkpoint > now, don't query the future.
        _mock_buckets(mock_query_cls, [5])
        alert = self._make_alert(window_minutes=5)
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)
        checkpoint = datetime(2025, 1, 1, 0, 2, 0, tzinfo=UTC)  # 60s ahead of now

        _evaluate_and_save_one(alert, now, _make_stats(), checkpoint=checkpoint)

        kwargs = mock_query_cls.call_args.kwargs
        assert kwargs["date_to"] == now
        assert kwargs["date_from"] == now - dt.timedelta(minutes=5)

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_query_uses_now_when_checkpoint_is_none(self, _mock_produce, mock_query_cls):
        _mock_buckets(mock_query_cls, [5])
        alert = self._make_alert(window_minutes=5)
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        _evaluate_and_save_one(alert, now, _make_stats(), checkpoint=None)

        kwargs = mock_query_cls.call_args.kwargs
        assert kwargs["date_to"] == now
        assert kwargs["date_from"] == now - dt.timedelta(minutes=5)

    @freeze_time("2025-01-01T01:00:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_query_ignores_stale_checkpoint_quiet_partition_case(self, _mock_produce, mock_query_cls):
        # Quiet partitions pin min(max_observed_timestamp) backwards. If that's older than
        # CHECKPOINT_MAX_STALENESS we must ignore the checkpoint — otherwise a spike of
        # errors on an active partition would never appear in the window.
        _mock_buckets(mock_query_cls, [5])
        alert = self._make_alert(window_minutes=5)
        now = datetime(2025, 1, 1, 1, 0, 0, tzinfo=UTC)
        stale_checkpoint = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)  # 1 hour behind now

        _evaluate_and_save_one(alert, now, _make_stats(), checkpoint=stale_checkpoint)

        kwargs = mock_query_cls.call_args.kwargs
        assert kwargs["date_to"] == now
        assert kwargs["date_from"] == now - dt.timedelta(minutes=5)

    @parameterized.expand(
        [
            ("M=3_window=5", 5, 3, 15),
            ("M=10_window=5", 5, 10, 50),
            ("M=3_window=10", 10, 3, 20),
            ("M=10_window=60_worst_case", 60, 10, 105),
        ]
    )
    @freeze_time("2025-01-01T05:00:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_date_from_covers_full_rolling_check_lookback(
        self, _name, window_minutes, evaluation_periods, expected_range_minutes, _mock_produce, mock_query_cls
    ):
        _mock_buckets(mock_query_cls, [0])
        alert = self._make_alert(
            window_minutes=window_minutes,
            evaluation_periods=evaluation_periods,
            datapoints_to_alarm=1,
        )
        now = datetime(2025, 1, 1, 5, 0, 0, tzinfo=UTC)

        _evaluate_and_save_one(alert, now, _make_stats(), checkpoint=None)

        kwargs = mock_query_cls.call_args.kwargs
        assert kwargs["date_to"] == now
        assert kwargs["date_from"] == now - dt.timedelta(minutes=expected_range_minutes)

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_errored_notification_emitted_on_first_error(self, mock_produce, mock_query_cls):
        mock_query_cls.return_value.execute_rolling_checks.side_effect = Exception(
            "Code: 160. DB::Exception: Estimated query execution time is too long"
        )
        alert = self._make_alert()

        with patch(
            "products.logs.backend.alert_error_classifier.classify_query_error",
            return_value=QueryErrorCategory.QUERY_PERFORMANCE_ERROR,
        ):
            _evaluate_and_save_one(alert, datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats())

        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.ERRORED
        errored_calls = [
            c
            for c in mock_produce.call_args_list
            if c.kwargs.get("event") and c.kwargs["event"].event == "$logs_alert_errored"
        ]
        assert len(errored_calls) == 1
        assert errored_calls[0].kwargs["event"].properties["consecutive_failures"] == 1

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.capture_exception")
    def test_errored_notification_retried_after_kafka_failure(self, _mock_capture, mock_query_cls):
        mock_query_cls.return_value.execute_rolling_checks.side_effect = RuntimeError("CH down")
        alert = self._make_alert()
        now1 = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)
        now2 = datetime(2025, 1, 1, 0, 6, 0, tzinfo=UTC)

        with patch("products.logs.backend.temporal.activities.produce_internal_event") as mock_produce:
            mock_produce.side_effect = Exception("Kafka down")
            _evaluate_and_save_one(alert, now1, _make_stats())

            mock_produce.side_effect = None
            mock_produce.reset_mock()
            _evaluate_and_save_one(alert, now2, _make_stats())

        errored_calls = [
            c
            for c in mock_produce.call_args_list
            if c.kwargs.get("event") and c.kwargs["event"].event == "$logs_alert_errored"
        ]
        assert len(errored_calls) == 1

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.capture_exception")
    def test_broken_notification_retried_after_kafka_failure(self, _mock_capture, mock_query_cls):
        mock_query_cls.return_value.execute_rolling_checks.side_effect = Exception(
            "Code: 160. DB::Exception: Estimated query execution time is too long"
        )
        # 4 prior failures — one more pushes consecutive_failures to MAX (5) → BROKEN.
        alert = self._make_alert(state=LogsAlertConfiguration.State.ERRORED, consecutive_failures=4)
        now1 = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)
        now2 = datetime(2025, 1, 1, 0, 6, 0, tzinfo=UTC)

        with (
            patch("products.logs.backend.temporal.activities.produce_internal_event") as mock_produce,
            patch(
                "products.logs.backend.alert_error_classifier.classify_query_error",
                return_value=QueryErrorCategory.QUERY_PERFORMANCE_ERROR,
            ),
        ):
            mock_produce.side_effect = Exception("Kafka down")
            _evaluate_and_save_one(alert, now1, _make_stats())

            mock_produce.side_effect = None
            mock_produce.reset_mock()
            _evaluate_and_save_one(alert, now2, _make_stats())

        auto_disabled_calls = [
            c
            for c in mock_produce.call_args_list
            if c.kwargs.get("event") and c.kwargs["event"].event == "$logs_alert_auto_disabled"
        ]
        assert len(auto_disabled_calls) == 1

    @parameterized.expand(
        [
            ("error", LogsAlertConfiguration.State.NOT_FIRING, 0, NotificationAction.ERROR),
            ("broken", LogsAlertConfiguration.State.ERRORED, 4, NotificationAction.BROKEN),
        ]
    )
    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.increment_notification_failures")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event", side_effect=Exception("Kafka down"))
    @patch("products.logs.backend.temporal.activities.capture_exception")
    def test_notification_failures_counter_for_error_and_broken(
        self,
        _name,
        initial_state,
        initial_failures,
        expected_action,
        _mock_capture,
        _mock_produce,
        mock_query_cls,
        mock_notif_failures,
    ):
        mock_query_cls.return_value.execute_rolling_checks.side_effect = Exception(
            "Code: 160. DB::Exception: Estimated query execution time is too long"
        )
        self._make_alert(state=initial_state, consecutive_failures=initial_failures)

        with patch(
            "products.logs.backend.alert_error_classifier.classify_query_error",
            return_value=QueryErrorCategory.QUERY_PERFORMANCE_ERROR,
        ):
            _evaluate_and_save_one(
                LogsAlertConfiguration.objects.get(), datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats()
            )

        mock_notif_failures.assert_called_once_with(expected_action)


class TestDeriveBreachesProperties(unittest.TestCase):
    """Property-based coverage of `_derive_breaches`.

    The activity's bucket → state-machine seam: takes ASC-ordered CH buckets,
    applies the threshold predicate, returns a newest-first breach tuple. Pure
    function so we can exercise the full input space without DB or mocks.
    """

    @given(
        bucket_counts=st.lists(st.integers(min_value=0, max_value=10_000), min_size=0, max_size=10),
        threshold=st.integers(min_value=1, max_value=5_000),
        operator=st.sampled_from(["above", "below"]),
    )
    @settings(max_examples=500, deadline=None)
    def test_length_preserved_when_no_padding_needed(
        self, bucket_counts: list[int], threshold: int, operator: str
    ) -> None:
        # When evaluation_periods == len(buckets), no pad fires; result length
        # matches input. Padding behavior covered by a separate property below.
        buckets = [BucketedCount(timestamp=datetime(2025, 1, 1, tzinfo=UTC), count=c) for c in bucket_counts]
        result = _derive_breaches(buckets, threshold, operator, len(buckets))
        assert len(result) == len(buckets)

    @given(
        bucket_counts=st.lists(st.integers(min_value=0, max_value=10_000), min_size=1, max_size=10),
        threshold=st.integers(min_value=1, max_value=5_000),
        operator=st.sampled_from(["above", "below"]),
    )
    @settings(max_examples=500, deadline=None)
    def test_newest_first_ordering(self, bucket_counts: list[int], threshold: int, operator: str) -> None:
        # The first element of the returned tuple corresponds to the LAST bucket
        # in the ASC input — i.e., the newest. State machine reads window
        # newest-first, so getting this wrong silently flips N-of-M decisions.
        buckets = [BucketedCount(timestamp=datetime(2025, 1, 1, tzinfo=UTC), count=c) for c in bucket_counts]
        result = _derive_breaches(buckets, threshold, operator, len(buckets))
        newest_breach = buckets[-1].count > threshold if operator == "above" else buckets[-1].count < threshold
        assert result[0] == newest_breach

    @given(
        bucket_counts=st.lists(st.integers(min_value=0, max_value=10_000), min_size=1, max_size=10),
        threshold=st.integers(min_value=1, max_value=5_000),
        operator=st.sampled_from(["above", "below"]),
    )
    @settings(max_examples=500, deadline=None)
    def test_breach_count_matches_threshold_predicate_when_no_padding(
        self, bucket_counts: list[int], threshold: int, operator: str
    ) -> None:
        # When the bucket list is already M long, no padding fires and the
        # breach count exactly matches the count of inputs satisfying the
        # threshold predicate. Catches drop / duplicate bugs.
        buckets = [BucketedCount(timestamp=datetime(2025, 1, 1, tzinfo=UTC), count=c) for c in bucket_counts]
        result = _derive_breaches(buckets, threshold, operator, len(buckets))
        if operator == "above":
            expected_count = sum(1 for c in bucket_counts if c > threshold)
        else:
            expected_count = sum(1 for c in bucket_counts if c < threshold)
        assert sum(result) == expected_count

    @given(
        bucket_counts=st.lists(st.integers(min_value=1, max_value=10_000), min_size=1, max_size=10),
        threshold=st.integers(min_value=1, max_value=10_000),
    )
    @settings(max_examples=300, deadline=None)
    def test_above_and_below_are_complementary_at_strict_inequality(
        self, bucket_counts: list[int], threshold: int
    ) -> None:
        # `above` = count > threshold; `below` = count < threshold. For any count
        # ≠ threshold, exactly one of the two is True. Sum of breach counts across
        # the two operators equals the number of buckets that aren't EQ to threshold.
        buckets = [BucketedCount(timestamp=datetime(2025, 1, 1, tzinfo=UTC), count=c) for c in bucket_counts]
        above = _derive_breaches(buckets, threshold, "above", len(buckets))
        below = _derive_breaches(buckets, threshold, "below", len(buckets))
        not_equal = sum(1 for c in bucket_counts if c != threshold)
        assert sum(above) + sum(below) == not_equal

    @given(
        bucket_counts=st.lists(st.integers(min_value=0, max_value=10_000), min_size=0, max_size=5),
        threshold=st.integers(min_value=1, max_value=5_000),
        m_extra=st.integers(min_value=1, max_value=8),
    )
    @settings(max_examples=300, deadline=None)
    def test_padding_fills_to_evaluation_periods_with_correct_implicit_breach(
        self, bucket_counts: list[int], threshold: int, m_extra: int
    ) -> None:
        # When `evaluation_periods > len(buckets)`, the result is padded to length
        # M with the implicit count=0 outcome:
        #   - above: pad = False (0 is not above threshold)
        #   - below: pad = True (0 is below threshold, given threshold >= 1)
        # This is the load-bearing fix for `below` alerts on silent services —
        # without it, an empty bucket list yields no breaches and silence detection
        # would never fire.
        m = len(bucket_counts) + m_extra
        buckets = [BucketedCount(timestamp=datetime(2025, 1, 1, tzinfo=UTC), count=c) for c in bucket_counts]

        above = _derive_breaches(buckets, threshold, "above", m)
        below = _derive_breaches(buckets, threshold, "below", m)

        assert len(above) == m
        assert len(below) == m
        # The trailing `m_extra` entries are pure padding.
        assert above[len(buckets) :] == (False,) * m_extra
        assert below[len(buckets) :] == (True,) * m_extra


class TestEvaluateSingleAlertEndToEnd(ClickhouseTestMixin, APIBaseTest):
    """End-to-end coverage of `_evaluate_single_alert` against real ClickHouse.

    Sibling tests above mock `execute_rolling_checks` and verify the activity's logic
    in isolation. This class drives the full hot path — periods CH query →
    state machine → PG state update — against seeded log data, catching seam
    bugs (BucketedCount tzinfo, threshold sign) that mocked-bucket tests can't
    see.
    """

    @freeze_time("2025-12-16T10:33:00Z")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_breach_against_real_clickhouse_fires_alert(self, _mock_produce):
        # Five logs at 10:30 with a unique service. next_check_at=10:33,
        # window=5, M=1 → activity's query window is [10:28, 10:33), capturing
        # all five.
        rows = [
            {
                "uuid": f"e2e-{i}",
                "team_id": self.team.id,
                "timestamp": "2025-12-16 10:30:00",
                "body": "",
                "severity_text": "info",
                "severity_number": 9,
                "service_name": "e2e_eval_test",
                "resource_attributes": {},
                "attributes_map_str": {},
            }
            for i in range(5)
        ]
        sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in rows))

        alert = self._make_alert(
            filters={"serviceNames": ["e2e_eval_test"]},
            next_check_at=datetime(2025, 12, 16, 10, 33, 0, tzinfo=UTC),
        )
        stats = _make_stats()

        _evaluate_and_save_one(alert, datetime(2025, 12, 16, 10, 33, 0, tzinfo=UTC), stats)

        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.FIRING
        assert stats["checked"] == 1
        assert stats["fired"] == 1

    def _seed_logs(self, service_name: str, timestamps: list[str]) -> None:
        rows = [
            {
                "uuid": f"{service_name}-{i}",
                "team_id": self.team.id,
                "timestamp": ts,
                "body": "",
                "severity_text": "info",
                "severity_number": 9,
                "service_name": service_name,
                "resource_attributes": {},
                "attributes_map_str": {},
            }
            for i, ts in enumerate(timestamps)
        ]
        sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in rows))

    def _make_alert(self, **kwargs) -> LogsAlertConfiguration:
        defaults = {
            "team": self.team,
            "name": "E2E Test Alert",
            "threshold_count": 2,
            "threshold_operator": "above",
            "window_minutes": 5,
            "evaluation_periods": 1,
        }
        defaults.update(kwargs)
        return LogsAlertConfiguration.objects.create(**defaults)

    @freeze_time("2025-12-16T10:35:00Z")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_n_of_m_progression_across_consecutive_evals(self, _mock_produce):
        # Real-CH version of the N-of-M progression test. M=3 N=2 over 5-min buckets.
        # Symmetric N-of-M: stays firing while breach_count >= N, resolves only
        # once it drops below N — so a single OK bucket after firing is not
        # enough to resolve.
        # Bucket counts (threshold=100):
        #   :00 = 50  (no breach)
        #   :05 = 50  (no breach)
        #   :10 = 200 (breach)
        #   :15 = 200 (breach)
        #   :20 = 50  (no breach)
        #   :25 = 50  (no breach)
        # Cycle 1 (NCA 10:15): rolling [10:00,10:05,10:10] → (T, F, F) → 1-of-3 → not_firing
        # Cycle 2 (NCA 10:20): rolling [10:05,10:10,10:15] → (T, T, F) → 2-of-3 → fire
        # Cycle 3 (NCA 10:25): rolling [10:10,10:15,10:20] → (F, T, T) → 2-of-3 → STILL firing
        # Cycle 4 (NCA 10:30): rolling [10:15,10:20,10:25] → (F, F, T) → 1-of-3 → resolve
        bucket_volumes = {
            "2025-12-16 10:00:30.000000": 50,
            "2025-12-16 10:05:30.000000": 50,
            "2025-12-16 10:10:30.000000": 200,
            "2025-12-16 10:15:30.000000": 200,
            "2025-12-16 10:20:30.000000": 50,
            "2025-12-16 10:25:30.000000": 50,
        }
        self._seed_logs(
            "n_of_m_progression",
            [ts for ts, count in bucket_volumes.items() for _ in range(count)],
        )

        alert = self._make_alert(
            filters={"serviceNames": ["n_of_m_progression"]},
            threshold_count=100,
            evaluation_periods=3,
            datapoints_to_alarm=2,
            next_check_at=datetime(2025, 12, 16, 10, 15, 0, tzinfo=UTC),
        )

        _evaluate_and_save_one(alert, datetime(2025, 12, 16, 10, 15, 0, tzinfo=UTC), _make_stats())
        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.NOT_FIRING

        alert.next_check_at = datetime(2025, 12, 16, 10, 20, 0, tzinfo=UTC)
        alert.save(update_fields=["next_check_at"])
        _evaluate_and_save_one(alert, datetime(2025, 12, 16, 10, 20, 0, tzinfo=UTC), _make_stats())
        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.FIRING

        alert.next_check_at = datetime(2025, 12, 16, 10, 25, 0, tzinfo=UTC)
        alert.save(update_fields=["next_check_at"])
        _evaluate_and_save_one(alert, datetime(2025, 12, 16, 10, 25, 0, tzinfo=UTC), _make_stats())
        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.FIRING

        alert.next_check_at = datetime(2025, 12, 16, 10, 30, 0, tzinfo=UTC)
        alert.save(update_fields=["next_check_at"])
        _evaluate_and_save_one(alert, datetime(2025, 12, 16, 10, 30, 0, tzinfo=UTC), _make_stats())
        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.NOT_FIRING

    @freeze_time("2025-12-16T10:25:00Z")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_cooldown_suppresses_resolve_notification_within_window(self, mock_produce):
        # Alert fires at next_check_at #1, resolve attempted at next_check_at #2
        # within cooldown_minutes → state transitions to NOT_FIRING but
        # NotificationAction.RESOLVE is suppressed (no produce call). Tests
        # cooldown timing across two real CH-backed evals.
        self._seed_logs(
            "cooldown_test",
            ["2025-12-16 10:18:00.000000"] * 10,  # logs only in cycle 1's window
        )

        alert = self._make_alert(
            filters={"serviceNames": ["cooldown_test"]},
            cooldown_minutes=30,  # cooldown longer than the 5-min interval between cycles
            next_check_at=datetime(2025, 12, 16, 10, 20, 0, tzinfo=UTC),
        )

        # Cycle 1: fires (10 logs at :18 in [10:15, 10:20)) → fire notification, sets last_notified_at
        _evaluate_and_save_one(alert, datetime(2025, 12, 16, 10, 20, 0, tzinfo=UTC), _make_stats())
        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.FIRING
        assert mock_produce.call_count == 1

        # Cycle 2: no logs in the new window [10:20, 10:25) → resolve attempted,
        # but cooldown=30min suppresses the dispatch (only 5 min since fire).
        alert.next_check_at = datetime(2025, 12, 16, 10, 25, 0, tzinfo=UTC)
        alert.save(update_fields=["next_check_at"])
        _evaluate_and_save_one(alert, datetime(2025, 12, 16, 10, 25, 0, tzinfo=UTC), _make_stats())
        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.NOT_FIRING  # state still transitions
        assert mock_produce.call_count == 1  # but no second notification dispatched

    @freeze_time("2025-12-16T10:33:00Z")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_below_operator_fires_on_truly_silent_service(self, _mock_produce):
        # `execute_rolling_checks` always returns exactly `period_count` entries (zero
        # counts for silent services, since each period is a fixed-width
        # `countIf` column rather than a `GROUP BY` over data), so
        # `0 < threshold` evaluates True → breach → fires. Regression guard
        # for the [TEST] Web Service Silent prod alert.
        alert = self._make_alert(
            filters={"serviceNames": ["truly_silent_service_no_logs"]},
            threshold_count=1,
            threshold_operator="below",
            next_check_at=datetime(2025, 12, 16, 10, 33, 0, tzinfo=UTC),
        )

        _evaluate_and_save_one(alert, datetime(2025, 12, 16, 10, 33, 0, tzinfo=UTC), _make_stats())

        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.FIRING, (
            "below operator on a silent service must fire — count=0 satisfies count<threshold"
        )

    @freeze_time("2025-12-16T10:33:00Z")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_first_run_with_null_nca_anchors_on_now(self, _mock_produce):
        # Alert created with next_check_at=None (first eval after enable). The
        # activity falls back to `now` as the anchor; the query window is
        # [now - window*M, now) and breach detection still works.
        self._seed_logs(
            "null_nca_test",
            ["2025-12-16 10:30:00.000000"] * 5,  # logs at :30, captured by [10:28, 10:33)
        )

        alert = self._make_alert(
            filters={"serviceNames": ["null_nca_test"]},
            next_check_at=None,  # first run
        )

        _evaluate_and_save_one(alert, datetime(2025, 12, 16, 10, 33, 0, tzinfo=UTC), _make_stats())

        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.FIRING
        assert alert.next_check_at is not None  # activity advanced it


class TestCohortManifest(unittest.TestCase):
    def test_manifest_round_trips_through_json(self):
        # CohortManifest must be JSON-serialisable for Temporal payload conversion.
        # Datetimes get serialised as ISO strings; UUIDs stay as plain strings.
        # Use list[str] (not tuple) for alert_ids — JSON arrays deserialise to
        # lists and Temporal's default converter doesn't round-trip tuples.
        import json

        from products.logs.backend.temporal.activities import CohortManifest

        manifest = CohortManifest(
            team_id=42,
            projection_eligible=True,
            date_to_iso="2026-05-05T10:00:00+00:00",
            alert_ids=["019decab-1234-7000-8000-000000000001", "019decab-1234-7000-8000-000000000002"],
        )

        as_dict = dataclasses.asdict(manifest)
        round_tripped = CohortManifest(**json.loads(json.dumps(as_dict)))

        assert round_tripped.team_id == 42
        assert round_tripped.alert_ids == manifest.alert_ids
        assert round_tripped.date_to_iso == manifest.date_to_iso

    def test_manifests_grouped_by_cohort_key(self):
        # Three alerts: two share a key (same team, window, cadence, projection,
        # date_to), one differs by window_minutes. Expect 2 manifests.
        from products.logs.backend.temporal.activities import _cohort_manifests_from_alerts

        rows = [
            {
                "id": "019dec00-0000-0000-0000-000000000001",
                "team_id": 1,
                "window_minutes": 5,
                "evaluation_periods": 1,
                "check_interval_minutes": 5,
                "filters": {"serviceNames": ["a"]},
                "next_check_at": None,
            },
            {
                "id": "019dec00-0000-0000-0000-000000000002",
                "team_id": 1,
                "window_minutes": 5,
                "evaluation_periods": 1,
                "check_interval_minutes": 5,
                "filters": {"serviceNames": ["b"]},
                "next_check_at": None,
            },
            {
                "id": "019dec00-0000-0000-0000-000000000003",
                "team_id": 1,
                "window_minutes": 15,  # different window → different cohort
                "evaluation_periods": 1,
                "check_interval_minutes": 5,
                "filters": {"serviceNames": ["a"]},
                "next_check_at": None,
            },
        ]
        now = datetime(2026, 5, 5, 10, 0, tzinfo=UTC)

        with (
            patch("products.logs.backend.temporal.activities.is_projection_eligible", return_value=True),
            patch("products.logs.backend.temporal.activities.resolve_alert_date_to", return_value=now),
        ):
            manifests = _cohort_manifests_from_alerts(rows, now=now, checkpoint=None)

        assert len(manifests) == 2
        sizes = sorted(len(m.alert_ids) for m in manifests)
        assert sizes == [1, 2]

    def test_manifests_split_oversized_groups(self):
        # 5 alerts on the same grid at MAX_ALERT_COHORT_SIZE=2 → 3 manifests
        # (sizes [1, 2, 2]).
        from products.logs.backend.temporal.activities import _cohort_manifests_from_alerts

        rows: list[dict[str, Any]] = [
            {
                "id": f"019dec00-0000-0000-0000-{i:012d}",
                "team_id": 1,
                "window_minutes": 5,
                "evaluation_periods": 1,
                "check_interval_minutes": 5,
                "filters": {},
                "next_check_at": None,
            }
            for i in range(5)
        ]
        now = datetime(2026, 5, 5, 10, 0, tzinfo=UTC)

        with (
            patch("products.logs.backend.temporal.activities.is_projection_eligible", return_value=True),
            patch("products.logs.backend.temporal.activities.resolve_alert_date_to", return_value=now),
            patch("products.logs.backend.temporal.activities.MAX_ALERT_COHORT_SIZE", 2),
        ):
            manifests = _cohort_manifests_from_alerts(rows, now=now, checkpoint=None)

        assert sorted(len(m.alert_ids) for m in manifests) == [1, 2, 2]


class TestDiscoverCohortsActivity(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    @freeze_time("2026-05-05T10:00:00Z")
    def test_returns_manifests_for_due_alerts_only(self):
        from products.logs.backend.temporal.activities import DiscoverCohortsInput, discover_cohorts_activity

        # Two due (next_check_at=None), one not due (next_check_at in future).
        for i in range(2):
            LogsAlertConfiguration.objects.create(
                team=self.team,
                name=f"due_{i}",
                threshold_count=1,
                threshold_operator="above",
                window_minutes=5,
                evaluation_periods=1,
                filters={"serviceNames": [f"svc_{i}"]},
                enabled=True,
                next_check_at=None,
            )
        LogsAlertConfiguration.objects.create(
            team=self.team,
            name="future",
            threshold_count=1,
            threshold_operator="above",
            window_minutes=5,
            evaluation_periods=1,
            filters={"serviceNames": ["svc_future"]},
            enabled=True,
            next_check_at=datetime(2026, 5, 5, 11, 0, tzinfo=UTC),  # future
        )

        result = asyncio.run(discover_cohorts_activity(DiscoverCohortsInput()))

        # Two due alerts share team + window + cadence → one cohort with 2 alert_ids.
        # (One alert is in the future; not due, not discovered.)
        assert len(result.manifests) == 1
        assert len(result.manifests[0].alert_ids) == 2


class TestCohortFromManifest(unittest.TestCase):
    def test_reconstructs_cohort_from_manifest_and_alerts(self):
        from products.logs.backend.temporal.activities import CohortManifest, _cohort_from_manifest

        alert_a = MagicMock(id="alert-a", team_id=7)
        alert_b = MagicMock(id="alert-b", team_id=7)
        alerts_by_id = cast(dict[str, LogsAlertConfiguration], {"alert-a": alert_a, "alert-b": alert_b})

        manifest = CohortManifest(
            team_id=7,
            projection_eligible=True,
            date_to_iso="2026-05-05T10:00:00+00:00",
            alert_ids=["alert-a", "alert-b"],
        )

        cohort = _cohort_from_manifest(manifest, alerts_by_id)

        assert len(cohort.alerts) == 2
        assert cohort.alerts[0] is alert_a
        assert cohort.alerts[1] is alert_b
        assert cohort.date_to == datetime(2026, 5, 5, 10, 0, tzinfo=UTC)
        assert cohort.projection_eligible is True

    def test_raises_if_manifest_alert_id_not_loaded(self):
        # Defensive: if the evaluate activity's bulk-load missed an alert
        # (e.g. it was deleted between discovery and evaluate), the manifest
        # references an ID that's not in `alerts_by_id`. This is a programmer
        # error / data race — fail loudly rather than silently dropping alerts.
        from products.logs.backend.temporal.activities import CohortManifest, _cohort_from_manifest

        manifest = CohortManifest(
            team_id=7,
            projection_eligible=True,
            date_to_iso="2026-05-05T10:00:00+00:00",
            alert_ids=["missing-id"],
        )

        with self.assertRaises(KeyError):
            _cohort_from_manifest(manifest, alerts_by_id={})


class TestEvaluateCohortBatchActivity(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    @freeze_time("2026-05-05T10:05:00Z")
    @patch("products.logs.backend.temporal.activities._run_cohort_query")
    def test_loads_alerts_by_id_and_processes_each_cohort(self, mock_run_cohort_query):
        from products.logs.backend.temporal.activities import (
            CohortManifest,
            EvaluateCohortBatchInput,
            _CohortQueryResult,
            _PrefetchedQuery,
            evaluate_cohort_batch_activity,
        )

        # Two alerts on the same grid → one manifest with 2 IDs.
        alerts = [
            LogsAlertConfiguration.objects.create(
                team=self.team,
                name=f"a{i}",
                threshold_count=1,
                threshold_operator="above",
                window_minutes=5,
                evaluation_periods=1,
                filters={"serviceNames": [f"s{i}"]},
                enabled=True,
                next_check_at=None,
            )
            for i in range(2)
        ]

        # Mock the CH query so this is a pure orchestration test (per-cohort
        # evaluation is covered by other test classes).
        def _mock_query(cohort):
            return _CohortQueryResult(per_alert={str(a.id): _PrefetchedQuery(buckets=[]) for a in cohort.alerts})

        mock_run_cohort_query.side_effect = _mock_query

        manifest = CohortManifest(
            team_id=self.team.id,
            projection_eligible=True,
            date_to_iso="2026-05-05T10:05:00+00:00",
            alert_ids=[str(a.id) for a in alerts],
        )

        result = asyncio.run(evaluate_cohort_batch_activity(EvaluateCohortBatchInput(manifests=[manifest])))

        assert result.alerts_checked == 2
        # _run_cohort_query was invoked exactly once (one cohort in this batch).
        assert mock_run_cohort_query.call_count == 1

    @freeze_time("2026-05-05T10:05:00Z")
    @patch("products.logs.backend.temporal.activities._run_cohort_query")
    def test_one_cohorts_failure_isolated_within_batch(self, mock_run_cohort_query):
        # If one cohort raises, the remaining cohorts in the batch still run.
        # (Failure isolation across BATCHES is structural — separate Temporal
        # activities — so it's tested at workflow level, not here.)
        from products.logs.backend.temporal.activities import (
            CohortManifest,
            EvaluateCohortBatchInput,
            _CohortQueryResult,
            _PrefetchedQuery,
            evaluate_cohort_batch_activity,
        )

        alerts = [
            LogsAlertConfiguration.objects.create(
                team=self.team,
                name=f"a{i}",
                threshold_count=1,
                threshold_operator="above",
                window_minutes=5,
                evaluation_periods=1,
                filters={"serviceNames": [f"s{i}"]},
                enabled=True,
                next_check_at=None,
            )
            for i in range(3)
        ]

        # First cohort errors, second succeeds.
        call_count = {"n": 0}

        def _mock_query(cohort):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("boom")
            return _CohortQueryResult(per_alert={str(a.id): _PrefetchedQuery(buckets=[]) for a in cohort.alerts})

        mock_run_cohort_query.side_effect = _mock_query

        # Two single-alert manifests so we can target one specific cohort to fail.
        manifests = [
            CohortManifest(
                team_id=self.team.id,
                projection_eligible=True,
                date_to_iso="2026-05-05T10:05:00+00:00",
                alert_ids=[str(alerts[0].id)],
            ),
            CohortManifest(
                team_id=self.team.id,
                projection_eligible=True,
                date_to_iso="2026-05-05T10:05:00+00:00",
                alert_ids=[str(alerts[1].id)],
            ),
        ]

        result = asyncio.run(evaluate_cohort_batch_activity(EvaluateCohortBatchInput(manifests=manifests)))

        assert mock_run_cohort_query.call_count == 2
        # First cohort errored → counts as 1 errored. Second succeeded → 1 checked.
        assert result.alerts_errored == 1
        assert result.alerts_checked == 1
