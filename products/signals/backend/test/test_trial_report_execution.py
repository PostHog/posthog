import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from uuid import UUID, uuid4

from posthog.test.base import NonAtomicBaseTest
from unittest.mock import AsyncMock, patch

from django.db import close_old_connections, connection, transaction
from django.utils import timezone

import httpx
from anthropic import APIStatusError
from asgiref.sync import async_to_sync
from parameterized import parameterized
from requests.exceptions import ReadTimeout

from posthog.llm.gateway_client import AIGatewayConfig
from posthog.llm.gateway_usage import GatewayRequestCost
from posthog.sync import database_sync_to_async

from products.signals.backend.custom_agent.persistence import create_custom_agent_ready_report
from products.signals.backend.custom_agent.schemas import CustomAgentFinalReport
from products.signals.backend.facade.trial import task_trial_admission
from products.signals.backend.llm_spend import generate_with_spend
from products.signals.backend.models import ArtefactAttribution, InvalidStatusTransition, SignalReport, SignalSpend
from products.signals.backend.report_generation.research import ActionabilityAssessment, ActionabilityChoice
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.scout_harness.tools.emit import SCOUT_SIGNAL_WEIGHT
from products.signals.backend.scout_report import ScoutReportSignal, create_scout_report
from products.signals.backend.spend import (
    begin_report_spend,
    begin_signal_spend,
    complete_signal_pipeline,
    lock_signal_spend,
    record_llm_spend,
)
from products.signals.backend.system_one_decision import run_model_decision
from products.signals.backend.system_one_prompts import bundled_prompt
from products.signals.backend.task_run_artefacts import record_report_task
from products.signals.backend.temporal.summary import (
    CheckReportQuotaGateInput,
    MarkReportInProgressInput,
    check_report_quota_gate_activity,
    mark_report_in_progress_activity,
)
from products.signals.backend.trial.direct_reports import (
    custom_report_reservation,
    trial_report_reservation,
    trial_report_reservation_sync,
)
from products.signals.backend.trial.funding import TrialFunding, direct_report_funding
from products.signals.backend.trial.llm_execution import TrialLLMExecution
from products.signals.backend.trial.models import SignalTrialGrant, SignalTrialReportReservation
from products.signals.backend.trial.policy import TrialPolicy, TrialRefused
from products.signals.backend.trial.reports import (
    implementation_requires_trial_opt_in,
    prepare_report_pass,
    report_pass_paid_authorized,
    report_trial_context,
    requires_trial_accounting,
    task_trial_context,
)
from products.tasks.backend.facade.api import get_task_run
from products.tasks.backend.models import Task, TaskRun

from ee.models.license import License


class TestTrialReportExecution(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.flag = patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True)
        self.flag_mock = self.flag.start()
        self.addCleanup(self.flag.stop)
        self.policy = TrialPolicy(self.team)

    def claim(self) -> SignalTrialGrant:
        return self.policy.claim(user_id=self.user.pk)

    def _exhaust_grant(self, grant: SignalTrialGrant) -> None:
        record_llm_spend(
            "exhaust",
            team_id=self.team.id,
            signal_id=str(uuid4()),
            stage="research",
            token_cost_microusd=grant.allowance_microusd + 1,
            trial_grant_id=str(grant.id),
        )
        self.flag_mock.return_value = False

    def _assert_report_continues_with_grant(self, report_id: str, grant: SignalTrialGrant) -> None:
        report = SignalReport.objects.get(id=report_id, team=self.team)
        funding = TrialFunding.from_dict(report.self_driving_funding)
        assert funding is not None and funding.grant_id == grant.id
        task = Task.objects.create(
            team=self.team, title="Accepted implementation", origin_product="signal_report", signal_report=report
        )
        record_report_task(
            team_id=self.team.id, report_id=report_id, task_id=str(task.id), relationship="implementation"
        )
        with task_trial_admission(
            team=self.team, origin="signal_report", report_id=report.id, continue_admitted_pipeline=True
        ):
            run = task.create_run(environment=TaskRun.Environment.CLOUD)
        assert run.state["self_driving_funding"]["grant_id"] == str(grant.id)
        receipt = SignalSpend.objects.for_team(self.team.id).get(task_run_id=run.id)
        assert receipt.trial_grant_id == grant.id and receipt.billing_exempt

    def test_scout_report_keeps_funding_after_exhaustion_and_rollout_off(self) -> None:
        grant = self.claim()
        task = Task.objects.create(team=self.team, title="Scout", origin_product="signals_scout")
        run = task.create_run(environment=TaskRun.Environment.CLOUD)
        self._exhaust_grant(grant)
        with trial_report_reservation_sync(team=self.team, run_id=run.id, emission_key="accepted-scout") as report_id:
            assert isinstance(report_id, UUID)
            result = create_scout_report(
                team_id=self.team.id,
                title="Synthetic scout report",
                summary="A finding from an accepted scout.",
                signals=[
                    ScoutReportSignal(description="Synthetic finding", source_id="fixture", weight=SCOUT_SIGNAL_WEIGHT)
                ],
                attribution=ArtefactAttribution.system(),
                reserved_report_id=report_id,
                emit_signals=False,
            )
        self._assert_report_continues_with_grant(result.report_id, grant)

    def test_custom_report_keeps_funding_across_async_persistence(self) -> None:
        grant = self.claim()

        async def persist() -> str:
            async with custom_report_reservation(
                team=self.team, run_id=None, emission_key="accepted-custom-agent"
            ) as report_id:
                assert isinstance(report_id, UUID)
                await database_sync_to_async(self._exhaust_grant)(grant)
                result = await database_sync_to_async(create_custom_agent_ready_report)(
                    team_id=self.team.id,
                    final_report=CustomAgentFinalReport(
                        title="Synthetic agent report",
                        description="A finding from accepted work.",
                        actionability=ActionabilityAssessment(
                            explanation="A verified fixture",
                            actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
                            already_addressed=False,
                        ),
                        assignees=[],
                        priority=None,
                    ),
                    repo_selection=RepoSelectionResult(repository=None, reason="No repository"),
                    agent_identifier=("test", "synthetic"),
                    reserved_report_id=report_id,
                )
                return result.report_id

        report_id = async_to_sync(persist)()
        self._assert_report_continues_with_grant(report_id, grant)

    @parameterized.expand([(True,), (False,)])
    def test_grouping_settlement_and_report_start_share_lock_order(self, existing_spend: bool) -> None:
        grant = self.claim()
        signal_id = str(uuid4())
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.CANDIDATE, triggering_signal_id=signal_id
        )
        if existing_spend:
            record_llm_spend(
                team_id=self.team.id,
                signal_id=signal_id,
                stage="grouping",
                token_cost_microusd=0,
                trial_grant_id=str(grant.id),
            )
        settling, starting = Event(), Event()

        def settle() -> None:
            close_old_connections()
            try:
                with transaction.atomic():
                    lock_signal_spend(team_id=self.team.id, signal_id=signal_id)
                    settling.set()
                    assert starting.wait(timeout=10)
                    record_llm_spend(
                        team_id=self.team.id,
                        signal_id=signal_id,
                        stage="grouping",
                        token_cost_microusd=123,
                        trial_grant_id=str(grant.id),
                    )
                    complete_signal_pipeline(team_id=self.team.id, signal_id=signal_id, report_id=str(report.id))
            finally:
                close_old_connections()

        def start_lock(*, team_id: int, signal_id: str) -> None:
            starting.set()
            lock_signal_spend(team_id=team_id, signal_id=signal_id)

        with (
            patch("products.signals.backend.temporal.summary.lock_signal_spend", side_effect=start_lock),
            patch("products.signals.backend.temporal.summary._capture_report_event", new_callable=AsyncMock),
            patch(
                "products.signals.backend.temporal.summary.temporalio.activity.info",
                return_value=SimpleNamespace(workflow_run_id="concurrent", activity_id="start"),
            ),
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            pending = pool.submit(settle)
            assert settling.wait(timeout=10)
            async_to_sync(mark_report_in_progress_activity)(
                MarkReportInProgressInput(
                    team_id=self.team.id, report_id=str(report.id), signal_id=signal_id, trial_policy_version=1
                )
            )
            pending.result(timeout=10)
        report.refresh_from_db()
        grant.refresh_from_db()
        assert report.status == SignalReport.Status.IN_PROGRESS
        assert grant.settled_microusd == 123
        assert SignalTrialReportReservation.objects.for_team(self.team.id).filter(report_id=report.id).count() == 1

    @parameterized.expand([(True,), (False,)])
    def test_rollout_controls_report_pass_quota_bypass(self, enabled: bool) -> None:
        self.claim()
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.IN_PROGRESS, triggering_signal_id=uuid4()
        )
        prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="quota-pass")
        self.flag_mock.side_effect = lambda key, *args, **kwargs: enabled if key == "self-driving-ubp" else True
        with patch("products.signals.backend.quota.is_team_limited", return_value=True):
            paused = async_to_sync(check_report_quota_gate_activity)(
                CheckReportQuotaGateInput(team_id=self.team.id, report_id=str(report.id), stage="summary_entry")
            )
        assert paused is (not enabled)
        if not enabled:
            assert TrialLLMExecution.prepare(team_id=self.team.id, gateway=None) is None

    def test_free_signal_does_not_replace_customer_report_trial_funding(self) -> None:
        grant = self.claim()
        signal_id = str(uuid4())
        begin_signal_spend(team_id=self.team.id, signal_id=signal_id, billing_exempt=True)
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY)

        prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="promoted", signal_id=signal_id)

        report.refresh_from_db()
        funding = TrialFunding.from_dict(report.self_driving_funding)
        assert funding is not None and funding.grant_id == grant.id
        assert report.billing_exempt_reason is None

    def test_free_signal_cannot_skip_paid_authorization_for_customer_report(self) -> None:
        grant = self.claim()
        SignalTrialGrant.objects.for_team(self.team.id).filter(id=grant.id).update(exhausted_at=timezone.now())
        signal_id = str(uuid4())
        begin_signal_spend(team_id=self.team.id, signal_id=signal_id, billing_exempt=True)
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY)

        with patch(
            "products.signals.backend.trial.reports.paid_trial_continuation_authorized", return_value=True
        ) as paid:
            assert report_pass_paid_authorized(
                team=self.team, report_id=str(report.id), operation_key="promoted", signal_id=signal_id
            )
        paid.assert_called_once_with(self.team)

    def test_billable_signal_keeps_existing_funding_after_trial_claim(self) -> None:
        signal_id = str(uuid4())
        self.flag_mock.return_value = False
        begin_signal_spend(team_id=self.team.id, signal_id=signal_id)
        self.flag_mock.return_value = True
        self.claim()
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY)

        prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="promoted", signal_id=signal_id)

        report.refresh_from_db()
        funding = TrialFunding.from_dict(report.self_driving_funding)
        assert funding is not None and funding.funding == "existing"

    @parameterized.expand([("exhausted",), ("flag_off",), ("claimed_during_run",)])
    def test_internal_summary_pass_preserves_accepted_workflow_funding(self, change: str) -> None:
        grant = None if change == "claimed_during_run" else self.claim()
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.CANDIDATE, signal_count=1)
        info = SimpleNamespace(workflow_run_id="accepted-workflow", activity_id="first-pass")
        inputs = MarkReportInProgressInput(team_id=self.team.id, report_id=str(report.id), trial_policy_version=1)
        with (
            patch("products.signals.backend.temporal.summary.temporalio.activity.info", return_value=info),
            patch("products.signals.backend.temporal.summary._capture_report_event", new_callable=AsyncMock),
        ):
            async_to_sync(mark_report_in_progress_activity)(inputs)
            report.refresh_from_db()
            accepted = report.self_driving_funding
            if grant is None:
                self.claim()
            else:
                self._exhaust_grant(grant)
                self.flag_mock.return_value = change != "flag_off"
            SignalReport.objects.filter(id=report.id).update(status=SignalReport.Status.CANDIDATE)
            info.activity_id = "second-pass"
            with patch(
                "products.signals.backend.trial.reports.paid_trial_continuation_authorized",
                side_effect=AssertionError("Accepted work must not reauthorize payment"),
            ):
                async_to_sync(mark_report_in_progress_activity)(inputs)
            report.refresh_from_db()
            assert accepted is not None and report.self_driving_funding == accepted
            assert report.status == SignalReport.Status.IN_PROGRESS

    def test_accepted_signal_finishes_report_after_trial_exhaustion(self) -> None:
        grant = self.claim()
        signal_id = str(uuid4())
        record_llm_spend(
            "accepted-signal",
            team_id=self.team.id,
            signal_id=signal_id,
            stage="grouping",
            token_cost_microusd=grant.allowance_microusd + 1,
            trial_grant_id=str(grant.id),
        )
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.CANDIDATE, triggering_signal_id=signal_id, signal_count=1
        )
        with (
            patch(
                "products.signals.backend.trial.billing.TrialBilling.status",
                side_effect=AssertionError("No new payment check"),
            ) as billing_status,
            patch("products.signals.backend.temporal.summary._capture_report_event", new_callable=AsyncMock),
            patch(
                "products.signals.backend.temporal.summary.temporalio.activity.info",
                return_value=SimpleNamespace(workflow_run_id="accepted-signal", activity_id="first-pass"),
            ),
        ):
            from products.signals.backend.quota import self_driving_quota_gate

            assert not self_driving_quota_gate(self.team, signal_id=signal_id).enforced
            assert not async_to_sync(check_report_quota_gate_activity)(
                CheckReportQuotaGateInput(
                    team_id=self.team.id, report_id=str(report.id), stage="summary_entry", signal_id=signal_id
                )
            )
            async_to_sync(mark_report_in_progress_activity)(
                MarkReportInProgressInput(
                    team_id=self.team.id, report_id=str(report.id), signal_id=signal_id, trial_policy_version=1
                )
            )
        billing_status.assert_not_called()
        report.refresh_from_db()
        assert report.self_driving_funding["grant_id"] == str(grant.id)
        SignalReport.objects.filter(id=report.id).update(status=SignalReport.Status.READY)
        with patch("products.signals.backend.trial.reports.paid_trial_continuation_authorized", return_value=False):
            with self.assertRaises(TrialRefused):
                prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="explicit-later-rerun")

    def test_nontrial_receipt_does_not_bypass_current_quota(self) -> None:
        from products.signals.backend.quota import self_driving_quota_gate

        grant = self.claim()
        signal_id = str(uuid4())
        record_llm_spend(team_id=self.team.id, signal_id=signal_id, stage="grouping", token_cost_microusd=1)
        self._exhaust_grant(grant)
        self.flag_mock.return_value = True
        with patch("products.signals.backend.trial.billing.paid_trial_continuation_authorized", return_value=False):
            assert self_driving_quota_gate(self.team, signal_id=signal_id).enforced

    def test_cancellation_during_scout_reservation_releases_slot(self) -> None:
        self._assert_cancelled_reservation_is_released(custom=False)

    def test_cancellation_during_custom_reservation_releases_slot(self) -> None:
        self._assert_cancelled_reservation_is_released(custom=True)

    def _assert_cancelled_reservation_is_released(self, *, custom: bool) -> None:
        from products.signals.backend.trial import direct_reports

        grant = self.claim()
        run = None
        if not custom:
            task = Task.objects.create(team=self.team, title="Scout", origin_product="signals_scout")
            run = task.create_run(environment=TaskRun.Environment.CLOUD)
        acquired, release = Event(), Event()
        name = "_reserve_custom_report" if custom else "reserve_report"
        original = getattr(direct_reports, name)
        body_entered = False

        def reserve(*args, **kwargs):
            result = original(*args, **kwargs)
            acquired.set()
            assert release.wait(timeout=10)
            return result

        async def exercise() -> None:
            async def emit() -> None:
                nonlocal body_entered
                factory = custom_report_reservation if custom else trial_report_reservation
                async with factory(team=self.team, run_id=run.id if run else None, emission_key="cancel-acquisition"):
                    body_entered = True

            attempt = asyncio.create_task(emit())
            try:
                assert await asyncio.to_thread(acquired.wait, 10)
                attempt.cancel()
                await asyncio.sleep(0)
                attempt.cancel()
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError):
                await attempt

        with patch.object(direct_reports, name, side_effect=reserve):
            async_to_sync(exercise)()
        assert not body_entered
        slot = SignalTrialReportReservation.objects.for_team(self.team.id).get(grant=grant)
        assert slot.active_attempts == 0 and slot.status == SignalTrialReportReservation.Status.RELEASED

    @parameterized.expand([(reason,) for reason in SignalReport.BillingExemptReason.values])
    def test_system_report_does_not_consume_exhausted_trial(self, reason: str) -> None:
        grant = self.claim()
        self._exhaust_grant(grant)
        self.flag_mock.return_value = True
        report = SignalReport.objects.create(team=self.team, billing_exempt_reason=reason)
        assert not async_to_sync(check_report_quota_gate_activity)(
            CheckReportQuotaGateInput(team_id=self.team.id, report_id=str(report.id), stage="summary_entry")
        )
        assert not report_pass_paid_authorized(team=self.team, report_id=str(report.id), operation_key="free-pass")
        prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="free-pass")
        assert not implementation_requires_trial_opt_in(self.team.id, str(report.id))
        task = Task.objects.create(
            team=self.team, title="System repair", origin_product="signal_report", signal_report=report
        )
        record_report_task(
            team_id=self.team.id, report_id=str(report.id), task_id=str(task.id), relationship="implementation"
        )
        with task_trial_admission(
            team=self.team, origin="signal_report", report_id=report.id, continue_admitted_pipeline=True
        ):
            run = task.create_run(environment=TaskRun.Environment.CLOUD)
        assert run.state["self_driving_funding"]["funding"] == "existing"
        receipt = SignalSpend.objects.for_team(self.team.id).get(task_run_id=run.id)
        assert receipt.trial_grant_id is None and receipt.billing_exempt
        assert not SignalTrialReportReservation.objects.for_team(self.team.id).filter(report_id=report.id).exists()
        grant.refresh_from_db()
        assert grant.settled_microusd == grant.allowance_microusd + 1

    def test_free_generation_keeps_cost_outside_exhausted_trial(self) -> None:
        grant = self.claim()
        self._exhaust_grant(grant)
        self.flag_mock.return_value = True
        signal_id = str(uuid4())
        generation = AsyncMock(return_value=SimpleNamespace(_request_id="free-system-generation"))
        with patch(
            "products.signals.backend.llm_spend._wait_for_gateway_cost",
            new=AsyncMock(return_value=GatewayRequestCost(model="model", provider="provider", cost_microusd=123)),
        ):
            async_to_sync(generate_with_spend)(
                generation(),
                gateway=AIGatewayConfig(url="https://gateway.example.com/v1", api_key="test-key"),
                team_id=self.team.id,
                signal_id=signal_id,
                stage="summarization",
                billing_exempt=True,
            )
        receipt = SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id)
        assert receipt.trial_grant_id is None and receipt.billing_exempt and receipt.spend > 0
        assert not requires_trial_accounting(self.team.id, signal_id)
        grant.refresh_from_db()
        assert grant.settled_microusd == grant.allowance_microusd + 1
        assert grant.incomplete_sources == 0

    def test_failed_generation_registration_prevents_provider_request(self) -> None:
        self.claim()
        generation = AsyncMock()
        with patch("products.signals.backend.spend.save_trial_spend", side_effect=RuntimeError("write failed")):
            with self.assertRaisesMessage(RuntimeError, "write failed"):
                async_to_sync(generate_with_spend)(
                    generation(),
                    gateway=AIGatewayConfig(url="https://gateway.example.com/v1", api_key="test-key"),
                    team_id=self.team.id,
                    signal_id=str(uuid4()),
                    stage="summarization",
                )
        generation.assert_not_awaited()

    @parameterized.expand([(True,), (False,)])
    def test_generation_preserves_existing_signal_funding(self, trial: bool) -> None:
        grant = self.claim() if trial else None
        signal_id = str(uuid4())
        record_llm_spend(
            team_id=self.team.id,
            signal_id=signal_id,
            stage="grouping",
            token_cost_microusd=101,
            trial_grant_id=str(grant.id) if grant else None,
        )
        if trial:
            self.flag_mock.return_value = False
        else:
            self.claim()
        assert requires_trial_accounting(self.team.id, signal_id) is trial
        execution = TrialLLMExecution.prepare(
            team_id=self.team.id,
            gateway=AIGatewayConfig(url="https://gateway.example.com/v1", api_key="test-key"),
            signal_id=signal_id,
        )
        if trial:
            assert execution is not None and grant is not None
            assert execution.funding.grant_id == grant.id
        else:
            assert execution is None

    @parameterized.expand([(True,), (False,)])
    def test_http_failure_preserves_gateway_receipt_and_charges_failed_attempt(self, settled: bool) -> None:
        grant = self.claim()
        signal_id = str(uuid4())
        error = APIStatusError(
            "provider error",
            response=httpx.Response(
                500,
                request=httpx.Request("POST", "https://gateway.example.com/v1/messages"),
                headers={"request-id": "failed-request"},
            ),
            body=None,
        )
        generation = AsyncMock(side_effect=error)
        with patch(
            "products.signals.backend.llm_spend._wait_for_gateway_cost",
            new=AsyncMock(
                return_value=GatewayRequestCost(model="model", provider="provider", cost_microusd=123),
                side_effect=None if settled else TimeoutError,
            ),
        ):
            with self.assertRaises(APIStatusError):
                async_to_sync(generate_with_spend)(
                    generation(),
                    gateway=AIGatewayConfig(url="https://gateway.example.com/v1", api_key="test-key"),
                    team_id=self.team.id,
                    signal_id=signal_id,
                    stage="summarization",
                )
        grant.refresh_from_db()
        assert grant.incomplete_sources == (0 if settled else 1)
        assert grant.settled_microusd == (123 if settled else 0)
        spend = SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id)
        assert list(spend.pending_requests.values()) == (
            [] if settled else [{"stage": "summarization", "request_id": "failed-request"}]
        )

    @parameterized.expand([(True,), (False,)])
    def test_report_pass_funding_survives_retry_exhaustion_and_paid_handoff(self, enabled: bool) -> None:
        grant = self.claim()
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.IN_PROGRESS, triggering_signal_id=uuid4()
        )
        prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="first-pass")
        task = Task.objects.create(
            team=self.team,
            title="Research",
            origin_product="signal_report",
            signal_report_id=report.id,
            internal=True,
        )
        run = task.create_run(environment=TaskRun.Environment.CLOUD, extra_state={"ai_stage": "research"})
        run.status = TaskRun.Status.COMPLETED
        run.save(update_fields=["status"])
        record_llm_spend(
            "exhaust",
            team_id=self.team.id,
            signal_id=str(uuid4()),
            stage="research",
            token_cost_microusd=10_000_000,
            trial_grant_id=str(grant.id),
        )
        prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="first-pass")
        with self.assertRaisesMessage(TrialRefused, "report_pass_in_progress"):
            prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="overlapping-pass")
        context = report_trial_context.set((self.team.id, str(report.id)))
        try:
            finalization = TrialLLMExecution.prepare(
                team_id=self.team.id, gateway=AIGatewayConfig(url="https://gateway.example.com/v1", api_key="test-key")
            )
            assert finalization is not None and finalization.funding.grant_id == grant.id
            continued = task.create_run(environment=TaskRun.Environment.CLOUD, extra_state={"ai_stage": "research"})
            assert continued.state["self_driving_funding"]["grant_id"] == str(grant.id)
        finally:
            report_trial_context.reset(context)
        report.status = SignalReport.Status.READY
        report.save(update_fields=["status"])
        assert SignalTrialReportReservation.objects.for_team(self.team.id).get(report_id=report.id).status == "consumed"
        self.flag_mock.return_value = enabled
        prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="second-pass", paid_authorized=True)
        SignalReport.objects.filter(id=report.id, team_id=self.team.id).update(status=SignalReport.Status.IN_PROGRESS)
        context = report_trial_context.set((self.team.id, str(report.id)))
        try:
            paid_run = task.create_run(environment=TaskRun.Environment.CLOUD, extra_state={"ai_stage": "research"})
        finally:
            report_trial_context.reset(context)
        assert paid_run.state["self_driving_funding"]["funding"] == ("paid" if enabled else "existing")
        assert run.state["self_driving_funding"]["funding"] == "trial"

    def test_paid_direct_retry_does_not_consume_released_trial_slot(self) -> None:
        grant = self.claim()
        task = Task.objects.create(team=self.team, title="Scout", origin_product="signals_scout")
        trial_run = task.create_run(environment=TaskRun.Environment.CLOUD)
        with trial_report_reservation_sync(
            team=self.team, run_id=trial_run.id, emission_key="same-report"
        ) as report_id:
            assert report_id is not None
        slot = SignalTrialReportReservation.objects.for_team(self.team.id).get(report_id=report_id)
        assert slot.status == "released"
        record_llm_spend(
            "exhaust",
            team_id=self.team.id,
            signal_id=str(uuid4()),
            stage="scout",
            token_cost_microusd=10_000_000,
            trial_grant_id=str(grant.id),
        )
        with patch("products.signals.backend.facade.trial.paid_trial_continuation_authorized", return_value=True):
            paid_run = task.create_run(environment=TaskRun.Environment.CLOUD)
        with trial_report_reservation_sync(team=self.team, run_id=paid_run.id, emission_key="same-report"):
            report = SignalReport.objects.create(id=report_id, team=self.team, status=SignalReport.Status.READY)
        slot.refresh_from_db()
        assert report.status == SignalReport.Status.READY
        assert slot.status == "released"

    @parameterized.expand([(False, RuntimeError), (True, RuntimeError), (True, asyncio.CancelledError)])
    def test_direct_report_setup_failure_releases_reservation(
        self, asynchronous: bool, failure: type[BaseException]
    ) -> None:
        grant = self.claim()
        task = Task.objects.create(team=self.team, title="Scout", origin_product="signals_scout")
        run = task.create_run(environment=TaskRun.Environment.CLOUD)
        run_dto = get_task_run(run.id, team_id=self.team.id)
        outer_task = (self.team.id, uuid4())
        outer_funding = (self.team.id, TrialFunding(funding="existing"))

        async def emit() -> None:
            async with trial_report_reservation(team=self.team, run_id=run.id, emission_key="setup-failure"):
                self.fail("Report execution must not start after setup fails")

        task_token = task_trial_context.set(outer_task)
        funding_token = direct_report_funding.set(outer_funding)
        try:
            with (
                patch("products.signals.backend.trial.reports.get_task_run", side_effect=[run_dto, failure()]),
                self.assertRaises(failure),
            ):
                if asynchronous:
                    async_to_sync(emit)()
                else:
                    with trial_report_reservation_sync(team=self.team, run_id=run.id, emission_key="setup-failure"):
                        self.fail("Report execution must not start after setup fails")
            assert task_trial_context.get() == outer_task
            assert direct_report_funding.get() == outer_funding
        finally:
            task_trial_context.reset(task_token)
            direct_report_funding.reset(funding_token)
        slot = SignalTrialReportReservation.objects.for_team(self.team.id).get(grant=grant)
        assert slot.status == "released"
        assert slot.active_attempts == 0

    @parameterized.expand(
        [
            (status, count)
            for status in (SignalReport.Status.SUPPRESSED, SignalReport.Status.CANDIDATE)
            for count in (2, None)
        ]
    )
    def test_report_start_admission_commits_with_transition(self, status: str, count: int | None) -> None:
        self.claim()
        report = SignalReport.objects.create(team=self.team, status=status, signal_count=7)
        input = MarkReportInProgressInput(
            team_id=self.team.id, report_id=str(report.id), signal_count=count, trial_policy_version=1
        )
        with (
            patch("products.signals.backend.temporal.summary._capture_report_event", new_callable=AsyncMock) as capture,
            patch(
                "products.signals.backend.temporal.summary.temporalio.activity.info",
                return_value=SimpleNamespace(workflow_run_id="report-run", activity_id="start"),
            ),
        ):
            if status == SignalReport.Status.SUPPRESSED:
                with self.assertRaises(InvalidStatusTransition):
                    async_to_sync(mark_report_in_progress_activity)(input)
                report.refresh_from_db()
                assert report.status == status
                assert report.self_driving_funding is None
                assert (
                    not SignalTrialReportReservation.objects.for_team(self.team.id).filter(report_id=report.id).exists()
                )
            else:
                async_to_sync(mark_report_in_progress_activity)(input)
                async_to_sync(mark_report_in_progress_activity)(input)
                report.refresh_from_db()
                assert report.status == SignalReport.Status.IN_PROGRESS
                assert report.run_count == 1
                assert report.researching_signal_count == (7 if count is None else count)
                assert capture.await_count == 1
                assert capture.call_args.kwargs["signal_count"] == report.researching_signal_count
                assert report.self_driving_funding is not None
                assert report.self_driving_funding["report_pass_key"] == "report-pass:report-run"
                assert (
                    SignalTrialReportReservation.objects.for_team(self.team.id).filter(report_id=report.id).count() == 1
                )

    @parameterized.expand([(True,), (False,)])
    def test_report_placeholder_preserves_the_admitted_funding(self, existing_nontrial: bool) -> None:
        signal_id = str(uuid4())
        if existing_nontrial:
            record_llm_spend(team_id=self.team.id, signal_id=signal_id, stage="grouping", token_cost_microusd=123)
        grant = self.claim()
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.CANDIDATE, triggering_signal_id=signal_id
        )
        prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="placeholder")
        begin_report_spend(team_id=self.team.id, report_id=str(report.id), signal_id=signal_id)
        token = report_trial_context.set((self.team.id, str(report.id)))
        try:
            execution = TrialLLMExecution.prepare(
                team_id=self.team.id,
                signal_id=signal_id,
                gateway=AIGatewayConfig(url="https://gateway.example.com/v1", api_key="test-key"),
            )
        finally:
            report_trial_context.reset(token)
        if existing_nontrial:
            assert execution is None
        else:
            assert execution is not None and execution.funding.grant_id == grant.id
        spend = SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id)
        assert spend.trial_grant_id == (None if existing_nontrial else grant.id)

    def test_billing_wait_does_not_block_database_executor(self) -> None:
        grant = self.claim()
        grant.exhausted_at = timezone.now()
        grant.exhaustion_reason = "cost_limit"
        grant.save(update_fields=["exhausted_at", "exhaustion_reason"])

        async def check() -> None:
            started = asyncio.Event()
            release = Event()
            loop = asyncio.get_running_loop()

            def get(*args: object, **kwargs: object) -> None:
                assert not connection.in_atomic_block
                loop.call_soon_threadsafe(started.set)
                if not release.wait(timeout=10):
                    raise AssertionError("Billing request was not released")
                raise ReadTimeout()

            with (
                patch("ee.billing.billing_manager.http_session.get", side_effect=get),
                patch(
                    "products.signals.backend.trial.billing.get_cached_instance_license",
                    return_value=License(key="trial-test::synthetic-billing-secret-for-tests"),
                ),
            ):
                decision = asyncio.create_task(
                    run_model_decision(
                        team_id=self.team.id,
                        stage="actionability",
                        primary_model="example-model",
                        mode_override="system-one-shadow",
                        source_id="example-source",
                        source_product="example-product",
                        state={},
                        prompt=bundled_prompt("signals-actionability-test", "policy", "Is it actionable?", 0.95),
                        traditional=AsyncMock(return_value=True),
                        verdict=lambda result: result,
                        system_one_result=lambda result, category: result,
                    )
                )
                try:
                    await asyncio.wait_for(started.wait(), timeout=5)
                    assert (
                        await asyncio.wait_for(
                            database_sync_to_async(lambda: SignalReport.objects.filter(team_id=self.team.id).count())(),
                            timeout=5,
                        )
                        == 0
                    )
                finally:
                    release.set()
                    assert await decision

        async_to_sync(check)()
