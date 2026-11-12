from contextlib import nullcontext
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync, sync_to_async
from parameterized import parameterized

from posthog.exceptions import QuotaLimitExceeded
from posthog.llm.gateway_usage import GatewayRequestCost

from products.signals.backend.constants import FIRST_REPORT_SCOUT
from products.signals.backend.facade.trial import (
    prepare_task_trial,
    refresh_trial_run_spend,
    start_task_trial,
    task_trial_admission,
)
from products.signals.backend.free_trial import FreeTrialPullRequestRefused, self_driving_free_trial_enabled
from products.signals.backend.models import SignalReport, SignalScoutConfig, SignalScoutRun, SignalSpend
from products.signals.backend.quota import self_driving_quota_gate
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.spend import record_llm_spend, record_task_spend
from products.signals.backend.task_profiles import IMPLEMENTATION
from products.signals.backend.task_run_artefacts import record_report_task
from products.signals.backend.temporal.agentic.report import RunAgenticReportInput, run_agentic_report_activity
from products.signals.backend.trial.funding import TrialFunding
from products.signals.backend.trial.models import SignalTrialGrant
from products.signals.backend.trial.policy import TrialExecutionRefused, TrialPolicy, TrialRefused
from products.signals.backend.trial.reports import (
    implementation_requires_trial_opt_in,
    prepare_report_pass,
    requires_trial_accounting,
)
from products.signals.backend.trial.scouts import trial_scout_limit
from products.signals.backend.usage import trial_usage
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.billing import get_task_run_token_usage, process_pending_gateway_usage
from products.tasks.backend.facade.contracts import CreatedTaskDTO
from products.tasks.backend.facade.testing import run_task_tool
from products.tasks.backend.models import Task, TaskRun


class TestTrialExecution(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag = patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True)
        self.flag_mock = self.flag.start()
        self.addCleanup(self.flag.stop)
        self.policy = TrialPolicy(self.team)

    def claim(self) -> SignalTrialGrant:
        return self.policy.claim(user_id=self.user.pk)

    def record_token_cost(self, run: TaskRun) -> None:
        run.state["unprocessed_request_ids"] = ["trial-cost"]
        run.save(update_fields=["state"])
        with patch(
            "products.tasks.backend.logic.services.gateway_usage._fetch_gateway_cost",
            new_callable=AsyncMock,
            return_value=GatewayRequestCost(model="example", provider="example", cost_microusd=123),
        ):
            process_pending_gateway_usage(team_id=self.team.id, run_id=run.id)

    def make_run(
        self,
        stage: str = "implementation",
        mode: str = "background",
        environment: TaskRun.Environment = TaskRun.Environment.CLOUD,
    ) -> TaskRun:
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=uuid4())
        task = Task.objects.create(
            team=self.team,
            title="Trial run",
            origin_product="signal_report",
            signal_report_id=report.id,
            internal=stage != "implementation",
        )
        if stage == "implementation":
            record_report_task(
                team_id=self.team.id, report_id=str(report.id), task_id=str(task.id), relationship="implementation"
            )
        return task.create_run(extra_state={"ai_stage": stage}, mode=mode, environment=environment)

    @parameterized.expand([(True,), (False,)])
    def test_background_discussion_keeps_posthog_ai_funding(self, claimed: bool) -> None:
        if claimed:
            self.claim()
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=uuid4())
        task = Task.objects.create(
            team=self.team, title="Discuss report", origin_product="signal_report", signal_report=report
        )
        record_report_task(
            team_id=self.team.id, report_id=str(report.id), task_id=str(task.id), relationship="discussion"
        )
        run = task.create_run(mode="background")
        assert run.state["billing_product"] == "posthog_ai"
        assert run.state["ai_stage"] == "inbox"
        assert "self_driving_funding" not in run.state
        assert not SignalSpend.objects.for_team(self.team.id).filter(task_run_id=run.id).exists()

    @parameterized.expand(
        [
            (FIRST_REPORT_SCOUT, "onboarding"),
            (FIRST_REPORT_SCOUT, "manual"),
            ("signals-scout-general", "onboarding"),
        ]
    )
    def test_accepted_scout_finishes_after_config_is_disabled(self, skill_name: str, triggered_by: str) -> None:
        self.claim()
        config = SignalScoutConfig.objects.for_team(self.team.id).create(
            team_id=self.team.id, skill_name=skill_name, enabled=False
        )
        task = Task.objects.create(team=self.team, title="First report", origin_product="signals_scout")
        run = task.create_run()
        scout_run = SignalScoutRun.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            task_run=run,
            scout_config=config,
            skill_name=skill_name,
            skill_version=1,
            metadata={"triggered_by": triggered_by},
        )
        record_task_spend(team_id=self.team.id, run_id=str(run.id), stage="scout", scout_run_id=str(scout_run.id))
        assert start_task_trial(team=self.team, run_id=run.id)

    def test_cost_notification_updates_trial_usage_without_trial_polling(self) -> None:
        grant = self.claim()
        run = self.make_run()
        assert start_task_trial(team=self.team, run_id=run.id)
        self.record_token_cost(run)
        grant.refresh_from_db()
        assert trial_usage(grant).spend_microusd == 40_123

    def test_trial_start_requires_successful_receipt_registration(self) -> None:
        self.claim()
        with patch("products.signals.backend.models.SignalSpend.save", side_effect=RuntimeError("write failed")):
            with self.assertRaisesMessage(RuntimeError, "write failed"):
                self.make_run()
        assert not SignalSpend.objects.for_team(self.team.id).exists()

    @parameterized.expand([("implementation",), ("research",), ("custom_agent",)])
    def test_workflow_refresh_updates_shared_costs_without_cancelling(self, stage: str) -> None:
        grant = self.claim()
        run = self.make_run(stage)
        run.status = TaskRun.Status.IN_PROGRESS
        run.state["token_cost"] = {"model": {"provider": {"cost_microusd": 10_000_001}}}
        run.save(update_fields=["state", "status"])
        with patch("products.tasks.backend.facade.cancellation.cancel_task_run") as cancel:
            assert refresh_trial_run_spend(team_id=self.team.id, run_id=run.id)
        cancel.assert_not_called()
        grant.refresh_from_db()
        assert trial_usage(grant).spend_microusd == 10_040_001
        assert trial_usage(grant).exhaustion_reason(grant) == "cost_limit"
        run.refresh_from_db()
        assert run.status == TaskRun.Status.IN_PROGRESS

    @parameterized.expand(
        [
            (claimed, mode, environment)
            for claimed in (True, False)
            for mode in ("background", "interactive")
            for environment in (TaskRun.Environment.CLOUD, TaskRun.Environment.LOCAL)
        ]
    )
    def test_manual_work_uses_execution_mode_for_billing(
        self, claimed: bool, mode: str, environment: TaskRun.Environment
    ) -> None:
        if claimed:
            self.claim()
        run = self.make_run("implementation", mode, environment)
        assert (run.state.get("billing_product") == "posthog_ai") == (mode == "interactive")
        accounted = mode == "background" and environment == TaskRun.Environment.CLOUD
        assert ("self_driving_funding" in run.state) == accounted
        assert SignalSpend.objects.for_team(self.team.id).filter(task_run_id=run.id).exists() == accounted
        if claimed and not accounted:
            grant = self.policy.grant()
            assert (
                grant is not None and not SignalSpend.objects.for_team(self.team.id).filter(trial_grant=grant).exists()
            )

    def test_custom_agent_registers_spend_before_trial_provisioning(self) -> None:
        grant = self.claim()
        task = Task.objects.create(team=self.team, title="Custom investigation", origin_product="signal_report")
        run = task.create_run(extra_state={"ai_stage": "custom_agent"})
        assert start_task_trial(team=self.team, run_id=run.id)
        spend = SignalSpend.objects.for_team(self.team.id).get(task_run_id=run.id)
        assert spend.kind == SignalSpend.Kind.CUSTOM_AGENT
        assert spend.billing_exempt and spend.trial_grant_id == grant.id
        assert spend.report_id is None and spend.signal_id is None
        self.record_token_cost(run)
        grant.refresh_from_db()
        assert trial_usage(grant).spend_microusd == 40_123

    @parameterized.expand([("scout_suggestions",), ("signals_chat",)])
    def test_configuration_helpers_do_not_use_report_trial_funding(self, origin: str) -> None:
        self.claim()
        task = Task.objects.create(team=self.team, title="Configure scouts", origin_product=origin)
        run = task.create_run()
        assert "self_driving_funding" not in run.state
        assert not start_task_trial(team=self.team, run_id=run.id)

    def test_unprovisioned_run_does_not_discard_pending_gateway_usage(self) -> None:
        self.claim()
        run = self.make_run()
        run.status = TaskRun.Status.FAILED
        run.state["unprocessed_request_ids"] = ["pending-request"]
        run.save(update_fields=["status", "state"])
        assert not get_task_run_token_usage(team_id=self.team.id, run_id=run.id).complete

    @parameterized.expand(
        [
            ("signals_scout", "scout", "claude-opus-5", "claude"),
            ("signal_report", "research", "claude-opus-5", "claude"),
            ("signal_report", "repo_selection", "gpt-6.1-sol", "codex"),
            ("signal_report", "implementation", "claude-opus-5", "claude"),
        ]
    )
    def test_trial_preserves_selected_model_profile(self, origin: str, stage: str, model: str, runtime: str) -> None:
        self.claim()
        task = Task.objects.create(team=self.team, title="Routing", origin_product=origin)
        profile = {
            "model": model,
            "runtime_adapter": runtime,
            "reasoning_effort": "high",
            "service_tier": "priority",
            f"{runtime}_model_access": "posthog-gateway",
        }
        run = task.create_run(extra_state={"ai_stage": stage, **profile})
        assert {key: run.state[key] for key in profile} == profile
        assert run.state["self_driving_funding"]["funding"] == "trial"

    @parameterized.expand(
        [
            (origin, runtime, adapter, prepared)
            for origin, runtime, adapter in (
                ("signal_report", "pi", None),
                ("signals_scout", "acp", "claude"),
                ("signals_scout", "acp", "codex"),
            )
            for prepared in (False, True)
        ]
    )
    def test_trial_refuses_unaccounted_execution_before_creating_run(
        self, origin: str, runtime: str, adapter: str | None, prepared: bool
    ) -> None:
        grant = self.claim()
        task = Task.objects.create(
            team=self.team, title="Trial run", origin_product=origin, runtime=runtime, internal=True
        )
        state = {"runtime_adapter": adapter, f"{adapter}_model_access": "own-subscription"} if adapter else {}
        admission = task_trial_admission(team=self.team, origin=origin) if prepared else nullcontext()
        with admission, self.assertRaisesMessage(TrialExecutionRefused, "PostHog AI gateway"):
            task.create_run(extra_state=state)
        assert not task.runs.exists()
        assert not SignalSpend.objects.for_team(self.team.id).exists()
        assert trial_usage(grant).spend_microusd == 0

    @parameterized.expand([(False,), (True,)])
    def test_trial_preserves_deepseek_for_pi_scouts(self, prepared: bool) -> None:
        grant = self.claim()
        task = Task.objects.create(
            team=self.team, title="First report", origin_product="signals_scout", runtime="pi", internal=True
        )
        model = "deepseek-ai/deepseek-v4.1-flash-1017-fast"
        admission = task_trial_admission(team=self.team, origin="signals_scout") if prepared else nullcontext()
        with admission:
            run = task.create_run(extra_state={"model": model})
        assert run.state["model"] == model
        assert run.state["self_driving_funding"]["funding"] == "trial"
        assert run.state["self_driving_funding"]["grant_id"] == str(grant.id)
        scout_run = SignalScoutRun.objects.for_team(self.team.id).create(
            team_id=self.team.id, task_run=run, skill_name=FIRST_REPORT_SCOUT, skill_version=1
        )
        record_task_spend(team_id=self.team.id, run_id=str(run.id), stage="scout", scout_run_id=str(scout_run.id))
        assert start_task_trial(team=self.team, run_id=run.id)
        self.record_token_cost(run)
        assert trial_usage(grant).spend_microusd == 40_123

    @parameterized.expand([("pi", None), ("acp", "claude"), ("acp", "codex")])
    def test_existing_funding_keeps_non_trial_execution_modes(self, runtime: str, adapter: str | None) -> None:
        task = Task.objects.create(
            team=self.team, title="Existing scout", origin_product="signals_scout", runtime=runtime
        )
        state = {"runtime_adapter": adapter, f"{adapter}_model_access": "own-subscription"} if adapter else {}
        run = task.create_run(extra_state=state)
        assert run.state["self_driving_funding"]["funding"] == "existing"

    @parameterized.expand([(True,), (False,)])
    def test_cost_exhaustion_keeps_accepted_implementation_with_existing_pr(self, enabled: bool) -> None:
        grant = self.claim()
        run = self.make_run()
        run.output = {"pr_url": "https://github.com/example/repository/pull/1"}
        run.save(update_fields=["output"])
        record_llm_spend(
            "exhaust",
            team_id=self.team.id,
            signal_id=str(uuid4()),
            stage="research",
            token_cost_microusd=10_000_000,
            trial_grant_id=str(grant.id),
        )
        self.flag_mock.return_value = enabled
        self.flag_mock.reset_mock()
        with patch("products.tasks.backend.facade.cancellation.cancel_task_run") as cancel:
            assert start_task_trial(team=self.team, run_id=run.id)
            assert refresh_trial_run_spend(team_id=self.team.id, run_id=run.id)
        cancel.assert_not_called()
        self.flag_mock.assert_not_called()
        run.refresh_from_db()
        assert run.output["pr_url"] == "https://github.com/example/repository/pull/1"

    @parameterized.expand([(True,), (False,)])
    def test_claimed_one_time_trial_requires_rollout_for_new_work(self, enabled: bool) -> None:
        grant = self.claim()
        self.flag_mock.side_effect = lambda key, *args, **kwargs: {
            "self-driving-ubp": enabled,
            "self-driving-free-trial": True,
        }.get(key, False)
        assert requires_trial_accounting(self.team.id) is enabled
        assert self_driving_free_trial_enabled(self.team) is (not enabled)
        assert trial_scout_limit(self.team.id) == (3 if enabled else None)
        assert not self_driving_quota_gate(self.team).enforced
        admission = prepare_task_trial(team=self.team, origin="signals_scout")
        if not enabled:
            assert admission is not None
            task = Task.objects.create(team=self.team, title="Scout outside rollout", origin_product="signals_scout")
            run = task.create_run()
            assert run.state["self_driving_funding"]["funding"] == "existing"
            assert not start_task_trial(team=self.team, run_id=run.id)
            assert not refresh_trial_run_spend(team_id=self.team.id, run_id=run.id)
            report = SignalReport.objects.create(
                team=self.team, status=SignalReport.Status.IN_PROGRESS, triggering_signal_id=uuid4()
            )
            prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="outside-rollout")
            report.refresh_from_db()
            assert report.self_driving_funding is not None
            assert report.self_driving_funding["funding"] == "existing"
            assert not implementation_requires_trial_opt_in(self.team.id, str(report.id))
            return
        assert admission is not None
        funding = admission.bind(
            origin="signals_scout",
            stage="scout",
            report_id=None,
            task_runtime="acp",
            model_access="posthog-gateway",
        )
        assert funding["funding"] == "trial"
        assert funding["grant_id"] == str(grant.id)

    def test_all_accepted_tasks_finish_after_exhaustion(self) -> None:
        grant = self.claim()
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.IN_PROGRESS, triggering_signal_id=uuid4()
        )
        research_task = Task.objects.create(
            team=self.team, title="Research", origin_product="signal_report", signal_report_id=report.id, internal=True
        )
        research = research_task.create_run(extra_state={"ai_stage": "research"})
        queued = research_task.create_run(extra_state={"ai_stage": "research"})
        implementation = self.make_run()
        research.status = TaskRun.Status.IN_PROGRESS
        research.save(update_fields=["status"])
        record_llm_spend(
            "exhaust",
            team_id=self.team.id,
            signal_id=str(uuid4()),
            stage="research",
            token_cost_microusd=10_000_000,
            trial_grant_id=str(grant.id),
        )
        assert start_task_trial(team=self.team, run_id=research.id)
        for run in (queued, implementation):
            assert start_task_trial(team=self.team, run_id=run.id)
        with patch("products.signals.backend.trial.billing.paid_trial_continuation_authorized", return_value=False):
            with self.assertRaisesMessage(TrialRefused, "cost_limit"):
                self.make_run()
        report.refresh_from_db()
        report.save(update_fields=report.transition_to(SignalReport.Status.PENDING_INPUT, error="Needs user input"))
        assert trial_usage(grant).reports == 1

    @parameterized.expand([("task",), ("report",), ("gateway",)])
    def test_unknown_flag_refuses_new_work_instead_of_bypassing_trial(self, entrypoint: str) -> None:
        self.claim()
        self.flag_mock.return_value = None
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=uuid4())
        with patch("products.signals.backend.trial.policy.cache.get", return_value=None):
            with self.assertRaisesMessage(TrialRefused, "flag_unavailable"):
                if entrypoint == "task":
                    self.make_run()
                elif entrypoint == "report":
                    prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="new-work")
                else:
                    requires_trial_accounting(self.team.id)
        assert not SignalSpend.objects.for_team(self.team.id).exists()
        report.refresh_from_db()
        assert report.self_driving_funding is None

    @parameterized.expand([(False,), (None,)])
    def test_accepted_report_pass_retry_does_not_recheck_the_flag(self, enabled: bool | None) -> None:
        self.claim()
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=uuid4())
        prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="accepted")
        self.flag_mock.return_value = enabled
        self.flag_mock.reset_mock()
        prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="accepted")
        self.flag_mock.assert_not_called()

    def test_accepted_report_implementation_keeps_funding_but_manual_rerun_is_new_work(self) -> None:
        grant = self.claim()
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=uuid4())
        prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="accepted")
        report.refresh_from_db()
        report.status = SignalReport.Status.READY
        report.save(update_fields=["status"])
        record_llm_spend(
            "exhaust",
            team_id=self.team.id,
            signal_id=str(uuid4()),
            stage="research",
            token_cost_microusd=10_000_001,
            trial_grant_id=str(grant.id),
        )
        task = Task.objects.create(
            team=self.team, title="Accepted implementation", origin_product="signal_report", signal_report=report
        )
        record_report_task(
            team_id=self.team.id, report_id=str(report.id), task_id=str(task.id), relationship="implementation"
        )
        self.flag_mock.return_value = False
        with task_trial_admission(
            team=self.team, origin="signal_report", report_id=report.id, continue_admitted_pipeline=True
        ):
            run = task.create_run()
        assert run.state["self_driving_funding"]["grant_id"] == str(grant.id)
        assert run.state["self_driving_funding"]["report_pass_key"] == "accepted"
        receipt = SignalSpend.objects.for_team(self.team.id).get(task_run_id=run.id)
        assert receipt.trial_grant_id == grant.id and receipt.billing_exempt
        self.flag_mock.return_value = True
        with patch("products.signals.backend.trial.billing.paid_trial_continuation_authorized", return_value=False):
            with self.assertRaisesMessage(TrialRefused, "cost_limit"):
                task.create_run()
        assert task.runs.count() == 1

    def test_private_scout_experiment_does_not_consume_the_customer_trial(self) -> None:
        grant = self.claim()
        task = Task.objects.create(
            team=self.team,
            title="Private scout experiment",
            origin_product="signals_scout",
            origin_key=f"scout-trial:{uuid4()}",
        )
        run = task.create_run()
        assert "self_driving_funding" not in run.state
        grant.refresh_from_db()
        assert trial_usage(grant).spend_microusd == 0
        assert (
            not SignalSpend.objects.for_team(self.team.id).filter(trial_grant=grant, accounting_pending=True).exists()
        )

    @parameterized.expand(
        [
            (status,)
            for status in (SignalReport.Status.CANDIDATE, SignalReport.Status.IN_PROGRESS, SignalReport.Status.READY)
        ]
    )
    def test_manual_tool_run_does_not_inherit_an_exhausted_report_grant(self, status: str) -> None:
        grant = self.claim()
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=uuid4())
        prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="accepted")
        report.refresh_from_db()
        report.status = status
        report.save(update_fields=["status"])
        task = Task.objects.create(
            team=self.team,
            title="Manual implementation",
            origin_product="signal_report",
            signal_report=report,
            created_by=self.user,
        )
        record_report_task(
            team_id=self.team.id, report_id=str(report.id), task_id=str(task.id), relationship="implementation"
        )
        record_llm_spend(
            "exhaust",
            team_id=self.team.id,
            signal_id=str(uuid4()),
            stage="research",
            token_cost_microusd=10_000_001,
            trial_grant_id=str(grant.id),
        )
        with (
            patch("products.signals.backend.trial.billing.paid_trial_continuation_authorized", return_value=False),
            patch(
                "products.tasks.backend.max_tools.execute_task_processing_workflow_async", new_callable=AsyncMock
            ) as dispatch,
        ):
            with self.assertRaisesMessage(TrialRefused, "cost_limit"):
                async_to_sync(run_task_tool)(team=self.team, user=self.user, task_id=str(task.id))
        dispatch.assert_not_called()
        assert task.runs.count() == 0

    @parameterized.expand(
        [
            (entrypoint, limited, claimed)
            for entrypoint in ("facade", "tool", "canvas", "bootstrap")
            for limited in (True, False)
            for claimed in (True, False)
        ]
    )
    def test_manual_run_without_active_trial_obeys_self_driving_quota(
        self, entrypoint: str, limited: bool, claimed: bool
    ) -> None:
        if claimed:
            self.claim()
        self.flag_mock.return_value = False
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=uuid4())
        task = Task.objects.create(
            team=self.team,
            title="Paid implementation",
            origin_product="signal_report",
            signal_report=report,
            created_by=self.user,
        )
        record_report_task(
            team_id=self.team.id, report_id=str(report.id), task_id=str(task.id), relationship="implementation"
        )
        with (
            patch("products.signals.backend.quota.is_team_signals_quota_limited", return_value=limited),
            patch("products.signals.backend.quota.self_driving_quota_enforcement_enabled", return_value=True),
            patch(
                "products.tasks.backend.logic.services.compute_quota.get_compute_quota_denial_reason", return_value=None
            ),
            patch("products.tasks.backend.temporal.client.execute_task_processing_workflow"),
            patch("products.tasks.backend.max_tools.execute_task_processing_workflow_async", new_callable=AsyncMock),
        ):
            with self.assertRaises(QuotaLimitExceeded) if limited else nullcontext():
                if entrypoint == "canvas":
                    assert (
                        tasks_facade.request_canvas_fix(
                            task.id, self.team.id, prompt="Fix the canvas", acting_user_id=self.user.id
                        )
                        == "new_run"
                    )
                elif entrypoint == "tool":
                    async_to_sync(run_task_tool)(team=self.team, user=self.user, task_id=str(task.id))
                elif entrypoint == "bootstrap":
                    created = tasks_facade.bootstrap_task_run(
                        task.id,
                        self.team.id,
                        self.user.id,
                        validated_data={"mode": "background", "environment": TaskRun.Environment.CLOUD},
                    )
                    assert created is not None and created.error is None and created.run is not None
                else:
                    result = tasks_facade.run_task(
                        task.id,
                        self.team.id,
                        self.user.id,
                        validated_data={"mode": "background"},
                        free_trial_enabled=False,
                    )
                    assert result is not None and result.error is None and result.run_error is None
        assert task.runs.count() == (0 if limited else 1)

    def test_bootstrapped_run_can_start_after_the_quota_is_reached(self) -> None:
        self.flag_mock.return_value = False
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=uuid4())
        task = Task.objects.create(
            team=self.team,
            title="Admitted bootstrap",
            origin_product="signal_report",
            signal_report=report,
            created_by=self.user,
        )
        record_report_task(
            team_id=self.team.id, report_id=str(report.id), task_id=str(task.id), relationship="implementation"
        )
        with patch("products.signals.backend.quota.is_team_signals_quota_limited", return_value=False):
            created = tasks_facade.bootstrap_task_run(
                task.id,
                self.team.id,
                self.user.id,
                validated_data={"mode": "background", "environment": TaskRun.Environment.CLOUD},
            )
        assert created is not None and created.error is None and created.run is not None
        with (
            patch("products.signals.backend.quota.is_team_signals_quota_limited", return_value=True),
            patch("products.signals.backend.quota.self_driving_quota_enforcement_enabled", return_value=True),
            patch("products.tasks.backend.facade.api._trigger_task_processing_workflow") as dispatch,
        ):
            assert tasks_facade.start_task_run(
                created.run.id, task.id, self.team.id, self.user.id, validated_data={}
            ) == ("started", task.id)
        dispatch.assert_called_once()
        assert task.runs.count() == 1

    @parameterized.expand(
        [
            (TaskRun.Environment.LOCAL, "background", "implementation"),
            (TaskRun.Environment.CLOUD, "interactive", "implementation"),
            (TaskRun.Environment.CLOUD, "background", "discussion"),
        ]
    )
    def test_other_bootstrap_billing_keeps_its_existing_gate(
        self, environment: str, mode: str, relationship: str
    ) -> None:
        self.flag_mock.return_value = False
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=uuid4())
        task = Task.objects.create(
            team=self.team,
            title="Local implementation",
            origin_product="signal_report",
            signal_report=report,
            created_by=self.user,
        )
        record_report_task(
            team_id=self.team.id, report_id=str(report.id), task_id=str(task.id), relationship=relationship
        )
        with patch(
            "products.signals.backend.facade.self_driving.self_driving_quota_gate",
            side_effect=AssertionError("This work does not use the cloud Self-driving gate"),
        ):
            created = tasks_facade.bootstrap_task_run(
                task.id,
                self.team.id,
                self.user.id,
                validated_data={"mode": mode, "environment": environment},
            )
        assert created is not None and created.error is None and created.run is not None
        assert task.runs.count() == 1

    def test_bootstrap_uses_an_active_trial_instead_of_the_ordinary_quota(self) -> None:
        grant = self.claim()
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=uuid4())
        task = Task.objects.create(
            team=self.team,
            title="Trial bootstrap",
            origin_product="signal_report",
            signal_report=report,
            created_by=self.user,
        )
        record_report_task(
            team_id=self.team.id, report_id=str(report.id), task_id=str(task.id), relationship="implementation"
        )
        with patch(
            "products.signals.backend.facade.self_driving.self_driving_quota_gate",
            side_effect=AssertionError("A trial-funded run uses trial admission"),
        ):
            created = tasks_facade.bootstrap_task_run(
                task.id,
                self.team.id,
                self.user.id,
                validated_data={"mode": "background", "environment": TaskRun.Environment.CLOUD},
            )
        assert created is not None and created.error is None and created.run is not None
        assert task.runs.get().state["self_driving_funding"]["grant_id"] == str(grant.id)

    @parameterized.expand([("existing", False), ("operator", False), ("operator", True)])
    def test_accepted_pipeline_without_trial_finishes_after_the_quota(self, funding: str, exempt: bool) -> None:
        self.flag_mock.side_effect = lambda key, *args, **kwargs: (
            funding == "operator" and key == "self-driving-free-trial"
        )
        report = SignalReport.objects.create(
            team=self.team,
            triggering_signal_id=uuid4(),
            run_count=1,
            billing_exempt_reason=SignalReport.BillingExemptReason.POSTHOG_SYSTEM if exempt else None,
        )
        prepare_report_pass(
            team=self.team, report_id=str(report.id), operation_key="accepted", operator_rerun=funding == "operator"
        )
        task = Task.objects.create(
            team=self.team,
            title="Accepted implementation",
            origin_product="signal_report",
            signal_report=report,
            created_by=self.user,
            internal=True,
        )
        record_report_task(
            team_id=self.team.id, report_id=str(report.id), task_id=str(task.id), relationship="implementation"
        )
        with (
            patch("products.signals.backend.quota.is_team_signals_quota_limited", return_value=True),
            patch("products.signals.backend.quota.self_driving_quota_enforcement_enabled", return_value=True),
            patch("products.tasks.backend.temporal.client.execute_task_processing_workflow"),
        ):
            result = tasks_facade.run_task(
                task.id,
                self.team.id,
                self.user.id,
                validated_data={"mode": "background"},
                pipeline_rerun=True,
                free_trial_enabled=funding == "operator",
            )
        assert result is not None and result.error is None and result.run_error is None
        assert task.runs.count() == 1
        assert task.runs.get().state["self_driving_funding"]["funding"] == funding

    def test_background_research_keeps_report_admission_after_the_quota(self) -> None:
        self.flag_mock.return_value = False
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.IN_PROGRESS)
        task = Task.objects.create(team=self.team, title="Accepted research", origin_product="signal_report")

        async def start_research(input: RunAgenticReportInput) -> None:
            await sync_to_async(task.create_run)(environment=TaskRun.Environment.CLOUD)

        with (
            patch("products.signals.backend.quota.is_team_signals_quota_limited", return_value=True),
            patch("products.signals.backend.quota.self_driving_quota_enforcement_enabled", return_value=True),
            patch("products.signals.backend.temporal.agentic.report._run_agentic_report", side_effect=start_research),
        ):
            async_to_sync(run_agentic_report_activity)(
                RunAgenticReportInput(
                    team_id=self.team.id,
                    report_id=str(report.id),
                    signals=[],
                    repo_selection=RepoSelectionResult(repository=None, reason="No repository"),
                )
            )
        assert task.runs.get().state["self_driving_funding"]["funding"] == "existing"

    @parameterized.expand([("signaled",), ("already_queued",), ("stale",)])
    def test_canvas_only_checks_self_driving_quota_for_a_new_run(self, outcome: str) -> None:
        self.flag_mock.return_value = False
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=uuid4())
        task = Task.objects.create(
            team=self.team,
            title="Running implementation",
            origin_product="signal_report",
            signal_report=report,
            created_by=self.user,
        )
        record_report_task(
            team_id=self.team.id, report_id=str(report.id), task_id=str(task.id), relationship="implementation"
        )
        run = task.create_run(
            extra_state={"pending_user_message": "Accepted work"} if outcome == "already_queued" else {}
        )
        run.status = TaskRun.Status.QUEUED if outcome == "already_queued" else TaskRun.Status.IN_PROGRESS
        run.save(update_fields=["status"])
        with (
            patch("products.signals.backend.quota.is_team_signals_quota_limited", return_value=True),
            patch("products.signals.backend.quota.self_driving_quota_enforcement_enabled", return_value=True),
            patch(
                "products.tasks.backend.logic.services.compute_quota.get_compute_quota_denial_reason", return_value=None
            ),
            patch("products.tasks.backend.facade.api.signal_task_run_user_message", return_value=outcome == "signaled"),
        ):
            with self.assertRaises(QuotaLimitExceeded) if outcome == "stale" else nullcontext():
                assert (
                    tasks_facade.request_canvas_fix(
                        task.id, self.team.id, prompt="Fix the canvas", acting_user_id=self.user.id
                    )
                    == outcome
                )
        assert task.runs.count() == 1

    @parameterized.expand([("trial",), ("paid",), ("operator",), ("existing",), (None,)])
    def test_facade_continuation_keeps_admitted_funding_when_trial_rollout_is_disabled(
        self, funding: str | None
    ) -> None:
        grant = self.claim()
        report = SignalReport.objects.create(team=self.team, triggering_signal_id=uuid4())
        if funding in {"trial", "paid", "operator"}:
            if funding == "paid":
                record_llm_spend(
                    "exhaust",
                    team_id=self.team.id,
                    signal_id=str(uuid4()),
                    stage="research",
                    token_cost_microusd=10_000_001,
                    trial_grant_id=str(grant.id),
                )
            with patch("products.signals.backend.trial.billing.paid_trial_continuation_authorized", return_value=True):
                prepare_report_pass(
                    team=self.team,
                    report_id=str(report.id),
                    operation_key="accepted",
                    operator_rerun=funding == "operator",
                )
            report.refresh_from_db()
        elif funding is not None:
            report.self_driving_funding = TrialFunding(funding="existing", report_pass_key="accepted").as_dict()
        report.status = SignalReport.Status.READY
        report.save(update_fields=["status", "self_driving_funding"])
        self.flag_mock.side_effect = lambda key, *args, **kwargs: key == "self-driving-free-trial"

        def create_implementation(*, continue_admitted_pipeline: bool = False) -> CreatedTaskDTO:
            return tasks_facade.create_and_run_task(
                team=self.team,
                title="Implementation",
                description="Continue the accepted report",
                user_id=self.user.pk,
                profile=IMPLEMENTATION,
                signal_report_id=str(report.id),
                start_workflow=False,
                free_trial_enabled=True,
                continue_admitted_pipeline=continue_admitted_pipeline,
            )

        created = create_implementation(continue_admitted_pipeline=True)
        assert created.latest_run is not None
        run = TaskRun.objects.get(id=created.latest_run.id)
        assert run.state["self_driving_funding"]["funding"] == (funding or "existing")
        receipt = SignalSpend.objects.for_team(self.team.id).get(task_run_id=run.id)
        assert receipt.billing_exempt is (funding in {"trial", "operator"})
        assert (receipt.trial_grant_id == grant.id) is (funding == "trial")
        with self.assertRaises(FreeTrialPullRequestRefused):
            create_implementation()
        assert implementation_requires_trial_opt_in(self.team.id, str(report.id)) is (funding == "trial")

    def test_projects_without_a_grant_do_not_depend_on_the_trial_flag(self) -> None:
        self.flag_mock.return_value = None
        with patch("products.signals.backend.trial.policy.cache.get", return_value=None):
            run = self.make_run()
        assert run.state["self_driving_funding"]["funding"] == "existing"
        assert SignalSpend.objects.for_team(self.team.id).get(task_run_id=run.id).trial_grant_id is None
