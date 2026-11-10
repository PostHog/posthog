import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from types import SimpleNamespace
from uuid import UUID, uuid4

from posthog.test.base import NonAtomicBaseTest
from unittest.mock import AsyncMock, patch

from django.db import close_old_connections, connection, transaction
from django.utils import timezone

import httpx
from anthropic import APIStatusError
from anthropic.types import Message, Usage
from asgiref.sync import async_to_sync
from parameterized import parameterized
from requests.exceptions import ReadTimeout

from posthog.llm.gateway_client import AIGatewayConfig
from posthog.llm.gateway_usage import GatewayRequestCost
from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.signals.backend.custom_agent.persistence import create_custom_agent_ready_report
from products.signals.backend.custom_agent.schemas import CustomAgentFinalReport
from products.signals.backend.facade.trial import task_trial_admission
from products.signals.backend.free_trial import self_driving_free_trial_enabled
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
    complete_task_spend,
    finish_report_spend,
    lock_signal_spend,
    record_llm_spend,
)
from products.signals.backend.spend_billing import get_signals_spend_billing_credits_by_team
from products.signals.backend.system_one_decision import run_model_decision
from products.signals.backend.system_one_prompts import bundled_prompt
from products.signals.backend.task_run_artefacts import record_report_task
from products.signals.backend.temporal.summary import (
    CheckReportQuotaGateInput,
    MarkReportInProgressInput,
    check_report_quota_gate_activity,
    mark_report_in_progress_activity,
    publish_report_spend_activity,
)
from products.signals.backend.temporal.types import SignalReportSummaryWorkflowInputs
from products.signals.backend.trial.direct_reports import funded_report, funded_report_sync
from products.signals.backend.trial.funding import TrialFunding, direct_report_funding
from products.signals.backend.trial.llm_execution import TrialLLMExecution
from products.signals.backend.trial.models import SignalTrialGrant
from products.signals.backend.trial.policy import TrialPolicy, TrialRefused
from products.signals.backend.trial.reports import (
    implementation_requires_trial_opt_in,
    prepare_report_pass,
    report_pass_admission,
    report_trial_context,
    requires_trial_accounting,
    task_trial_context,
)
from products.signals.backend.trial.signals import admit_signal
from products.signals.backend.usage import trial_usage
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
        with funded_report_sync(team=self.team, run_id=run.id, emission_key="accepted-scout") as report_id:
            assert isinstance(report_id, UUID)
            result = create_scout_report(
                team_id=self.team.id,
                title="Synthetic scout report",
                summary="A finding from an accepted scout.",
                signals=[
                    ScoutReportSignal(description="Synthetic finding", source_id="fixture", weight=SCOUT_SIGNAL_WEIGHT)
                ],
                attribution=ArtefactAttribution.system(),
                funded_report_id=report_id,
                emit_signals=False,
            )
        self._assert_report_continues_with_grant(result.report_id, grant)

    def test_custom_report_keeps_funding_across_async_persistence(self) -> None:
        grant = self.claim()

        async def persist() -> str:
            async with funded_report(team=self.team, run_id=None, emission_key="accepted-custom-agent") as report_id:
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
                    funded_report_id=report_id,
                )
                return result.report_id

        report_id = async_to_sync(persist)()
        self._assert_report_continues_with_grant(report_id, grant)

    def test_funded_report_identity_is_scoped_to_the_environment(self) -> None:
        self.claim()
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child")
        report_ids: list[str] = []
        for team in (self.team, child):
            with funded_report_sync(team=team, run_id=None, emission_key="same-emission") as report_id:
                result = create_scout_report(
                    team_id=team.id,
                    title="Synthetic scout report",
                    summary="An independent environment finding.",
                    signals=[ScoutReportSignal(description="Synthetic finding", source_id="fixture", weight=1)],
                    attribution=ArtefactAttribution.system(),
                    funded_report_id=report_id,
                    emit_signals=False,
                )
                report_ids.append(result.report_id)
        assert report_ids[0] != report_ids[1]
        for team, expected in zip((self.team, child), report_ids):
            with funded_report_sync(team=team, run_id=None, emission_key="same-emission") as report_id:
                assert str(report_id) == expected
        assert set(SignalReport.objects.filter(id__in=report_ids).values_list("team_id", flat=True)) == {
            self.team.id,
            child.id,
        }

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
        assert trial_usage(grant).spend_microusd == 123

    @parameterized.expand([(True,), (False,)])
    def test_existing_report_is_not_rechecked_when_rollout_changes(self, enabled: bool) -> None:
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
        assert paused is False
        if not enabled:
            assert TrialLLMExecution.prepare(team_id=self.team.id, gateway=None) is None

    @parameterized.expand([(restricted, signal) for restricted in (False, True) for signal in (False, True)])
    def test_report_keeps_implementation_eligibility_when_legacy_flag_changes(
        self, restricted: bool, signal: bool
    ) -> None:
        self.flag_mock.side_effect = lambda key, *args, **kwargs: (
            restricted if key == "self-driving-free-trial" else False
        )
        signal_id = str(uuid4()) if signal else None
        if signal_id:
            begin_signal_spend(team_id=self.team.id, signal_id=signal_id)
        report = SignalReport.objects.create(team=self.team)
        prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="accepted", signal_id=signal_id)
        self.flag_mock.side_effect = lambda key, *args, **kwargs: (
            not restricted if key == "self-driving-free-trial" else False
        )
        assert self_driving_free_trial_enabled(self.team, admitted_report_id=str(report.id)) is restricted

    @parameterized.expand([(False, False), (True, False), (False, True)])
    def test_free_signal_does_not_replace_customer_report_trial_funding(
        self, previous_pass: bool, exhausted: bool
    ) -> None:
        grant = self.claim()
        signal_id = str(uuid4())
        begin_signal_spend(team_id=self.team.id, signal_id=signal_id, billing_exempt=True)
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY)

        if previous_pass:
            prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="original")
        if exhausted:
            self._exhaust_grant(grant)
            self.flag_mock.return_value = True
        with patch(
            "products.signals.backend.trial.billing.paid_trial_continuation_authorized",
            side_effect=AssertionError("Accepted work must not request new payment authorization"),
        ):
            prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="promoted", signal_id=signal_id)

        report.refresh_from_db()
        funding = TrialFunding.from_dict(report.self_driving_funding)
        assert funding is not None and funding.grant_id == grant.id
        assert report.billing_exempt_reason is None

    @parameterized.expand([("active",), ("exhausted",), ("flag_off",)])
    def test_operator_pipeline_keeps_customer_spend_and_trial_balance_unchanged(self, state: str) -> None:
        grant = self.claim()
        signal_id = str(uuid4())
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, triggering_signal_id=signal_id, signal_count=1
        )
        record_llm_spend(
            "original",
            team_id=self.team.id,
            signal_id=signal_id,
            stage="research",
            token_cost_microusd=100_000,
            trial_grant_id=str(grant.id),
        )
        finish_report_spend(team_id=self.team.id, report_id=str(report.id), signal_id=signal_id)
        original = SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id)
        original_snapshot = (original.spend, original.finalized_at, original.trial_grant_id)
        if state == "exhausted":
            self._exhaust_grant(grant)
        self.flag_mock.return_value = state != "flag_off"
        grant.refresh_from_db()
        grant_snapshot = (
            trial_usage(grant).spend_microusd,
            SignalSpend.objects.unscoped().filter(trial_grant=grant, accounting_pending=True).count(),
        )
        self.organization.usage = {"signals_spend_credits": {"billing_start_date": "2020-01-01"}}
        self.organization.save(update_fields=["usage"])
        SignalReport.objects.filter(id=report.id).update(status=SignalReport.Status.CANDIDATE)
        info = SimpleNamespace(workflow_run_id="operator-workflow", activity_id="mark")
        with (
            patch("products.signals.backend.temporal.summary.temporalio.activity.info", return_value=info),
            patch("products.signals.backend.temporal.summary._capture_report_event", new_callable=AsyncMock),
        ):
            async_to_sync(mark_report_in_progress_activity)(
                MarkReportInProgressInput(
                    team_id=self.team.id,
                    report_id=str(report.id),
                    signal_id=signal_id,
                    operator_rerun=True,
                )
            )
        token = report_trial_context.set((self.team.id, str(report.id)))
        runs: list[TaskRun] = []
        try:
            assert not requires_trial_accounting(self.team.id, signal_id)
            response = Message(
                id="operator-generation",
                content=[],
                model="model",
                role="assistant",
                type="message",
                usage=Usage(input_tokens=0, output_tokens=0),
            )
            result = async_to_sync(generate_with_spend)(
                AsyncMock(return_value=response)(),
                gateway=None,
                team_id=self.team.id,
                signal_id=signal_id,
                stage="safety_judge",
            )
            assert result.response is response and result.spend is None
            for stage in ("research", "implementation"):
                task = Task.objects.create(
                    team=self.team,
                    title="Operator repair",
                    origin_product="signal_report",
                    signal_report=report,
                    internal=True,
                )
                run = task.create_run(
                    environment=TaskRun.Environment.CLOUD,
                    extra_state={"ai_stage": stage},
                    spend_signal_id=signal_id,
                )
                assert run.state["self_driving_funding"]["funding"] == "operator"
                runs.append(run)
        finally:
            report_trial_context.reset(token)

        SignalReport.objects.filter(id=report.id).update(status=SignalReport.Status.READY)
        with patch("products.signals.backend.trial.billing.paid_trial_continuation_authorized", return_value=True):
            prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="automatic-refresh")
        report.refresh_from_db()
        assert report.self_driving_funding is not None
        assert (
            report.self_driving_funding["funding"]
            == {
                "active": "trial",
                "exhausted": "paid",
                "flag_off": "existing",
            }[state]
        )
        assert report.billing_exempt_reason is None
        for run in runs:
            TaskRun.update_state_atomic(
                run.id,
                updates={
                    "token_cost": {"model": {"provider": {"cost_microusd": 100_000, "request_ids": ["task-call"]}}},
                },
            )
            TaskRun.objects.filter(id=run.id).update(status=TaskRun.Status.COMPLETED)
            with patch("products.signals.backend.spend.submit_signal_metadata_updates", new_callable=AsyncMock):
                complete_task_spend(team_id=self.team.id, run_id=str(run.id))
            receipt = SignalSpend.objects.for_team(self.team.id).get(task_run_id=run.id)
            assert receipt.spend == 14
            assert receipt.billing_exempt and receipt.trial_grant_id is None and receipt.usage_billing
        with patch("products.signals.backend.temporal.summary.submit_signal_metadata_updates", new_callable=AsyncMock):
            async_to_sync(publish_report_spend_activity)(
                SignalReportSummaryWorkflowInputs(
                    team_id=self.team.id,
                    report_id=str(report.id),
                    signal_id=signal_id,
                    operator_rerun=True,
                )
            )
        original.refresh_from_db()
        assert (original.spend, original.finalized_at, original.trial_grant_id) == original_snapshot
        grant.refresh_from_db()
        assert (
            trial_usage(grant).spend_microusd,
            SignalSpend.objects.unscoped().filter(trial_grant=grant, accounting_pending=True).count(),
        ) == grant_snapshot
        now = timezone.now()
        assert get_signals_spend_billing_credits_by_team(now - timedelta(days=1), now + timedelta(days=1)) == []

    def test_operator_pipeline_finalizes_new_signals_without_changing_its_original_receipt(self) -> None:
        grant = self.claim()
        original_id, pending_id = uuid4(), uuid4()
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=original_id)
        record_llm_spend(
            "original",
            team_id=self.team.id,
            signal_id=str(original_id),
            stage="research",
            token_cost_microusd=100_000,
            trial_grant_id=str(grant.id),
        )
        finish_report_spend(team_id=self.team.id, report_id=str(report.id), signal_id=str(original_id))
        original = SignalSpend.objects.for_team(self.team.id).get(signal_id=original_id)
        original_finalized = original.finalized_at
        prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="operator", operator_rerun=True)
        SignalReport.objects.filter(id=report.id).update(pending_triggering_signal_id=pending_id)
        record_llm_spend(
            "organic-signal",
            team_id=self.team.id,
            signal_id=str(pending_id),
            stage="research",
            token_cost_microusd=100_000,
            trial_grant_id=str(grant.id),
        )
        with patch("products.signals.backend.temporal.summary.submit_signal_metadata_updates", new_callable=AsyncMock):
            async_to_sync(publish_report_spend_activity)(
                SignalReportSummaryWorkflowInputs(
                    team_id=self.team.id,
                    report_id=str(report.id),
                    signal_id=str(original_id),
                    operator_rerun=True,
                )
            )
        original.refresh_from_db()
        assert original.finalized_at == original_finalized
        assert original.spend == 10 and original.trial_grant_id == grant.id
        assert SignalSpend.objects.for_team(self.team.id).get(signal_id=pending_id).finalized_at is not None

    def test_accepted_free_signal_keeps_report_funding_after_trial_exhaustion(self) -> None:
        grant = self.claim()
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY)
        prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="original")
        self._exhaust_grant(grant)
        self.flag_mock.return_value = True
        signal_id = str(uuid4())
        admit_signal(team=self.team, signal_id=signal_id, billing_exempt=True)
        with patch(
            "products.signals.backend.trial.billing.paid_trial_continuation_authorized",
            side_effect=AssertionError("Accepted work must not request new payment authorization"),
        ):
            prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="promoted", signal_id=signal_id)
        report.refresh_from_db()
        assert report.self_driving_funding is not None
        assert report.self_driving_funding["grant_id"] == str(grant.id)
        self._assert_report_continues_with_grant(str(report.id), grant)

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
                "products.signals.backend.trial.billing.paid_trial_continuation_authorized",
                side_effect=AssertionError("Accepted work must not reauthorize payment"),
            ):
                async_to_sync(mark_report_in_progress_activity)(inputs)
            report.refresh_from_db()
            assert accepted is not None and report.self_driving_funding == accepted
            assert report.status == SignalReport.Status.IN_PROGRESS

    @parameterized.expand([(False,), (True,)])
    def test_accepted_signal_finishes_report_after_trial_exhaustion(self, admitted_at_emission: bool) -> None:
        grant = self.claim()
        signal_id = str(uuid4())
        if admitted_at_emission:
            admit_signal(team=self.team, signal_id=signal_id)
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
        assert report.self_driving_funding is not None
        assert report.self_driving_funding["grant_id"] == str(grant.id)
        SignalReport.objects.filter(id=report.id).update(status=SignalReport.Status.READY)
        finish_report_spend(team_id=self.team.id, report_id=str(report.id), signal_id=signal_id)
        with patch("products.signals.backend.trial.billing.paid_trial_continuation_authorized", return_value=False):
            with self.assertRaises(TrialRefused):
                prepare_report_pass(
                    team=self.team, report_id=str(report.id), operation_key="explicit-later-rerun", signal_id=signal_id
                )

    def test_older_report_can_implement_after_the_project_claims_a_trial(self) -> None:
        report = SignalReport.objects.create(team=self.team)
        self.claim()
        self.flag_mock.return_value = True
        assert not implementation_requires_trial_opt_in(self.team.id, str(report.id))
        assert not self_driving_free_trial_enabled(self.team, admitted_report_id=str(report.id))

    def test_accepted_nontrial_signal_continues_without_unpausing_new_work(self) -> None:
        from products.signals.backend.quota import self_driving_quota_gate

        grant = self.claim()
        signal_id = str(uuid4())
        record_llm_spend(team_id=self.team.id, signal_id=signal_id, stage="grouping", token_cost_microusd=1)
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=signal_id)
        self._exhaust_grant(grant)
        self.flag_mock.return_value = True
        with patch("products.signals.backend.trial.billing.paid_trial_continuation_authorized", return_value=False):
            assert self_driving_quota_gate(self.team).enforced
            prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="accepted", signal_id=signal_id)
        report.refresh_from_db()
        assert report.self_driving_funding is not None
        assert report.self_driving_funding["funding"] == "existing"

    @parameterized.expand([(reason,) for reason in SignalReport.BillingExemptReason.values])
    def test_system_report_does_not_consume_exhausted_trial(self, reason: str) -> None:
        grant = self.claim()
        self._exhaust_grant(grant)
        self.flag_mock.return_value = True
        report = SignalReport.objects.create(team=self.team, billing_exempt_reason=reason)
        assert not async_to_sync(check_report_quota_gate_activity)(
            CheckReportQuotaGateInput(team_id=self.team.id, report_id=str(report.id), stage="summary_entry")
        )
        assert not report_pass_admission(
            team=self.team, report_id=str(report.id), operation_key="free-pass"
        ).gate.enforced
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
        grant.refresh_from_db()
        assert trial_usage(grant).spend_microusd == grant.allowance_microusd + 1

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
        assert trial_usage(grant).spend_microusd == grant.allowance_microusd + 1
        assert SignalSpend.objects.unscoped().filter(trial_grant=grant, accounting_pending=True).count() == 0

    @parameterized.expand([(False,), (True,)])
    def test_standalone_trial_generation_finalizes_when_its_cost_settles(self, delayed: bool) -> None:
        grant = self.claim()
        generation = AsyncMock(return_value=SimpleNamespace(_request_id="standalone-generation"))
        with patch(
            "products.signals.backend.llm_spend.fetch_gateway_cost",
            new=AsyncMock(
                side_effect=TimeoutError if delayed else None,
                return_value=GatewayRequestCost(model="model", provider="provider", cost_microusd=123),
            ),
        ):
            async_to_sync(generate_with_spend)(
                generation(),
                gateway=AIGatewayConfig(url="https://gateway.example.com/v1", api_key="test-key"),
                team_id=self.team.id,
                signal_id=None,
                stage="safety_judge",
            )
        receipt = SignalSpend.objects.for_team(self.team.id).get(trial_grant=grant)
        assert receipt.finalization_requested_at is not None
        assert (receipt.finalized_at is None) is delayed
        if delayed:
            record_llm_spend(
                "standalone-generation",
                team_id=self.team.id,
                signal_id=str(receipt.signal_id),
                source_id=next(iter(receipt.pending_requests)),
                stage="safety_judge",
                token_cost_microusd=123,
            )
            receipt.refresh_from_db()
        assert receipt.finalized_at is not None
        assert not receipt.accounting_pending
        assert trial_usage(grant).settled_microusd == 123
        generation.assert_awaited_once()

    def test_failed_generation_registration_prevents_provider_request(self) -> None:
        self.claim()
        generation = AsyncMock()
        with patch("products.signals.backend.models.SignalSpend.save", side_effect=RuntimeError("write failed")):
            with self.assertRaisesMessage(RuntimeError, "write failed"):
                async_to_sync(generate_with_spend)(
                    generation(),
                    gateway=AIGatewayConfig(url="https://gateway.example.com/v1", api_key="test-key"),
                    team_id=self.team.id,
                    signal_id=str(uuid4()),
                    stage="summarization",
                )
        generation.assert_not_awaited()

    @parameterized.expand([(trial, admitted) for trial in (True, False) for admitted in (True, False)])
    def test_generation_preserves_existing_signal_funding(self, trial: bool, admitted: bool) -> None:
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
        if admitted:
            admit_signal(team=self.team, signal_id=signal_id)
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
        assert SignalSpend.objects.unscoped().filter(trial_grant=grant, accounting_pending=True).count() == (
            0 if settled else 1
        )
        assert trial_usage(grant).spend_microusd == (123 if settled else 0)
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
        report.refresh_from_db()
        report.save(
            update_fields=report.transition_to(
                SignalReport.Status.READY, title="Completed report", summary="Research is complete."
            )
        )
        assert trial_usage(grant).reports == 1
        self.flag_mock.return_value = enabled
        with patch("products.signals.backend.trial.billing.paid_trial_continuation_authorized", return_value=True):
            prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="second-pass")
        SignalReport.objects.filter(id=report.id, team_id=self.team.id).update(status=SignalReport.Status.IN_PROGRESS)
        context = report_trial_context.set((self.team.id, str(report.id)))
        try:
            paid_run = task.create_run(environment=TaskRun.Environment.CLOUD, extra_state={"ai_stage": "research"})
        finally:
            report_trial_context.reset(context)
        assert paid_run.state["self_driving_funding"]["funding"] == ("paid" if enabled else "existing")
        assert run.state["self_driving_funding"]["funding"] == "trial"

    @parameterized.expand([(False, RuntimeError), (True, RuntimeError), (True, asyncio.CancelledError)])
    def test_direct_report_context_restored_after_failure(
        self, asynchronous: bool, failure: type[BaseException]
    ) -> None:
        self.claim()
        task = Task.objects.create(team=self.team, title="Scout", origin_product="signals_scout")
        run = task.create_run(environment=TaskRun.Environment.CLOUD)
        outer_task = (self.team.id, uuid4())
        outer_funding = (self.team.id, TrialFunding(funding="existing"))

        async def emit() -> None:
            async with funded_report(team=self.team, run_id=run.id, emission_key="failed-report"):
                raise failure()

        task_token = task_trial_context.set(outer_task)
        funding_token = direct_report_funding.set(outer_funding)
        try:
            with self.assertRaises(failure):
                if asynchronous:
                    async_to_sync(emit)()
                else:
                    with funded_report_sync(team=self.team, run_id=run.id, emission_key="failed-report"):
                        raise failure()
            assert task_trial_context.get() == outer_task
            assert direct_report_funding.get() == outer_funding
        finally:
            task_trial_context.reset(task_token)
            direct_report_funding.reset(funding_token)

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
        self._exhaust_grant(grant)
        self.flag_mock.return_value = True

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
