from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from queue import Queue
from time import monotonic
from uuid import uuid4

import time_machine
from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from django.db import connection, transaction
from django.utils import timezone

from parameterized import parameterized
from rest_framework.test import APIClient

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import CheckObservation
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportCheck,
    SignalReportMonitoringAttempt,
    SignalReportMonitoringResult,
)
from products.signals.backend.report_check_authoring import cancel_check
from products.signals.backend.report_check_evaluation import CheckVerdict
from products.signals.backend.report_check_execution import (
    expire_overdue_checks,
    record_check_verdict,
    run_due_report_checks,
)
from products.signals.backend.report_check_monitoring import MONITORING_ERROR_RETRY_AFTER, record_monitoring_observation
from products.signals.backend.report_checks import MAX_CHECK_HORIZON
from products.signals.backend.report_monitoring_attempts import check_definition_version, complete_implementation
from products.signals.backend.report_monitoring_outcomes import aggregate_monitoring_attempt
from products.signals.backend.report_monitoring_results import (
    InvalidMonitoringResult,
    MonitoringEvaluation,
    MonitoringResultConflict,
    save_monitoring_result,
)
from products.signals.backend.test.report_metric_test_fixtures import trends_metric_query


@time_machine.travel("2026-10-01T12:00:00Z", tick=False)
class TestReportCheckConcurrency(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.worker_pids: Queue[int] = Queue()
        self.report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.RESOLVED)
        now = timezone.now()
        self.check = SignalReportCheck.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            report=self.report,
            title="Errors stay low",
            kind=SignalReportCheck.Kind.METRIC_THRESHOLD,
            status=SignalReportCheck.Status.ACTIVE,
            config={
                "query": trends_metric_query(series=[{"kind": "EventsNode", "event": "$pageview"}]),
                "comparison": {"operator": "lte", "value": 10},
                "monitoring": {"reference_period_minutes": 10080, "threshold_scaling": "linear"},
            },
            soak_minutes=14 * 1440,
            next_run_at=now - timedelta(hours=1),
            expires_at=now - timedelta(minutes=1),
        )

    def _start_write(self, executor: ThreadPoolExecutor, write: Callable[[], object]) -> Future[object]:
        def run() -> object:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '15s'")
                    cursor.execute("SELECT pg_backend_pid()")
                    self.worker_pids.put(cursor.fetchone()[0])
                return write()
            finally:
                connection.close()

        return executor.submit(run)

    def _assert_write_waits(self, future: Future[object]) -> None:
        worker_pid = self.worker_pids.get(timeout=10)
        deadline = monotonic() + 10
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            holder_pid = cursor.fetchone()[0]
            while monotonic() < deadline:
                if future.done():
                    future.result()
                    self.fail("The competing write finished before the holder transaction ended")
                cursor.execute("SELECT %s = ANY(pg_blocking_pids(%s))", [holder_pid, worker_pid])
                if cursor.fetchone()[0]:
                    return
        self.fail("The competing write did not wait for the holder transaction")

    @parameterized.expand([(False,), (True,)])
    def test_stopping_monitoring_rejects_a_verdict_waiting_for_the_report_lock(self, bulk: bool) -> None:
        now = timezone.now()
        self.report.status = SignalReport.Status.MONITORING
        self.report.monitoring_started_at = now - timedelta(days=1)
        self.report.save(update_fields=["status", "monitoring_started_at"])
        self.check.expires_at = now + timedelta(days=30)
        self.check.save(update_fields=["expires_at"])
        client = APIClient()
        client.force_authenticate(self.user)
        url = (
            f"/api/projects/{self.team.id}/signals/reports/bulk-state/"
            if bulk
            else f"/api/projects/{self.team.id}/signals/reports/{self.report.id}/state/"
        )
        with (
            patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            with transaction.atomic():
                SignalReport.objects.select_for_update().get(id=self.report.id, team_id=self.team.id)
                future = self._start_write(
                    executor,
                    lambda: record_check_verdict(
                        self.check, CheckVerdict(outcome="passed", explanation="Late query result", observed_value=1)
                    ),
                )
                self._assert_write_waits(future)
                response = client.post(
                    url,
                    {
                        "state": "resolved",
                        "dismissal_reason": "verified_manually",
                        **({"ids": [str(self.report.id)]} if bulk else {}),
                    },
                    format="json",
                )
                assert response.status_code == 200, response.json()
            future.result(timeout=10)
        self.report.refresh_from_db()
        self.check.refresh_from_db()
        assert self.report.status == SignalReport.Status.RESOLVED
        assert self.check.status == SignalReportCheck.Status.CANCELLED
        assert self.check.last_outcome is None
        assert not SignalReportArtefact.objects.filter(report=self.report, type="check_result").exists()

    def _final_evaluation(self) -> MonitoringEvaluation:
        now = timezone.now()
        start = now - timedelta(hours=1)
        SignalReport.objects.filter(id=self.report.id, team_id=self.team.id).update(status=SignalReport.Status.READY)
        SignalReportCheck.objects.for_team(self.team.id).filter(id=self.check.id).update(
            soak_minutes=60, expires_at=now + timedelta(days=1)
        )
        self.check.refresh_from_db()
        attempt = complete_implementation(team_id=self.team.id, report_id=self.report.id, monitoring_started_at=start)
        assert attempt is not None
        return MonitoringEvaluation(
            team_id=self.team.id,
            report_id=self.report.id,
            attempt_id=attempt.id,
            check_id=self.check.id,
            submission_id=uuid4(),
            definition_version=check_definition_version(self.check),
            window_start=start,
            window_end=now,
            evaluated_at=now,
            evidence_status="sufficient",
            evidence_reason="qualifying_observations",
            expectation_matches=True,
            explanation="The expectation holds.",
        )

    @parameterized.expand([("cancelled",), ("definition",), ("completed",), ("flag_off",), ("errored",), ("expired",)])
    def test_final_result_rechecks_check_invalidation_after_a_lock_wait(self, change: str) -> None:
        with (
            patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True) as flag,
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            evaluation = self._final_evaluation()
            checks = SignalReportCheck.objects.for_team(self.team.id).filter(id=self.check.id)
            with transaction.atomic():
                checks.select_for_update().get()
                future = self._start_write(executor, lambda: save_monitoring_result(evaluation))
                self._assert_write_waits(future)
                if change == "cancelled":
                    assert cancel_check(
                        self.check, reason="stopped_by_person", attribution=ArtefactAttribution.system()
                    )
                elif change == "definition":
                    checks.update(title="A different expectation")
                elif change in {"errored", "expired", "completed"}:
                    checks.update(
                        status=SignalReportCheck.Status.PASSED if change == "completed" else change,
                        expires_at=timezone.now(),
                    )
                else:
                    flag.return_value = False
            if change in {"errored", "expired"}:
                result = future.result(timeout=10)
                assert isinstance(result, SignalReportMonitoringResult)
                assert result.outcome == "passed"
                self.check.refresh_from_db()
                assert self.check.status == SignalReportCheck.Status.PASSED
            else:
                with self.assertRaises(InvalidMonitoringResult):
                    future.result(timeout=10)
        assert SignalReportMonitoringResult.objects.for_team(self.team.id).exists() == (
            change in {"errored", "expired"}
        )

    @parameterized.expand([("resolved",), ("suppressed",), ("reopened",)])
    def test_final_result_rechecks_report_state_after_a_lock_wait(self, change: str) -> None:
        with (
            patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            evaluation = self._final_evaluation()
            with transaction.atomic():
                report = SignalReport.objects.select_for_update(no_key=True).get(
                    id=self.report.id, team_id=self.team.id
                )
                future = self._start_write(executor, lambda: save_monitoring_result(evaluation))
                self._assert_write_waits(future)
                target = {
                    "resolved": SignalReport.Status.RESOLVED,
                    "suppressed": SignalReport.Status.SUPPRESSED,
                    "reopened": SignalReport.Status.READY,
                }[change]
                report.save(update_fields=report.transition_to(target))
            with self.assertRaises(InvalidMonitoringResult):
                future.result(timeout=10)
        assert not SignalReportMonitoringResult.objects.for_team(self.team.id).exists()

    @parameterized.expand([("duplicate",), ("conflict",)])
    def test_concurrent_final_submissions_accept_one_verdict(self, change: str) -> None:
        with (
            patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            evaluation = self._final_evaluation()
            competitor = (
                replace(evaluation, submission_id=uuid4(), expectation_matches=False)
                if change == "conflict"
                else evaluation
            )
            with transaction.atomic():
                SignalReport.objects.select_for_update(no_key=True).get(id=self.report.id, team_id=self.team.id)
                future = self._start_write(executor, lambda: save_monitoring_result(competitor))
                self._assert_write_waits(future)
                accepted = save_monitoring_result(evaluation)
            if change == "conflict":
                with self.assertRaises((MonitoringResultConflict, InvalidMonitoringResult)):
                    future.result(timeout=10)
            else:
                duplicate = future.result(timeout=10)
                assert isinstance(duplicate, SignalReportMonitoringResult)
                assert duplicate.id == accepted.id
        assert SignalReportMonitoringResult.objects.for_team(self.team.id).count() == 1

    def test_aggregation_preserves_manual_resolution_after_a_report_lock_wait(self) -> None:
        with (
            patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            evaluation = replace(self._final_evaluation(), expectation_matches=False)
            with transaction.atomic():
                report = SignalReport.objects.select_for_update(no_key=True).get(
                    id=self.report.id, team_id=self.team.id
                )
                save_monitoring_result(evaluation)
                future = self._start_write(
                    executor,
                    lambda: aggregate_monitoring_attempt(
                        team_id=self.team.id, report_id=self.report.id, attempt_id=evaluation.attempt_id
                    ),
                )
                self._assert_write_waits(future)
                report.save(update_fields=report.transition_to(SignalReport.Status.RESOLVED))
            future.result(timeout=10)
        self.report.refresh_from_db()
        attempt = SignalReportMonitoringAttempt.objects.for_team(self.team.id).get(id=evaluation.attempt_id)
        assert self.report.status == SignalReport.Status.RESOLVED
        assert attempt.research_requested_at is None

    def test_aggregation_does_not_wait_for_unrelated_historical_checks(self) -> None:
        with (
            patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True),
            patch("products.signals.backend.tasks.close_report_tracker_issue.delay"),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            evaluation = self._final_evaluation()
            SignalReportMonitoringResult.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                report_id=self.report.id,
                attempt_id=evaluation.attempt_id,
                report_check_id=self.check.id,
                submission_id=evaluation.submission_id,
                definition_version=evaluation.definition_version,
                window_start=evaluation.window_start,
                window_end=evaluation.window_end,
                evaluated_at=evaluation.evaluated_at,
                outcome="passed",
                evidence_status="sufficient",
                evidence_reason=evaluation.evidence_reason,
                expectation_matches=True,
                explanation=evaluation.explanation,
            )
            historical = SignalReportCheck.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                report=self.report,
                title="An expired observation",
                kind=SignalReportCheck.Kind.METRIC_THRESHOLD,
                status=SignalReportCheck.Status.EXPIRED,
                next_run_at=timezone.now(),
                expires_at=timezone.now(),
            )
            with transaction.atomic():
                SignalReportCheck.objects.for_team(self.team.id).select_for_update().get(id=historical.id)
                future = self._start_write(
                    executor,
                    lambda: aggregate_monitoring_attempt(
                        team_id=self.team.id, report_id=self.report.id, attempt_id=evaluation.attempt_id
                    ),
                )
                assert future.result(timeout=10) == "passed"
        self.report.refresh_from_db()
        assert self.report.status == SignalReport.Status.RESOLVED

    @parameterized.expand([("cancelled",), ("extended",)])
    def test_expiry_sweep_preserves_a_concurrent_change(self, change: str) -> None:
        now = timezone.now()
        checks = SignalReportCheck.objects.for_team(self.team.id).filter(id=self.check.id)
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                checks.select_for_update().get()
                future = self._start_write(
                    executor, lambda: expire_overdue_checks(now, disabled_monitoring_organization_ids=frozenset())
                )
                self._assert_write_waits(future)
                if change == "cancelled":
                    assert cancel_check(
                        self.check, reason="stopped_by_person", attribution=ArtefactAttribution.system()
                    )
                else:
                    checks.update(expires_at=now + timedelta(days=1), updated_at=now)
            assert future.result(timeout=10) == 0
        self.check.refresh_from_db()
        assert self.check.status == (
            SignalReportCheck.Status.CANCELLED if change == "cancelled" else SignalReportCheck.Status.ACTIVE
        )
        if change == "extended":
            assert self.check.expires_at == now + timedelta(days=1)
        assert not SignalReportArtefact.objects.filter(
            team_id=self.team.id, report=self.report, type=SignalReportArtefact.ArtefactType.CHECK_EXPIRED
        ).exists()

    @parameterized.expand(
        [(outcome, entry) for outcome in ("cancelled", "expired") for entry in ("service", "single", "bulk")]
    )
    def test_monitoring_entry_rechecks_eligibility_after_a_lock_wait(self, outcome: str, entry: str) -> None:
        now = timezone.now()
        SignalReport.objects.filter(id=self.report.id, team_id=self.team.id).update(status=SignalReport.Status.READY)
        checks = SignalReportCheck.objects.for_team(self.team.id).filter(id=self.check.id)
        checks.update(expires_at=now + timedelta(days=1))

        def enter_monitoring() -> object:
            if entry == "service":
                return complete_implementation(
                    team_id=self.team.id, report_id=self.report.id, monitoring_started_at=now
                )
            client = APIClient()
            client.force_authenticate(self.user)
            url = (
                f"/api/projects/{self.team.id}/signals/reports/bulk-state/"
                if entry == "bulk"
                else f"/api/projects/{self.team.id}/signals/reports/{self.report.id}/state/"
            )
            response = client.post(
                url,
                {"state": "monitoring", **({"ids": [str(self.report.id)]} if entry == "bulk" else {})},
                format="json",
            )
            assert response.status_code == 200, response.json()
            result = response.json()["results"][0] if entry == "bulk" else response.json()
            assert result["status"] == SignalReport.Status.RESOLVED
            return None

        with (
            patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True),
            ThreadPoolExecutor(max_workers=1) as executor,
            time_machine.travel(now, tick=False) as clock,
        ):
            with transaction.atomic():
                checks.select_for_update().get()
                future = self._start_write(executor, enter_monitoring)
                self._assert_write_waits(future)
                if outcome == "cancelled":
                    assert cancel_check(
                        self.check, reason="stopped_by_person", attribution=ArtefactAttribution.system()
                    )
                else:
                    clock.shift(timedelta(days=2))
            assert future.result(timeout=10) is None
        self.report.refresh_from_db()
        self.check.refresh_from_db()
        assert self.report.status == SignalReport.Status.RESOLVED
        assert self.check.status == (
            SignalReportCheck.Status.CANCELLED if outcome == "cancelled" else SignalReportCheck.Status.EXPIRED
        )
        assert not SignalReportMonitoringAttempt.objects.for_team(self.team.id).filter(report=self.report).exists()
        assert SignalReportArtefact.objects.filter(
            team_id=self.team.id,
            report=self.report,
            type=SignalReportArtefact.ArtefactType.CHECK_CANCELLED
            if outcome == "cancelled"
            else SignalReportArtefact.ArtefactType.CHECK_EXPIRED,
        ).exists()

    def test_schedule_repair_preserves_a_concurrent_observation(self) -> None:
        now = timezone.now()
        start = now - timedelta(days=1)
        self.report.status = SignalReport.Status.MONITORING
        self.report.monitoring_started_at = start
        self.report.save(update_fields=["status", "monitoring_started_at"])
        SignalReportCheck.objects.for_team(self.team.id).filter(id=self.check.id).update(
            measurement_start_at=start, expires_at=start + MAX_CHECK_HORIZON, updated_at=start
        )
        self.check.refresh_from_db()
        observation = CheckObservation(
            check_id=str(self.check.id),
            title=self.check.title,
            monitoring_started_at=start,
            measured_at=now,
            monitoring_ends_at=start + timedelta(minutes=self.check.soak_minutes or 0),
            error="The metric query failed.",
            explanation="The metric query failed.",
        )
        with (
            patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            with transaction.atomic():
                SignalReportCheck.objects.for_team(self.team.id).select_for_update().get(id=self.check.id)
                future = self._start_write(executor, lambda: run_due_report_checks(now=now, limit=0))
                self._assert_write_waits(future)
                with patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True):
                    assert record_monitoring_observation(self.check, observation)
            future.result(timeout=10)
        self.check.refresh_from_db()
        assert self.check.last_run_at == now
        assert self.check.next_run_at == now + MONITORING_ERROR_RETRY_AFTER
        assert self.check.consecutive_errors == 1
        assert self.check.expires_at == start + MAX_CHECK_HORIZON
        assert (
            SignalReportArtefact.objects.filter(
                team_id=self.team.id, report=self.report, type=SignalReportArtefact.ArtefactType.CHECK_OBSERVATION
            ).count()
            == 1
        )
