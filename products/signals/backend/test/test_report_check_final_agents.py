from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from typing import cast
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import BaseTest, NonAtomicBaseTest, PostHogTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from asgiref.sync import async_to_sync
from parameterized import parameterized
from rest_framework.test import APIClient
from temporalio.converter import default
from temporalio.exceptions import ActivityError
from temporalio.testing import ActivityEnvironment

from posthog.models import OAuthApplication, Team
from posthog.sync import database_sync_to_async

from products.signals.backend.models import (
    SignalReport,
    SignalReportCheck,
    SignalReportMonitoringResult,
    SignalScoutConfig,
    SignalScoutRun,
    SignalScratchpad,
)
from products.signals.backend.report_check_execution import run_due_report_checks
from products.signals.backend.report_check_final_agents import (
    MONITORING_AGENT_DISPATCH_BACKOFF,
    MonitoringScoutCheck,
    MonitoringScoutResult,
    build_monitoring_run_note,
    finalize_monitoring_scout_run,
    monitoring_scout_check,
    run_due_final_agents,
    submit_monitoring_scout_result,
)
from products.signals.backend.report_check_final_candidates import DueFinalCheck, collect_due_final_checks
from products.signals.backend.report_metric_refresh import MetricMeasurement
from products.signals.backend.report_monitoring_attempts import check_definition_version, complete_implementation
from products.signals.backend.scout_harness.limits import STALE_RUN_CUTOFF_S, TRIGGERED_BY_MONITORING
from products.signals.backend.scout_harness.prompt import SignalScoutRunSummary
from products.signals.backend.temporal.agentic.scout_scheduler import (
    RunSignalsScoutInput,
    RunSignalsScoutOutput,
    RunSignalsScoutWorkflow,
    finalize_monitoring_scout_run_activity,
    run_signals_scout_activity,
)
from products.signals.backend.test.report_metric_test_fixtures import trends_metric_query
from products.skills.backend.models.skills import LLMSkill, LLMSkillFile
from products.tasks.backend.facade.agents import CustomPromptSandboxContext
from products.tasks.backend.facade.testing import create_task_run_oauth_access_token
from products.tasks.backend.models import Task, TaskRun


class FinalAuthoredAgentChecksSetup(PostHogTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.clock = time_machine.travel(timezone.now(), tick=False)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.flag = patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True)
        self.flag.start()
        self.addCleanup(self.flag.stop)
        self.now = timezone.now()
        self.skill = LLMSkill.objects.create(
            team=self.team,
            name="checkout-verifier",
            description="Verify checkout",
            body="Read the checkout playbook before querying. Keep useful notes.",
            allowed_tools=["emit_report", "edit_report", "remember"],
            created_by=self.user,
        )
        LLMSkillFile.objects.create(
            skill=self.skill,
            path="references/playbook.md",
            content="Inspect checkout failures.",
            content_type="text/markdown",
        )
        self.scout = SignalScoutConfig.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            skill_name=self.skill.name,
            enabled=True,
            created_by=self.user,
            network_access=SignalScoutConfig.NetworkAccess.FULL,
            write_scopes=["notebook:write"],
        )
        self.report = SignalReport.objects.create(
            team=self.team, title="Checkout errors", status=SignalReport.Status.READY
        )
        self.check = SignalReportCheck.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            report=self.report,
            title="Checkout failures stopped",
            kind=SignalReportCheck.Kind.AGENT,
            config={
                "skill_name": self.skill.name,
                "instructions": "Verify no checkout errors occurred while checkouts continued.",
                "probe_hints": ["Read checkout traffic and error events."],
            },
            soak_minutes=60,
            next_run_at=self.now,
            expires_at=self.now + timedelta(days=30),
            runs_remaining=3,
        )
        self.start = self.now - timedelta(hours=2)
        attempt = complete_implementation(
            team_id=self.team.id, report_id=self.report.id, monitoring_started_at=self.start
        )
        assert attempt is not None
        self.attempt = attempt
        self.check.refresh_from_db()
        self.report.refresh_from_db()
        self.binding = monitoring_scout_check(self._due()[0])
        self.note = build_monitoring_run_note(self.binding, self.check)

    def _due(self) -> list[DueFinalCheck]:
        return collect_due_final_checks(timezone.now(), kind=SignalReportCheck.Kind.AGENT, limit=10)

    def _payload(self, status: str = "sufficient", matches: bool | None = False) -> str:
        return json.dumps(
            {
                "evidence_status": status,
                "evidence_reason": "Traffic establishes an observable window.",
                "expectation_matches": matches,
                "explanation": "Checkout traffic continued and failures remain.",
                "evidence_refs": ["https://example.com/evidence/checkout"],
            }
        )

    def _run(self, summary: str, *, status: str = "completed") -> SignalScoutRun:
        task = Task.objects.create(team=self.team, title="Scout", origin_product=Task.OriginProduct.SIGNALS_SCOUT)
        task_run = TaskRun.objects.create(team=self.team, task=task, status=status)
        return SignalScoutRun.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            task_run=task_run,
            skill_name=self.skill.name,
            skill_version=1,
            metadata={"triggered_by": TRIGGERED_BY_MONITORING, "run_note": self.note},
            summary=summary,
        )

    def _deliver(
        self,
        run: SignalScoutRun,
        *,
        binding: MonitoringScoutCheck | None = None,
        note: str | None = None,
        run_id: str | None = None,
    ) -> None:
        finalize_monitoring_scout_run(
            binding or self.binding,
            canonical_team_id=self.team.id,
            skill_name=self.skill.name,
            run_note=note or self.note,
            run_id=run_id or str(run.id),
        )


class TestFinalAuthoredAgentChecks(FinalAuthoredAgentChecksSetup, BaseTest):
    def test_due_selection_uses_original_membership_soak_and_version(self) -> None:
        assert self.binding.window_start == self.start
        assert self.binding.window_end == self.start + timedelta(hours=1)
        assert self.binding.attempt_id == self.attempt.id
        with time_machine.travel(self.start + timedelta(minutes=59), tick=False):
            assert self._due() == []
        self.check.title = "A changed expectation"
        self.check.save(update_fields=["title"])
        assert self._due() == []
        self.check.title = "Checkout failures stopped"
        self.check.save(update_fields=["title"])
        late = SignalReportCheck.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            report=self.report,
            title="Late check",
            kind="agent",
            config=self.check.config,
            soak_minutes=0,
            next_run_at=self.now,
            expires_at=self.now + timedelta(days=30),
        )
        assert [item.member.check.id for item in self._due()] == [self.check.id]
        assert late.id not in self.attempt.check_versions
        self.report.status = SignalReport.Status.RESOLVED
        self.report.save(update_fields=["status"])
        assert self._due() == []

    @parameterized.expand(
        [
            ("sufficient", True, "passed"),
            ("sufficient", False, "failed"),
            ("insufficient", True, "inconclusive"),
            ("insufficient", None, "inconclusive"),
            ("unsupported", None, "inconclusive"),
            ("errored", None, "errored"),
        ]
    )
    def test_submission_preserves_qualification_separately_from_match(
        self, evidence_status: str, matches: bool | None, outcome: str
    ) -> None:
        self.check.monitoring_dispatch_after = self.now + MONITORING_AGENT_DISPATCH_BACKOFF
        self.check.save(update_fields=["monitoring_dispatch_after"])
        run = self._run("The Monitoring result was submitted.", status="in_progress")
        submit_monitoring_scout_result(
            run, MonitoringScoutResult.model_validate_json(self._payload(evidence_status, matches))
        )
        self._deliver(run)
        result = SignalReportMonitoringResult.objects.for_team(self.team.id).get()
        assert result.outcome == outcome
        assert result.window_start == self.start and result.window_end == self.start + timedelta(hours=1)
        assert result.definition_version == self.binding.definition_version
        assert result.attempt_id == self.attempt.id
        self._deliver(run)
        assert SignalReportMonitoringResult.objects.for_team(self.team.id).count() == 1
        self.report.refresh_from_db()
        self.check.refresh_from_db()
        assert self.report.status == SignalReport.Status.MONITORING
        assert self.check.last_outcome is None and self.check.runs_remaining == 3
        self.assertIsNone(self.check.monitoring_dispatch_after)
        if outcome != "errored":
            assert result.evidence_status == evidence_status
            assert result.expectation_matches == matches
            assert result.evidence_refs == ["https://example.com/evidence/checkout"]
        if evidence_status == "errored":
            assert self._due() == []
            with time_machine.travel(self.now + timedelta(minutes=5), tick=False):
                next_due = self._due()[0]
                assert next_due.submission_id != self.binding.submission_id
                assert next_due.member.window_end == self.binding.window_end

    @parameterized.expand(["changed", "cancelled", "reopened", "wrong_run", "wrong_team", "wrong_note", "disabled"])
    def test_stale_or_unbound_output_cannot_be_accepted(self, change: str) -> None:
        run = self._run(self._payload())
        binding = self.binding
        run_id = str(run.id)
        note = self.note
        if change == "changed":
            self.check.config = {"instructions": "Verify a different expectation."}
            self.check.save(update_fields=["config"])
        elif change == "cancelled":
            self.check.status = SignalReportCheck.Status.CANCELLED
            self.check.save(update_fields=["status"])
        elif change == "reopened":
            SignalReport.objects.filter(id=self.report.id).update(
                status=SignalReport.Status.READY, monitoring_started_at=None
            )
        elif change == "wrong_run":
            run_id = str(uuid4())
        elif change == "wrong_team":
            other = Team.objects.create(organization=self.organization, name="Other")
            binding = replace(binding, team_id=other.id)
        elif change == "wrong_note":
            note = "unrelated brief"
        elif change == "disabled":
            self.flag.stop()
        self._deliver(run, binding=binding, run_id=run_id, note=note)
        assert not SignalReportMonitoringResult.objects.for_team(self.team.id).exists()

    @parameterized.expand(["prose", "json", "failed"])
    def test_a_closeout_without_a_submission_records_a_bounded_execution_error(self, shape: str) -> None:
        run = self._run(
            self._payload("sufficient", True) if shape == "json" else "No errors found.",
            status="failed" if shape == "failed" else "completed",
        )
        self._deliver(run)
        result = SignalReportMonitoringResult.objects.for_team(self.team.id).get()
        assert result.evidence_status == "errored" and result.expectation_matches is None
        assert self._due() == []

    @parameterized.expand(["in_progress", "completed"])
    def test_accepted_submission_does_not_wait_for_task_finalization(self, status: str) -> None:
        run = self._run("Submitted the evidence.", status="in_progress")
        accepted = submit_monitoring_scout_result(
            run, MonitoringScoutResult.model_validate_json(self._payload("sufficient", True))
        )
        run.task_run.status = status
        run.task_run.save(update_fields=["status"])
        self._deliver(run)
        result = SignalReportMonitoringResult.objects.for_team(self.team.id).get()
        assert result.id == accepted.id and result.outcome == "passed"
        run.task_run.refresh_from_db()
        assert run.task_run.status == status

    @parameterized.expand(["queued", "in_progress"])
    def test_recovery_leaves_live_runs_time_to_submit_and_expires_orphans(self, status: str) -> None:
        run = self._run("Still investigating.", status=status)
        self._deliver(run)
        assert not SignalReportMonitoringResult.objects.for_team(self.team.id).exists()
        with time_machine.travel(self.now + timedelta(seconds=STALE_RUN_CUTOFF_S + 1), tick=False):
            self._deliver(run)
        assert SignalReportMonitoringResult.objects.for_team(self.team.id).get().evidence_status == "errored"

    def test_finalization_preserves_a_submitted_result_independently_of_summary(self) -> None:
        run = self._run("Submission accepted.", status="in_progress")
        accepted = submit_monitoring_scout_result(
            run, MonitoringScoutResult.model_validate_json(self._payload("sufficient", True))
        )
        run.summary = self._payload("sufficient", False)
        run.save(update_fields=["summary"])
        self._deliver(run)
        accepted.refresh_from_db()
        assert accepted.outcome == "passed"
        assert self._due() == []

    def test_failures_before_a_run_exists_consume_only_the_bounded_retry_budget(self) -> None:
        finalize_monitoring_scout_run(
            self.binding, canonical_team_id=self.team.id, skill_name=self.skill.name, run_note=self.note, run_id=None
        )
        assert not SignalReportMonitoringResult.objects.for_team(self.team.id).exists()
        for index, minutes in enumerate((0, 5, 20)):
            with time_machine.travel(self.now + timedelta(minutes=minutes), tick=False):
                binding = monitoring_scout_check(self._due()[0])
                note = build_monitoring_run_note(binding, self.check)
                for _ in range(2):
                    finalize_monitoring_scout_run(
                        binding,
                        canonical_team_id=self.team.id,
                        skill_name=self.skill.name,
                        run_note=note,
                        run_id=None,
                        failed=True,
                    )
                results = SignalReportMonitoringResult.objects.for_team(self.team.id)
                assert results.count() == index + 1
                assert not results.exclude(evidence_status="errored").exists()
                assert self._due() == []
        with time_machine.travel(self.now + timedelta(days=1), tick=False):
            assert self._due() == []
        assert not SignalScoutRun.objects.for_team(self.team.id).exists()

    @parameterized.expand([False, True])
    def test_deferred_scouts_cannot_starve_other_due_checks(self, expired: bool) -> None:
        self.scout.enabled = False
        self.scout.save(update_fields=["enabled"])
        paused = [self.check]
        for index in range(9):
            paused.append(
                SignalReportCheck.objects.for_team(self.team.id).create(
                    team_id=self.team.id,
                    report=self.report,
                    title=f"Paused check {index}",
                    kind="agent",
                    config=self.check.config,
                    soak_minutes=60,
                    next_run_at=self.now,
                    expires_at=self.now + timedelta(days=30),
                )
            )
        active_skill = LLMSkill.objects.create(
            team=self.team, name="active-verifier", body="Verify the expectation.", created_by=self.user
        )
        SignalScoutConfig.objects.for_team(self.team.id).create(
            team_id=self.team.id, skill_name=active_skill.name, enabled=True, created_by=self.user
        )
        active = SignalReportCheck.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            report=self.report,
            title="Active scout check",
            kind="agent",
            config={"skill_name": active_skill.name, "instructions": "Verify recovery."},
            soak_minutes=120,
            next_run_at=self.now,
            expires_at=self.now + timedelta(days=30),
        )
        self.attempt.check_versions = {str(check.id): check_definition_version(check) for check in [*paused, active]}
        self.attempt.save(update_fields=["check_versions"])
        if expired:
            SignalReportCheck.objects.for_team(self.team.id).filter(id__in=[check.id for check in paused]).update(
                status=SignalReportCheck.Status.EXPIRED, expires_at=self.now - timedelta(minutes=1)
            )
        client = MagicMock()
        client.start_workflow = AsyncMock()
        with (
            patch("posthog.temporal.common.client.sync_connect", return_value=client),
            patch(
                "products.signals.backend.scout_harness.run_gates._read_flag_payload",
                return_value={"guaranteed_team_ids": [self.team.id]},
            ),
        ):
            first = run_due_final_agents(now=self.now, deadline=time.monotonic() + 30, limit=10)
            assert first.deferred == 10 and first.dispatched == 0
            later = self.now + MONITORING_AGENT_DISPATCH_BACKOFF * 2
            with time_machine.travel(later, tick=False):
                second = run_due_final_agents(now=later, deadline=time.monotonic() + 30, limit=1)
        assert second.dispatched == 1 and second.deferred == 0
        assert client.start_workflow.call_args.args[1].monitoring_check.check_id == active.id
        assert not SignalReportMonitoringResult.objects.for_team(self.team.id).exists()
        with time_machine.travel(self.now + MONITORING_AGENT_DISPATCH_BACKOFF, tick=False):
            assert self._due()

    def test_paused_agent_batches_leave_capacity_for_interim_measurements_on_consecutive_ticks(self) -> None:
        self.scout.enabled = False
        self.scout.save(update_fields=["enabled"])
        for team_index in range(10):
            team = (
                self.team
                if team_index == 0
                else Team.objects.create(organization=self.organization, name=f"Scout project {team_index}")
            )
            report = (
                self.report
                if team_index == 0
                else SignalReport.objects.create(team=team, title="Checkout recovery", status=SignalReport.Status.READY)
            )
            for check_index in range(9 if team_index == 0 else 10):
                SignalReportCheck.objects.for_team(team.id).create(
                    team_id=team.id,
                    report=report,
                    title=f"Deferred agent {check_index}",
                    kind="agent",
                    config=self.check.config,
                    soak_minutes=60,
                    next_run_at=self.now,
                    expires_at=self.now + timedelta(days=30),
                )
            if team_index == 0:
                checks = SignalReportCheck.objects.for_team(team.id).filter(report=report)
                self.attempt.check_versions = {str(check.id): check_definition_version(check) for check in checks}
                self.attempt.save(update_fields=["check_versions"])
            else:
                complete_implementation(team_id=team.id, report_id=report.id, monitoring_started_at=self.start)
        metric_reports: list[SignalReport] = []
        for offset in (0, 30, 60):
            start = self.now + timedelta(minutes=offset) - timedelta(hours=6)
            report = SignalReport.objects.create(
                team=self.team, title=f"Interim metric {offset}", status=SignalReport.Status.READY
            )
            SignalReportCheck.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                report=report,
                title="Interim checkout measurement",
                kind="metric_threshold",
                config={
                    "query": trends_metric_query(series=[{"kind": "EventsNode", "event": "checkout"}]),
                    "comparison": {"operator": "gte", "value": 1},
                    "monitoring": {"reference_period_minutes": 120, "threshold_scaling": "linear"},
                },
                soak_minutes=24 * 60,
                run_interval_minutes=6 * 60,
                next_run_at=start + timedelta(hours=6),
                expires_at=self.now + timedelta(days=30),
                runs_remaining=5,
            )
            complete_implementation(team_id=self.team.id, report_id=report.id, monitoring_started_at=start)
            metric_reports.append(report)
        for offset in (0, 30, 60):
            tick = self.now + timedelta(minutes=offset)
            with (
                time_machine.travel(tick, tick=False),
                patch(
                    "products.signals.backend.scout_harness.run_gates._read_flag_payload",
                    return_value={"guaranteed_team_ids": [self.team.id]},
                ),
                patch(
                    "products.signals.backend.report_check_monitoring.measure_metric",
                    return_value=MetricMeasurement(value=8, measured_at=tick, series=None),
                ),
            ):
                summary = run_due_report_checks(now=tick, limit=50)
            assert summary.dispatched == 0
            assert summary.deferred == 25
            assert summary.observed == 1
        assert all(report.artefacts.filter(type="check_observation").count() == 1 for report in metric_reports)
        assert not SignalReportMonitoringResult.objects.for_team(self.team.id).exists()

    @parameterized.expand(["paused", "not_enrolled", "daily_budget"])
    def test_dispatch_respects_normal_scout_controls(self, gate: str) -> None:
        payload = {"guaranteed_team_ids": [self.team.id], "default_team_config": {"max_runs_per_day": 10}}
        if gate == "paused":
            self.scout.enabled = False
            self.scout.save(update_fields=["enabled"])
        elif gate == "not_enrolled":
            payload["skip_team_ids"] = [self.team.id]
        elif gate == "daily_budget":
            payload["default_team_config"] = {"max_runs_per_day": 1}
            prior = self._run(self._payload())
            prior.metadata = {}
            prior.save(update_fields=["metadata"])
        with (
            patch("products.signals.backend.scout_harness.run_gates._read_flag_payload", return_value=payload),
            patch("posthog.temporal.common.client.sync_connect") as connect,
        ):
            summary = run_due_final_agents(now=self.now, deadline=time.monotonic() + 30, limit=10)
        assert summary.dispatched == 0 and summary.deferred == 1
        connect.assert_not_called()

    def test_coordinator_dispatches_the_existing_scout_workflow_and_binds_its_input(self) -> None:
        client = MagicMock()
        client.start_workflow = AsyncMock()
        with (
            patch("posthog.temporal.common.client.sync_connect", return_value=client),
            patch(
                "products.signals.backend.scout_harness.run_gates._read_flag_payload",
                return_value={"guaranteed_team_ids": [self.team.id]},
            ),
        ):
            summary = run_due_report_checks(now=self.now, limit=10)
        assert summary.dispatched == 1
        input = client.start_workflow.call_args.args[1]
        assert input.skill_name == self.skill.name
        assert input.monitoring_check == self.binding
        assert input.triggered_by == TRIGGERED_BY_MONITORING
        assert input.check_id is None
        assert json.loads(input.run_note)["team_id"] == self.team.id


class TestFinalAuthoredAgentExecution(FinalAuthoredAgentChecksSetup, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_child_environment_checks_remain_deferred_without_execution_artifacts(self) -> None:
        child = Team.objects.create(
            organization=self.organization, parent_team=self.team, name="Verification environment"
        )
        report = SignalReport.objects.create(team=child, title="Checkout errors", status=SignalReport.Status.READY)
        check = SignalReportCheck.objects.for_team(child.id).create(
            team_id=child.id,
            report=report,
            title=self.check.title,
            kind="agent",
            config=self.check.config,
            soak_minutes=0,
            next_run_at=self.now,
            expires_at=self.now + timedelta(days=30),
        )
        attempt = complete_implementation(team_id=child.id, report_id=report.id, monitoring_started_at=self.start)
        assert attempt is not None
        self.check.status = SignalReportCheck.Status.CANCELLED
        self.check.save(update_fields=["status"])
        binding = MonitoringScoutCheck(
            team_id=child.id,
            report_id=report.id,
            attempt_id=attempt.id,
            check_id=check.id,
            submission_id=uuid4(),
            definition_version=check_definition_version(check),
            window_start_iso=self.start.isoformat(),
            window_end_iso=self.start.isoformat(),
        )
        with patch("posthog.temporal.common.client.sync_connect") as connect:
            summary = run_due_final_agents(now=self.now, deadline=time.monotonic() + 30, limit=10)
        assert summary.dispatched == 0
        connect.assert_not_called()
        input = RunSignalsScoutInput(
            team_id=self.team.id,
            skill_name=self.skill.name,
            triggered_by=TRIGGERED_BY_MONITORING,
            monitoring_check=binding,
            run_note=build_monitoring_run_note(binding, check),
        )

        async def execute() -> RunSignalsScoutOutput:
            return await ActivityEnvironment().run(run_signals_scout_activity, input)

        output = async_to_sync(execute)()
        assert output.skip_reason == "monitoring_check_unavailable"
        assert not SignalScoutRun.all_teams.exists()
        assert not TaskRun.objects.exists()
        assert not SignalReportMonitoringResult.objects.for_team(child.id).exists()
        check.refresh_from_db()
        assert check.monitoring_dispatch_after is None

    def test_monitoring_uses_the_full_runner_and_corrects_submission_without_a_second_run(self) -> None:
        memory = SignalScratchpad.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            key="checkout-context",
            content="Compare failures with completed checkouts.",
        )
        input = RunSignalsScoutInput(
            team_id=self.team.id,
            skill_name=self.skill.name,
            triggered_by=TRIGGERED_BY_MONITORING,
            run_note=self.note,
            monitoring_check=self.binding,
        )
        captured: dict[str, object] = {}

        def make_task_run() -> TaskRun:
            task = Task.objects.create(team=self.team, title="Scout", origin_product=Task.OriginProduct.SIGNALS_SCOUT)
            return TaskRun.objects.create(team=self.team, task=task, status="in_progress")

        def submit_with_correction(task_run_id: UUID) -> None:
            run = SignalScoutRun.objects.for_team(self.team.id).get(task_run_id=task_run_id)
            application = OAuthApplication.objects.create(
                name="Synthetic Monitoring scout",
                client_type=OAuthApplication.CLIENT_PUBLIC,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris="http://localhost:8237/callback",
                algorithm="RS256",
            )
            with patch("posthog.temporal.oauth.get_sandbox_oauth_app", return_value=application):
                token = create_task_run_oauth_access_token(
                    team_id=self.team.id,
                    task_run_id=task_run_id,
                    user_id=self.user.id,
                    scopes=cast(CustomPromptSandboxContext, captured["context"]).posthog_mcp_scopes or "signals_scout",
                )
            client = APIClient()
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
            url = f"/api/projects/{self.team.id}/signals/scout/runs/{run.id}/monitoring_result/"
            invalid = client.post(url, json.loads(self._payload("sufficient", None)), format="json")
            assert invalid.status_code == 400, invalid.data
            assert "expectation_matches" in str(invalid.data)
            assert not SignalReportMonitoringResult.objects.for_team(self.team.id).exists()
            accepted = client.post(url, json.loads(self._payload("sufficient", False)), format="json")
            assert accepted.status_code == 200, accepted.data
            assert accepted.data["accepted"] is True
            captured["submission_statuses"] = [invalid.status_code, accepted.status_code]

        async def start(
            *, before_task_dispatch: Callable[[UUID], None], **kwargs: object
        ) -> tuple[MagicMock, SignalScoutRunSummary]:
            captured.update(kwargs)
            task_run = await database_sync_to_async(make_task_run)()
            await database_sync_to_async(before_task_dispatch)(task_run.id)
            await database_sync_to_async(submit_with_correction)(task_run.id)
            session = MagicMock(task_run=task_run)

            async def end() -> None:
                task_run.status = "completed"
                await database_sync_to_async(task_run.save)(update_fields=["status"])

            session.end = AsyncMock(side_effect=end)
            return session, SignalScoutRunSummary(
                summary="Submitted the Monitoring verdict after correcting validation errors."
            )

        async def activity() -> RunSignalsScoutOutput:
            return await ActivityEnvironment().run(run_signals_scout_activity, input)

        self.scout.enabled = False
        self.scout.save(update_fields=["enabled"])
        with patch(
            "products.signals.backend.scout_harness.runner.MultiTurnSession.start", new_callable=AsyncMock
        ) as paused:
            assert async_to_sync(activity)().skip_reason == "monitoring_check_unavailable"
        paused.assert_not_called()
        self.scout.enabled = True
        self.scout.save(update_fields=["enabled"])
        with (
            patch("products.signals.backend.scout_harness.runner.MultiTurnSession.start", new=start),
            patch(
                "products.signals.backend.scout_harness.runner.get_or_create_signals_sandbox_env",
                return_value="sandbox-env",
            ),
            patch(
                "products.signals.backend.scout_harness.run_gates._read_flag_payload",
                return_value={"guaranteed_team_ids": [self.team.id]},
            ),
        ):
            output = async_to_sync(activity)()
        assert output.status == "completed", output
        assert captured["submission_statuses"] == [400, 200]
        assert output.last_message is None
        context = cast(CustomPromptSandboxContext, captured["context"])
        assert context.user_id == self.user.id
        assert context.team_id == self.team.id
        assert output.run_id is not None
        run = SignalScoutRun.objects.for_team(self.team.id).get(id=output.run_id)
        assert context.github_read_access is True
        assert context.posthog_mcp_scopes == {
            "preset": "signals_scout_reports",
            "extra_write_scopes": ["notebook:write"],
        }
        assert captured["mcp_builtin_agent_key"] == "scout"
        assert captured["model"] is SignalScoutRunSummary
        assert captured["mcp_tool_allowlist"] is None
        prompt = cast(str, captured["prompt"])
        assert self.skill.name in prompt and "skill-file-get" in prompt
        assert "skill-get(skill_name=" in prompt
        assert "scout-scratchpad-search" in prompt
        memory.refresh_from_db()
        assert memory.content == "Compare failures with completed checkouts."
        assert "Authored Monitoring check" in prompt
        assert "sole assignment and takes precedence" in prompt
        assert "Do not call scout-check-record-result" in prompt
        assert "Skip the skill's scheduled queues, empty-queue early exits" in prompt
        assert "scout-monitoring-result-submit" in prompt
        assert "Do not finish until the tool returns accepted=true" in prompt
        assert output.run_id is not None
        run = SignalScoutRun.objects.for_team(self.team.id).get(id=output.run_id)
        assert run.metadata is not None
        assert run.metadata["run_note"] == self.note
        self.scout.enabled = False
        self.scout.save(update_fields=["enabled"])
        with patch(
            "products.signals.backend.scout_harness.runner.MultiTurnSession.start", new_callable=AsyncMock
        ) as second_start:
            replay = async_to_sync(activity)()
        second_start.assert_not_called()
        assert replay.run_id is None and replay.skip_reason == "monitoring_check_unavailable"
        finalize_monitoring_scout_run_activity(input, output.run_id)
        result = SignalReportMonitoringResult.objects.for_team(self.team.id).get()
        assert result.outcome == "failed" and result.report_check_id == self.check.id
        assert run.team_id == self.team.id and run.task_run.team_id == self.team.id


class TestMonitoringScoutWorkflow(SimpleTestCase):
    @parameterized.expand([False, True])
    def test_existing_temporal_converter_preserves_the_binding_and_old_inputs(self, monitoring: bool) -> None:
        now = timezone.now()
        binding = MonitoringScoutCheck(
            team_id=1,
            report_id=uuid4(),
            attempt_id=uuid4(),
            check_id=uuid4(),
            submission_id=uuid4(),
            definition_version="definition",
            window_start_iso=(now - timedelta(hours=1)).isoformat(),
            window_end_iso=now.isoformat(),
        )
        input = RunSignalsScoutInput(
            team_id=1, skill_name="checkout-verifier", monitoring_check=binding if monitoring else None
        )

        async def round_trip() -> RunSignalsScoutInput:
            converter = default()
            payloads = await converter.encode([input])
            return (await converter.decode(payloads, [RunSignalsScoutInput]))[0]

        restored = async_to_sync(round_trip)()
        assert restored == input
        if monitoring:
            assert restored.monitoring_check is not None
            assert restored.monitoring_check.window_start == now - timedelta(hours=1)
            assert restored.monitoring_check.window_end == now

    @parameterized.expand(
        ["completed", "failed", "failed_without_run", "cancelled_without_run", "worker_error", "skipped"]
    )
    def test_finalization_retries_independently_of_the_normal_scout_activity(self, outcome: str) -> None:
        now = timezone.now()
        binding = MonitoringScoutCheck(
            team_id=1,
            report_id=uuid4(),
            attempt_id=uuid4(),
            check_id=uuid4(),
            submission_id=uuid4(),
            definition_version="definition",
            window_start_iso=(now - timedelta(hours=1)).isoformat(),
            window_end_iso=now.isoformat(),
        )
        input = RunSignalsScoutInput(
            team_id=1,
            skill_name="checkout-verifier",
            triggered_by=TRIGGERED_BY_MONITORING,
            monitoring_check=binding,
            run_note="brief",
        )
        output = RunSignalsScoutOutput(
            run_id=None if outcome == "skipped" or outcome.endswith("_without_run") else "run",
            task_run_id=None,
            status=outcome.removesuffix("_without_run"),
            runtime_s=0,
            skill_name=input.skill_name,
            skill_version=1,
        )
        error = ActivityError(
            "Worker stopped",
            scheduled_event_id=1,
            started_event_id=2,
            identity="worker",
            activity_type="run_signals_scout_activity",
            activity_id="scout",
            retry_state=None,
        )
        with (
            patch("temporalio.workflow.patched", return_value=False),
            patch(
                "temporalio.workflow.execute_activity",
                new_callable=AsyncMock,
                side_effect=[error if outcome == "worker_error" else output, None],
            ) as execute,
        ):
            if outcome == "worker_error":
                with self.assertRaises(ActivityError):
                    async_to_sync(RunSignalsScoutWorkflow().run)(input)
            else:
                assert async_to_sync(RunSignalsScoutWorkflow().run)(input) == output
        assert execute.call_args_list[0].args == (run_signals_scout_activity, input)
        assert execute.call_args_list[0].kwargs["retry_policy"].maximum_attempts == 1
        if outcome == "skipped":
            assert execute.call_count == 1
        else:
            assert execute.call_count == 2
            delivery = execute.call_args_list[1]
            assert delivery.args == (finalize_monitoring_scout_run_activity,)
            assert delivery.kwargs["args"] == [
                input,
                None if outcome == "worker_error" or outcome.endswith("_without_run") else "run",
                outcome in {"failed", "failed_without_run", "cancelled_without_run", "worker_error"},
                True,
            ]
            assert delivery.kwargs["retry_policy"].maximum_attempts == 5
