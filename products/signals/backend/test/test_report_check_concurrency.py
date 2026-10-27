import json
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from queue import Queue
from time import monotonic
from typing import cast
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import NonAtomicBaseTest
from unittest.mock import AsyncMock, patch

from django.db import connection, transaction
from django.utils import timezone

from asgiref.sync import async_to_sync
from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.sync import database_sync_to_async

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import CheckObservation
from products.signals.backend.models import (
    SignalReport,
    SignalReportAgentEvaluation,
    SignalReportArtefact,
    SignalReportCheck,
    SignalReportMonitoringAttempt,
    SignalReportMonitoringResult,
    SignalScoutConfig,
    SignalScoutRun,
)
from products.signals.backend.report_check_agent import FALLBACK_CHECK_SKILL_NAME
from products.signals.backend.report_check_agent_runner import run_monitoring_agent
from products.signals.backend.report_check_authoring import cancel_check
from products.signals.backend.report_check_evaluation import CheckVerdict
from products.signals.backend.report_check_execution import (
    expire_overdue_checks,
    record_check_verdict,
    run_due_report_checks,
)
from products.signals.backend.report_check_final_agents import (
    AgentMonitoringResult,
    claim_agent_evaluation,
    fail_agent_evaluation,
    stage_agent_result,
)
from products.signals.backend.report_check_monitoring import MONITORING_ERROR_RETRY_AFTER, record_monitoring_observation
from products.signals.backend.report_checks import MAX_CHECK_HORIZON
from products.signals.backend.report_monitoring_attempts import check_definition_version, complete_implementation
from products.signals.backend.report_monitoring_results import (
    InvalidMonitoringResult,
    MonitoringEvaluation,
    MonitoringResultConflict,
    save_monitoring_result,
)
from products.signals.backend.test.report_metric_test_fixtures import trends_metric_query
from products.skills.backend.models.skills import LLMSkill
from products.tasks.backend.models import Task, TaskRun


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

    def _agent_attempt(self) -> SignalReportMonitoringAttempt:
        now = timezone.now()
        self.report.status = SignalReport.Status.MONITORING
        self.report.monitoring_started_at = now - timedelta(hours=2)
        self.report.save(update_fields=["status", "monitoring_started_at"])
        self.check.kind = SignalReportCheck.Kind.AGENT
        self.check.config = {"instructions": "Verify checkout during the fixed window."}
        self.check.soak_minutes = 60
        self.check.expires_at = now + timedelta(days=1)
        self.check.save(update_fields=["kind", "config", "soak_minutes", "expires_at"])
        return SignalReportMonitoringAttempt.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            report_id=self.report.id,
            monitoring_started_at=self.report.monitoring_started_at,
            check_versions={str(self.check.id): check_definition_version(self.check)},
        )

    @parameterized.expand([(None,), ("scout",), ("budget",)])
    def test_agent_runner_binds_before_dispatch_and_supplies_context_as_a_file(self, refusal: str | None) -> None:
        LLMSkill.objects.create(team=self.team, name=FALLBACK_CHECK_SKILL_NAME, is_latest=True, deleted=False)
        scout = SignalScoutConfig.objects.for_team(self.team.id).create(
            team_id=self.team.id, skill_name=FALLBACK_CHECK_SKILL_NAME, enabled=True
        )
        task = Task.objects.create(team=self.team, created_by=self.user, title="Verify outcome")
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        session = AsyncMock()
        session.task_run = run
        supplied: dict[str, object] = {}
        payload: dict[str, object] = {"guaranteed_team_ids": [self.team.id]}
        task_count = Task.objects.filter(team=self.team).count()
        run_count = TaskRun.objects.filter(team=self.team).count()
        result = AgentMonitoringResult(
            evidence_status="sufficient",
            evidence_reason="The checkout trace covers the fixed window.",
            expectation_matches=True,
            explanation="Checkout completed.",
            evidence_refs=("event:example",),
        )

        async def start(**kwargs: object) -> tuple[object, AgentMonitoringResult]:
            callback = cast(Callable[[UUID], None], kwargs["before_task_dispatch"])
            if refusal is not None:

                def create_refused_task() -> None:
                    if refusal == "scout":
                        scout.enabled = False
                        scout.save(update_fields=["enabled"])
                    else:
                        payload["default_team_config"] = {"max_runs_per_day": 1}
                        SignalScoutRun.objects.for_team(self.team.id).create(
                            team_id=self.team.id, task_run=run, skill_name="budget-scout", skill_version=1
                        )
                    Task.create_and_run(
                        team=self.team,
                        title="Monitoring check",
                        description="Verify the fixed window",
                        origin_product=Task.OriginProduct.SIGNAL_REPORT,
                        user_id=self.user.id,
                        signal_report_id=str(self.report.id),
                        ai_stage="monitoring_authored_check",
                        before_task_dispatch=callback,
                        start_workflow=False,
                    )

                await database_sync_to_async(create_refused_task)()
                raise AssertionError("Execution controls should refuse task creation")
            await database_sync_to_async(callback)(run.id)
            supplied.update(kwargs)
            return session, result

        with (
            patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True),
            patch(
                "products.signals.backend.scout_harness.run_gates._read_flag_payload",
                return_value=payload,
            ),
            patch(
                "products.signals.backend.scout_harness.team_limits._read_flag_payload",
                return_value=payload,
            ),
            patch("products.signals.backend.report_check_agent_runner.MultiTurnSession.start", side_effect=start),
            patch(
                "products.signals.backend.report_check_agent_runner.get_or_create_signals_sandbox_env",
                return_value="test-env",
            ),
            patch("products.signals.backend.agent_runtime._read_flag_payload", return_value={}),
        ):
            attempt = self._agent_attempt()
            evaluation = claim_agent_evaluation(team_id=self.team.id, report_id=self.report.id, check_id=self.check.id)
            assert evaluation is not None
            async_to_sync(run_monitoring_agent)(team_id=self.team.id, evaluation_id=evaluation.id)
            if refusal is not None:
                fail_agent_evaluation(team_id=self.team.id, evaluation_id=evaluation.id)
                evaluation.refresh_from_db()
                assert evaluation.state == SignalReportAgentEvaluation.State.ABANDONED
                assert evaluation.task_run_id is None
                assert not SignalReportMonitoringResult.objects.for_team(self.team.id).exists()
                assert Task.objects.filter(team=self.team).count() == task_count
                assert TaskRun.objects.filter(team=self.team).count() == run_count
                scout.enabled = True
                scout.save(update_fields=["enabled"])
                payload.pop("default_team_config", None)
                replacement = claim_agent_evaluation(
                    team_id=self.team.id, report_id=self.report.id, check_id=self.check.id
                )
                assert replacement is not None and replacement.id != evaluation.id
                assert replacement.window_end == evaluation.window_end
                return
        stored = SignalReportMonitoringResult.objects.for_team(self.team.id).get()
        assert stored.evidence_refs[-1] == f"task-run:{run.id}"
        files = supplied["files"]
        assert isinstance(files, list)
        context = json.loads(files[0].content)
        assert context["check"]["config"] == self.check.config
        assert context["window_end"] == evaluation.window_end.isoformat()
        assert context["attempt_id"] == str(attempt.id)
        session.end.assert_awaited_once()

    def test_concurrent_agent_dispatch_claims_share_one_durable_identity(self) -> None:
        LLMSkill.objects.create(team=self.team, name=FALLBACK_CHECK_SKILL_NAME, is_latest=True, deleted=False)
        SignalScoutConfig.objects.for_team(self.team.id).create(
            team_id=self.team.id, skill_name=FALLBACK_CHECK_SKILL_NAME, enabled=True
        )
        with (
            patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True),
            patch(
                "products.signals.backend.scout_harness.run_gates._read_flag_payload",
                return_value={"guaranteed_team_ids": [self.team.id]},
            ),
            patch(
                "products.signals.backend.scout_harness.team_limits._read_flag_payload",
                return_value={"guaranteed_team_ids": [self.team.id]},
            ),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            self._agent_attempt()

            def claim() -> SignalReportAgentEvaluation | None:
                return claim_agent_evaluation(team_id=self.team.id, report_id=self.report.id, check_id=self.check.id)

            with transaction.atomic():
                SignalReport.objects.select_for_update(no_key=True).get(id=self.report.id)
                future = self._start_write(executor, claim)
                self._assert_write_waits(future)
                first = claim()
                assert first is not None
            second = future.result(timeout=10)
        assert isinstance(second, SignalReportAgentEvaluation)
        assert first.id == second.id
        assert SignalReportAgentEvaluation.objects.for_team(self.team.id).count() == 1

    def test_agent_result_waiting_for_report_lock_rechecks_manual_completion(self) -> None:
        with patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True):
            attempt = self._agent_attempt()
            evaluation = SignalReportAgentEvaluation.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                report_id=self.report.id,
                attempt_id=attempt.id,
                report_check_id=self.check.id,
                definition_version=check_definition_version(self.check),
                window_start=attempt.monitoring_started_at,
                window_end=attempt.monitoring_started_at + timedelta(hours=1),
                sequence=1,
                state="running",
                task_run_id=self.check.id,
                user_id=self.user.id,
            )
            with ThreadPoolExecutor(max_workers=1) as executor:
                with transaction.atomic():
                    SignalReport.objects.select_for_update(no_key=True).get(id=self.report.id)
                    future = self._start_write(
                        executor,
                        lambda: stage_agent_result(
                            team_id=self.team.id,
                            evaluation_id=evaluation.id,
                            task_run_id=self.check.id,
                            result=AgentMonitoringResult(
                                evidence_status="sufficient",
                                evidence_reason="A checkout trace covers the window.",
                                expectation_matches=True,
                                explanation="Checkout succeeded.",
                                evidence_refs=("event:example",),
                            ),
                        ),
                    )
                    self._assert_write_waits(future)
                    self.report.status = SignalReport.Status.RESOLVED
                    self.report.save(update_fields=["status"])
                with self.assertRaises(InvalidMonitoringResult):
                    future.result(timeout=10)
        evaluation.refresh_from_db()
        assert evaluation.output is None
        assert not SignalReportMonitoringResult.objects.for_team(self.team.id).exists()

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
                assert self.check.status == change
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
                with self.assertRaises(MonitoringResultConflict):
                    future.result(timeout=10)
            else:
                duplicate = future.result(timeout=10)
                assert isinstance(duplicate, SignalReportMonitoringResult)
                assert duplicate.id == accepted.id
        assert SignalReportMonitoringResult.objects.for_team(self.team.id).count() == 1

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
