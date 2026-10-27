from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized
from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.constants import AvailableFeature
from posthog.models import PropertyDefinition, Team, User

from products.access_control.backend.facade.contracts import PropertyAccessLevel
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import CheckObservation
from products.signals.backend.models import (
    SignalReport,
    SignalReportAgentEvaluation,
    SignalReportArtefact,
    SignalReportCheck,
    SignalReportMonitoringResult,
    SignalScoutConfig,
)
from products.signals.backend.report_check_agent import FALLBACK_CHECK_SKILL_NAME
from products.signals.backend.report_check_agent_context import build_agent_context
from products.signals.backend.report_check_execution import CHECK_ERROR_RETRY_AFTER
from products.signals.backend.report_check_final_agents import (
    AgentMonitoringResult,
    bind_agent_run,
    claim_agent_evaluation,
    deliver_agent_result,
    fail_agent_evaluation,
    monitoring_agent_start_refusal,
    run_due_agent_evaluations,
    stage_agent_result,
)
from products.signals.backend.report_monitoring_attempts import check_definition_version, complete_implementation
from products.signals.backend.report_monitoring_results import InvalidMonitoringResult, MonitoringResultConflict
from products.signals.backend.scout_harness.run_gates import check_fleet_gates
from products.signals.backend.temporal.agentic.monitoring_agents import start_monitoring_agent
from products.signals.backend.test.report_metric_test_fixtures import trends_metric_query
from products.skills.backend.models.skills import LLMSkill
from products.tasks.backend.facade.task_run_signals import task_run_start_refusal
from products.tasks.backend.models import Task, TaskRun


class TestMonitoringWorkflowDispatch(SimpleTestCase):
    @parameterized.expand([(False,), (True,)])
    def test_only_new_workflows_consume_dispatch_capacity(self, existing: bool) -> None:
        client = cast(
            Client,
            SimpleNamespace(
                start_workflow=AsyncMock(
                    side_effect=WorkflowAlreadyStartedError("monitoring-test", "MonitoringAgentWorkflow")
                    if existing
                    else None,
                )
            ),
        )
        assert start_monitoring_agent(client, team_id=1, evaluation_id=str(uuid4())) is not existing


class TestFinalAuthoredAgentChecks(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.now = timezone.now()
        self.clock = self.enterContext(time_machine.travel(self.now, tick=False))
        self.monitoring_flag = self.enterContext(
            patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True)
        )
        payload: dict[str, object] = {"guaranteed_team_ids": [self.team.id]}
        self.fleet_payload: dict[str, object] = payload
        self.enterContext(
            patch("products.signals.backend.scout_harness.run_gates._read_flag_payload", return_value=payload)
        )
        self.enterContext(
            patch("products.signals.backend.scout_harness.team_limits._read_flag_payload", return_value=payload)
        )
        LLMSkill.objects.create(team=self.team, name=FALLBACK_CHECK_SKILL_NAME, is_latest=True, deleted=False)
        self.scout = SignalScoutConfig.objects.for_team(self.team.id).create(
            team_id=self.team.id, skill_name=FALLBACK_CHECK_SKILL_NAME, enabled=True
        )
        self.report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="Verify checkout"
        )
        self.check = SignalReportCheck.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            report=self.report,
            title="Checkout succeeds",
            config={"instructions": "Inspect checkout results during the verification window."},
            kind=SignalReportCheck.Kind.AGENT,
            soak_minutes=60,
            next_run_at=self.now,
            expires_at=self.now + timedelta(days=1),
        )
        attempt = complete_implementation(
            team_id=self.team.id, report_id=self.report.id, monitoring_started_at=self.now - timedelta(hours=2)
        )
        assert attempt is not None
        self.attempt = attempt
        self.task = Task.objects.create(team=self.team, created_by=self.user, title="Verify outcome")
        self.task_run = TaskRun.objects.create(task=self.task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

    def claim(self) -> SignalReportAgentEvaluation:
        evaluation = claim_agent_evaluation(team_id=self.team.id, report_id=self.report.id, check_id=self.check.id)
        assert evaluation is not None
        return evaluation

    def bind(self, evaluation: SignalReportAgentEvaluation) -> None:
        bind_agent_run(
            team_id=self.team.id, evaluation_id=evaluation.id, task_run_id=self.task_run.id, user_id=self.user.id
        )

    def metric_member(self) -> SignalReportCheck:
        metric = SignalReportCheck.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            report=self.report,
            title="Checkout count",
            kind="metric_threshold",
            config={
                "query": trends_metric_query(series=[{"kind": "EventsNode", "event": "$pageview"}]),
                "comparison": {"operator": "lte", "value": 10},
            },
            soak_minutes=60,
            next_run_at=self.now,
            expires_at=self.now + timedelta(days=1),
        )
        assert self.attempt is not None
        self.attempt.check_versions[str(metric.id)] = check_definition_version(metric)
        self.attempt.save(update_fields=["check_versions"])
        return metric

    def result(self, *, evidence_status: str = "sufficient", matches: bool | None = True) -> AgentMonitoringResult:
        return AgentMonitoringResult.model_validate(
            {
                "evidence_status": evidence_status,
                "evidence_reason": "The checkout trace covers the required operation and fixed window.",
                "expectation_matches": matches,
                "explanation": "Checkout completed during the verification window.",
                "evidence_refs": ["event:example-checkout"],
            }
        )

    def test_claim_is_idempotent_and_ignores_checks_outside_the_attempt(self) -> None:
        first = self.claim()
        assert self.claim().id == first.id
        assert first.window_start == self.now - timedelta(hours=2)
        assert first.window_end == self.now - timedelta(hours=1)
        outsider = SignalReportCheck.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            report=self.report,
            title="Late check",
            kind="agent",
            config=self.check.config,
            soak_minutes=0,
            next_run_at=self.now,
            expires_at=self.now + timedelta(days=1),
        )
        assert claim_agent_evaluation(team_id=self.team.id, report_id=self.report.id, check_id=outsider.id) is None

    @parameterized.expand([("errored",), ("expired",)])
    def test_final_obligation_survives_interim_terminal_state(self, state: str) -> None:
        SignalReportCheck.objects.for_team(self.team.id).filter(id=self.check.id).update(
            status=state, expires_at=self.now
        )
        evaluation = self.claim()
        self.bind(evaluation)
        stage_agent_result(
            team_id=self.team.id, evaluation_id=evaluation.id, task_run_id=self.task_run.id, result=self.result()
        )
        deliver_agent_result(team_id=self.team.id, evaluation_id=evaluation.id)
        assert SignalReportMonitoringResult.objects.for_team(self.team.id).get().outcome == "passed"

    @parameterized.expand(
        [("insufficient", None, "inconclusive"), ("sufficient", False, "failed"), ("sufficient", True, "passed")]
    )
    def test_only_bound_run_can_submit_immutable_evidence(
        self, evidence: str, matches: bool | None, outcome: str
    ) -> None:
        evaluation = self.claim()
        self.bind(evaluation)
        result = self.result(evidence_status=evidence, matches=matches)
        with self.assertRaises(InvalidMonitoringResult):
            stage_agent_result(team_id=self.team.id, evaluation_id=evaluation.id, task_run_id=uuid4(), result=result)
        stage_agent_result(
            team_id=self.team.id, evaluation_id=evaluation.id, task_run_id=self.task_run.id, result=result
        )
        deliver_agent_result(team_id=self.team.id, evaluation_id=evaluation.id)
        stage_agent_result(
            team_id=self.team.id, evaluation_id=evaluation.id, task_run_id=self.task_run.id, result=result
        )
        deliver_agent_result(team_id=self.team.id, evaluation_id=evaluation.id)
        stored = SignalReportMonitoringResult.objects.for_team(self.team.id).get()
        assert stored.outcome == outcome
        assert stored.evidence_refs == ["event:example-checkout", f"task-run:{self.task_run.id}"]
        assert stored.window_end == self.now - timedelta(hours=1)
        with CaptureQueriesContext(connection) as queries:
            assert run_due_agent_evaluations() == 0
        assert not any("FOR UPDATE" in query["sql"] or "FOR NO KEY UPDATE" in query["sql"] for query in queries)
        with self.assertRaises(MonitoringResultConflict):
            stage_agent_result(
                team_id=self.team.id,
                evaluation_id=evaluation.id,
                task_run_id=self.task_run.id,
                result=result.model_copy(update={"explanation": "Conflicting delivery"}),
            )
        self.report.refresh_from_db()
        assert self.report.status == SignalReport.Status.MONITORING
        assert claim_agent_evaluation(team_id=self.team.id, report_id=self.report.id, check_id=self.check.id) is None

    @parameterized.expand([("status",), ("definition",), ("flag",), ("cancelled",), ("task_cancelled",), ("timeout",)])
    def test_changes_during_execution_reject_result_acceptance(self, change: str) -> None:
        evaluation = self.claim()
        self.bind(evaluation)
        if change == "status":
            self.report.status = SignalReport.Status.READY
            self.report.save(update_fields=["status"])
        elif change == "definition":
            SignalReportCheck.objects.for_team(self.team.id).filter(id=self.check.id).update(
                config={"instructions": "A new criterion"}
            )
        elif change == "flag":
            self.monitoring_flag.return_value = False
        elif change == "task_cancelled":
            TaskRun.objects.filter(id=self.task_run.id).update(status=TaskRun.Status.CANCELLED)
        elif change == "timeout":
            self.clock.shift(timedelta(hours=2))
        else:
            SignalReportCheck.objects.for_team(self.team.id).filter(id=self.check.id).update(status="cancelled")
        with self.assertRaises(InvalidMonitoringResult):
            stage_agent_result(
                team_id=self.team.id, evaluation_id=evaluation.id, task_run_id=self.task_run.id, result=self.result()
            )
        assert not SignalReportMonitoringResult.objects.for_team(self.team.id).exists()
        assert monitoring_agent_start_refusal(str(self.task.id), self.team.id, self.user.id) is not None

    def test_archive_restore_keeps_window_but_invalidates_the_old_run(self) -> None:
        evaluation = self.claim()
        self.bind(evaluation)
        self.report.refresh_from_db()
        self.report.save(update_fields=self.report.transition_to(SignalReport.Status.SUPPRESSED))
        self.report.save(update_fields=self.report.transition_to(SignalReport.Status.MONITORING))
        with self.assertRaises(InvalidMonitoringResult):
            stage_agent_result(
                team_id=self.team.id, evaluation_id=evaluation.id, task_run_id=self.task_run.id, result=self.result()
            )
        assert claim_agent_evaluation(team_id=self.team.id, report_id=self.report.id, check_id=self.check.id) is None
        TaskRun.objects.filter(id=self.task_run.id).update(status=TaskRun.Status.CANCELLED)
        resumed = self.claim()
        assert resumed.id != evaluation.id
        assert resumed.attempt_id == evaluation.attempt_id
        assert resumed.window_end == evaluation.window_end

    @parameterized.expand([(None,), (0,), (180,)])
    def test_explicit_soak_controls_due_work_and_zero_soak_cannot_prove_success(self, soak: int | None) -> None:
        SignalReportCheck.objects.for_team(self.team.id).filter(id=self.check.id).update(soak_minutes=soak)
        self.check.refresh_from_db()
        self.attempt.check_versions = {str(self.check.id): check_definition_version(self.check)}
        self.attempt.save(update_fields=["check_versions"])
        if soak is None or soak == 180:
            with self.assertRaises(InvalidMonitoringResult):
                self.claim()
            return
        evaluation = self.claim()
        self.bind(evaluation)
        stage_agent_result(
            team_id=self.team.id, evaluation_id=evaluation.id, task_run_id=self.task_run.id, result=self.result()
        )
        deliver_agent_result(team_id=self.team.id, evaluation_id=evaluation.id)
        assert SignalReportMonitoringResult.objects.for_team(self.team.id).get().evidence_status == "insufficient"

    def test_worker_errors_retry_three_times_without_reusing_a_live_run(self) -> None:
        for sequence in range(1, 4):
            evaluation = self.claim()
            assert evaluation.sequence == sequence
            fail_agent_evaluation(team_id=self.team.id, evaluation_id=evaluation.id)
            assert (
                claim_agent_evaluation(team_id=self.team.id, report_id=self.report.id, check_id=self.check.id) is None
            )
            self.clock.shift(CHECK_ERROR_RETRY_AFTER)
        assert claim_agent_evaluation(team_id=self.team.id, report_id=self.report.id, check_id=self.check.id) is None
        assert (
            list(SignalReportMonitoringResult.objects.for_team(self.team.id).values_list("outcome", flat=True))
            == ["errored"] * 3
        )

    def test_coordinator_recovers_ambiguous_dispatch_with_the_same_workflow_identity(self) -> None:
        with (
            patch("posthog.temporal.common.client.sync_connect", return_value=object()),
            patch(
                "products.signals.backend.temporal.agentic.monitoring_agents.start_monitoring_agent",
                side_effect=[RuntimeError("lost acknowledgement"), False],
            ) as start,
        ):
            run_due_agent_evaluations()
            self.clock.shift(timedelta(minutes=1))
            run_due_agent_evaluations()
        assert start.call_count == 2
        assert start.call_args_list[0].kwargs == start.call_args_list[1].kwargs
        assert SignalReportAgentEvaluation.objects.for_team(self.team.id).count() == 1

    @parameterized.expand([("flag",), ("scout",)])
    def test_queued_work_rechecks_execution_controls_before_provisioning(self, control: str) -> None:
        evaluation = self.claim()
        self.bind(evaluation)
        assert monitoring_agent_start_refusal(str(self.task.id), self.team.id, self.user.id) is None
        if control == "flag":
            self.monitoring_flag.return_value = False
        else:
            self.scout.enabled = False
            self.scout.save(update_fields=["enabled"])
        self.task_run.status = TaskRun.Status.QUEUED
        self.task_run.save(update_fields=["status"])
        assert task_run_start_refusal(str(self.task.id), self.team.id, self.user.id) is not None

    @parameterized.expand([(False,), (None,)])
    def test_disabled_or_unavailable_monitoring_never_dispatches(self, flag: bool | None) -> None:
        self.monitoring_flag.return_value = flag
        assert run_due_agent_evaluations() == 0
        assert not SignalReportAgentEvaluation.objects.for_team(self.team.id).exists()

    def test_metric_only_attempt_never_launches_an_authored_agent(self) -> None:
        self.check.kind = SignalReportCheck.Kind.METRIC_THRESHOLD
        self.check.config = {
            "query": trends_metric_query(series=[{"kind": "EventsNode", "event": "$pageview"}]),
            "comparison": {"operator": "lte", "value": 10},
        }
        self.check.save(update_fields=["kind", "config"])
        self.attempt.check_versions = {str(self.check.id): check_definition_version(self.check)}
        self.attempt.save(update_fields=["check_versions"])
        assert run_due_agent_evaluations() == 0
        assert not SignalReportAgentEvaluation.objects.for_team(self.team.id).exists()

    @parameterized.expand([(False,), (True,)])
    def test_staged_result_delivery_recovers_without_relaunching_the_agent(self, slow_cancellation: bool) -> None:
        if slow_cancellation:
            other_check = SignalReportCheck.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                report=self.report,
                title="Other verification",
                kind="agent",
                config=self.check.config,
                soak_minutes=60,
                next_run_at=self.now,
                expires_at=self.now + timedelta(days=1),
            )
            self.attempt.check_versions[str(other_check.id)] = check_definition_version(other_check)
            self.attempt.save(update_fields=["check_versions"])
            other_evaluation = claim_agent_evaluation(
                team_id=self.team.id, report_id=self.report.id, check_id=other_check.id
            )
            assert other_evaluation is not None
            other_task = Task.objects.create(team=self.team, created_by=self.user, title="Other verification")
            other_run = TaskRun.objects.create(task=other_task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
            bind_agent_run(
                team_id=self.team.id, evaluation_id=other_evaluation.id, task_run_id=other_run.id, user_id=self.user.id
            )
            SignalReportAgentEvaluation.objects.for_team(self.team.id).filter(id=other_evaluation.id).update(
                state=SignalReportAgentEvaluation.State.ABANDONED
            )
        evaluation = self.claim()
        self.bind(evaluation)
        stage_agent_result(
            team_id=self.team.id, evaluation_id=evaluation.id, task_run_id=self.task_run.id, result=self.result()
        )
        elapsed = [0.0]

        def cancel(*args: object, **kwargs: object) -> None:
            elapsed[0] += 10

        with (
            patch("products.signals.backend.temporal.agentic.monitoring_agents.start_monitoring_agent") as start,
            patch("products.signals.backend.report_check_final_agents.time.monotonic", side_effect=lambda: elapsed[0]),
            patch("products.signals.backend.report_check_final_agents.cancel_task_run", side_effect=cancel),
        ):
            assert run_due_agent_evaluations(deadline=30) == 1
        assert elapsed[0] == (10 if slow_cancellation else 0)
        start.assert_not_called()
        assert SignalReportMonitoringResult.objects.for_team(self.team.id).get().submission_id == evaluation.id

    @parameterized.expand([(phase, access) for phase in ("staged", "finalization") for access in ("user", "analytics")])
    def test_lost_access_abandons_the_run_and_allows_another_user_to_verify(self, phase: str, access: str) -> None:
        self.metric_member()
        evaluation = self.claim()
        self.bind(evaluation)
        if phase == "staged":
            stage_agent_result(
                team_id=self.team.id, evaluation_id=evaluation.id, task_run_id=self.task_run.id, result=self.result()
            )
        if access == "user":
            self.user.is_active = False
            self.user.save(update_fields=["is_active"])

        with (
            patch("products.signals.backend.report_check_final_agents.cancel_task_run") as cancel,
            patch(
                "products.signals.backend.report_check_final_agents.metric_context_reader",
                return_value=lambda _queries: access != "analytics",
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            with self.assertRaises(InvalidMonitoringResult):
                if phase == "staged":
                    deliver_agent_result(team_id=self.team.id, evaluation_id=evaluation.id)
                else:
                    fail_agent_evaluation(team_id=self.team.id, evaluation_id=evaluation.id)
        evaluation.refresh_from_db()
        assert evaluation.state == SignalReportAgentEvaluation.State.ABANDONED
        assert not SignalReportMonitoringResult.objects.for_team(self.team.id).exists()
        cancel.assert_called_once()
        fail_agent_evaluation(team_id=self.team.id, evaluation_id=evaluation.id)

        TaskRun.objects.filter(id=self.task_run.id).update(status=TaskRun.Status.CANCELLED)
        replacement = self.claim()
        assert replacement.id != evaluation.id
        verifier = User.objects.create_user(
            email="replacement-verifier@example.com", first_name="Verifier", password=None
        )
        self.organization.members.add(verifier)
        task = Task.objects.create(team=self.team, created_by=verifier, title="Replacement verification")
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        bind_agent_run(team_id=self.team.id, evaluation_id=replacement.id, task_run_id=run.id, user_id=verifier.id)
        replacement.refresh_from_db()
        assert replacement.user_id == verifier.id
        assert replacement.state == SignalReportAgentEvaluation.State.RUNNING

    def test_queued_recoveries_leave_capacity_for_new_checks_and_rotate(self) -> None:
        pending_ids = set()
        for index in range(5):
            check = SignalReportCheck.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                report=self.report,
                title=f"Check {index}",
                kind="agent",
                config=self.check.config,
                soak_minutes=60,
                next_run_at=self.now,
                expires_at=self.now + timedelta(days=1),
            )
            self.attempt.check_versions[str(check.id)] = check_definition_version(check)
        self.attempt.save(update_fields=["check_versions"])
        for check_id in list(self.attempt.check_versions)[:3]:
            evaluation = claim_agent_evaluation(team_id=self.team.id, report_id=self.report.id, check_id=check_id)
            assert evaluation is not None
            pending_ids.add(str(evaluation.id))
        dispatched = []

        def start(_client: object, *, team_id: int, evaluation_id: str) -> bool:
            dispatched.append(evaluation_id)
            return evaluation_id not in pending_ids

        with (
            patch("products.signals.backend.report_check_final_agents.MAX_AGENT_DISPATCHES_PER_TICK", 2),
            patch("products.signals.backend.report_check_final_agents.MAX_AGENT_RECOVERIES_PER_TICK", 2),
            patch("posthog.temporal.common.client.sync_connect", return_value=object()),
            patch(
                "products.signals.backend.temporal.agentic.monitoring_agents.start_monitoring_agent", side_effect=start
            ),
        ):
            assert run_due_agent_evaluations() == 2
            assert len(set(dispatched) - pending_ids) == 2
            first_recovered = set(dispatched) & pending_ids
            self.clock.shift(timedelta(minutes=1))
            dispatched.clear()
            run_due_agent_evaluations()
        assert pending_ids - first_recovered <= set(dispatched)

    @parameterized.expand([("exception", True), ("live_run", False)])
    def test_failed_drain_requests_rotate_before_retrying(self, _name: str, raises: bool) -> None:
        run_ids: list[UUID] = []
        for sequence in range(1, 4):
            run = TaskRun.objects.create(task=self.task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
            evaluation = SignalReportAgentEvaluation.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                report=self.report,
                attempt=self.attempt,
                report_check=self.check,
                definition_version=check_definition_version(self.check),
                window_start=self.attempt.monitoring_started_at,
                window_end=self.attempt.monitoring_started_at + timedelta(hours=1),
                sequence=sequence,
                state=SignalReportAgentEvaluation.State.ABANDONED,
                task_id=self.task.id,
                task_run_id=run.id,
            )
            SignalReportAgentEvaluation.objects.for_team(self.team.id).filter(id=evaluation.id).update(
                created_at=self.now - timedelta(minutes=4 - sequence)
            )
            run_ids.append(run.id)
        requested: list[UUID] = []

        def cancel(run_id: UUID, *args: object, **kwargs: object) -> None:
            requested.append(run_id)
            if raises:
                raise RuntimeError("Cancellation is unavailable")

        self.monitoring_flag.return_value = False
        with (
            patch("products.signals.backend.report_check_final_agents.MAX_AGENT_RECOVERIES_PER_TICK", 2),
            patch("products.signals.backend.report_check_final_agents.cancel_task_run", side_effect=cancel),
        ):
            run_due_agent_evaluations()
            assert requested == run_ids[:2]
            requested.clear()
            run_due_agent_evaluations()
            assert requested == run_ids[2:]
            requested.clear()
            run_due_agent_evaluations()
            assert requested == []
            self.clock.shift(timedelta(minutes=1))
            run_due_agent_evaluations()
            assert requested == run_ids[:2]
        assert SignalReportAgentEvaluation.objects.for_team(self.team.id).filter(drained_at__isnull=True).count() == 3

    def test_expired_sweep_budget_defers_new_dispatches(self) -> None:
        with patch("products.signals.backend.report_check_final_agents.time.monotonic", return_value=10):
            assert run_due_agent_evaluations(deadline=9) == 0
        assert not SignalReportAgentEvaluation.objects.for_team(self.team.id).exists()

    def test_context_includes_only_current_attempt_observations(self) -> None:
        metric = self.metric_member()
        evaluation = self.claim()
        self.bind(evaluation)
        evaluation.refresh_from_db()
        for start in [evaluation.window_start - timedelta(days=1), evaluation.window_start]:
            SignalReportArtefact.add_log(
                team_id=self.team.id,
                report_id=str(self.report.id),
                attribution=ArtefactAttribution.system(),
                content=CheckObservation(
                    check_id=str(metric.id),
                    title="Checkout count",
                    monitoring_started_at=start,
                    measured_at=start + timedelta(minutes=30),
                    monitoring_ends_at=start + timedelta(hours=1),
                    comparison={"operator": "lte", "value": 10},
                    observed_value=1,
                    matches=True,
                    explanation="One event observed.",
                ),
            )
        context = json.loads(build_agent_context(evaluation))
        assert len(context["current_attempt_observations"]) == 1
        assert context["current_attempt_observations"][0]["content"]["check_id"] == str(metric.id)

    def test_restricted_analytics_context_is_not_given_to_an_agent(self) -> None:
        self.metric_member()
        evaluation = self.claim()
        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=PropertyDefinition.objects.create(
                team=self.team, name="restricted_plan", property_type="String", type=PropertyDefinition.Type.EVENT
            ),
            organization_member=self.organization_membership,
            access_level=PropertyAccessLevel.NONE.value,
        )
        with self.assertRaises(InvalidMonitoringResult):
            self.bind(evaluation)
        evaluation.refresh_from_db()
        assert evaluation.task_run_id is None

    @parameterized.expand([(field, reopened) for field in ("query", "eligibility_query") for reopened in (False, True)])
    def test_agent_only_attempt_checks_permissions_on_all_attached_plans(self, field: str, reopened: bool) -> None:
        evaluation = self.claim()
        self.bind(evaluation)
        evaluation.refresh_from_db()
        allowed_query = trends_metric_query(series=[{"kind": "EventsNode", "event": "$pageview"}])
        restricted_query = trends_metric_query(series=[{"kind": "ActionsNode", "id": 42}])
        plan = {"query": allowed_query, field: restricted_query}
        SignalReportArtefact.objects.create(
            team_id=self.team.id,
            report=self.report,
            type="impact_measurement_plan",
            content=json.dumps(plan),
        )
        if reopened:
            self.report.refresh_from_db()
            self.report.save(update_fields=self.report.transition_to(SignalReport.Status.READY))
        with patch(
            "products.signals.backend.report_metric_access.ReportMetricAccessPolicy._may_read_resource_id",
            return_value=False,
        ):
            with self.assertRaises(InvalidMonitoringResult):
                build_agent_context(evaluation)
            with self.assertRaises(InvalidMonitoringResult):
                stage_agent_result(
                    team_id=self.team.id,
                    evaluation_id=evaluation.id,
                    task_run_id=self.task_run.id,
                    result=self.result(),
                )

    def test_a_parent_project_run_cannot_answer_an_environment_check(self) -> None:
        environment = Team.objects.create(
            organization=self.organization, project=self.team.project, parent_team=self.team, name="Staging"
        )
        SignalReport.objects.filter(id=self.report.id).update(team_id=environment.id)
        SignalReportCheck.objects.for_team(self.team.id).filter(id=self.check.id).update(team_id=environment.id)
        assert self.attempt is not None
        self.attempt.team_id = environment.id
        self.attempt.save(update_fields=["team_id"])
        evaluation = claim_agent_evaluation(team_id=environment.id, report_id=self.report.id, check_id=self.check.id)
        assert evaluation is not None
        with self.assertRaises(InvalidMonitoringResult):
            bind_agent_run(
                team_id=environment.id, evaluation_id=evaluation.id, task_run_id=self.task_run.id, user_id=self.user.id
            )

    @parameterized.expand([(False,), (True,)])
    def test_scout_budget_counts_monitoring_runs_without_refusing_their_own_reservation(
        self, environment: bool
    ) -> None:
        team = self.team
        if environment:
            team = Team.objects.create(
                organization=self.organization, project=self.team.project, parent_team=self.team, name="Staging"
            )
            SignalReport.objects.filter(id=self.report.id).update(team_id=team.id)
            SignalReportCheck.objects.for_team(self.team.id).filter(id=self.check.id).update(team_id=team.id)
            self.attempt.team_id = team.id
            self.attempt.save(update_fields=["team_id"])
        self.fleet_payload["default_team_config"] = {"max_runs_per_day": 1}
        evaluation = claim_agent_evaluation(team_id=team.id, report_id=self.report.id, check_id=self.check.id)
        assert evaluation is not None
        task = Task.objects.create(team=team, created_by=self.user, title="Verify outcome")
        run = TaskRun.objects.create(task=task, team=team, status=TaskRun.Status.IN_PROGRESS)
        bind_agent_run(team_id=team.id, evaluation_id=evaluation.id, task_run_id=run.id, user_id=self.user.id)
        refusal = check_fleet_gates(self.team.id)
        assert refusal is not None and refusal.reason == "daily_run_budget"
        assert monitoring_agent_start_refusal(str(task.id), team.id, self.user.id) is None

    def test_reopening_implementation_rejects_the_old_attempts_run(self) -> None:
        evaluation = self.claim()
        self.bind(evaluation)
        self.report.refresh_from_db()
        self.report.save(update_fields=self.report.transition_to(SignalReport.Status.READY))
        complete_implementation(team_id=self.team.id, report_id=self.report.id, monitoring_started_at=self.now)
        with self.assertRaises(InvalidMonitoringResult):
            stage_agent_result(
                team_id=self.team.id, evaluation_id=evaluation.id, task_run_id=self.task_run.id, result=self.result()
            )
