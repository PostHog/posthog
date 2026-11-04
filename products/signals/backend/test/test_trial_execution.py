from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from parameterized import parameterized

from posthog.llm.gateway_usage import GatewayRequestCost

from products.signals.backend.constants import FIRST_REPORT_SCOUT
from products.signals.backend.facade.trial import check_trial_run_quota, prepare_task_trial, start_task_trial
from products.signals.backend.free_trial import self_driving_free_trial_enabled
from products.signals.backend.models import SignalReport, SignalScoutConfig, SignalScoutRun, SignalSpend
from products.signals.backend.quota import trial_quota_gate
from products.signals.backend.spend import record_llm_spend, record_task_spend
from products.signals.backend.task_run_artefacts import record_report_task
from products.signals.backend.trial.models import SignalTrialGrant, SignalTrialReportReservation
from products.signals.backend.trial.policy import TrialPolicy, TrialRefused
from products.signals.backend.trial.reports import (
    implementation_requires_trial_opt_in,
    prepare_report_pass,
    requires_trial_accounting,
)
from products.signals.backend.trial.scouts import trial_scout_limit
from products.signals.backend.trial.tasks import cancel_trial_grant
from products.tasks.backend.facade.billing import get_task_run_token_usage, process_pending_gateway_usage
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
            (FIRST_REPORT_SCOUT, "onboarding", True),
            (FIRST_REPORT_SCOUT, "manual", False),
            ("signals-scout-general", "onboarding", False),
        ]
    )
    def test_disabled_scout_only_runs_for_authorized_first_report(
        self, skill_name: str, triggered_by: str, allowed: bool
    ) -> None:
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
        if allowed:
            assert start_task_trial(team=self.team, run_id=run.id)
        else:
            with self.assertRaisesMessage(TrialRefused, "scout_disabled"):
                start_task_trial(team=self.team, run_id=run.id)

    def test_cost_notification_updates_grant_without_trial_polling(self) -> None:
        grant = self.claim()
        run = self.make_run()
        assert start_task_trial(team=self.team, run_id=run.id)
        self.record_token_cost(run)
        grant.refresh_from_db()
        assert grant.settled_microusd == 40_123

    def test_trial_start_requires_successful_receipt_registration(self) -> None:
        self.claim()
        with patch("products.signals.backend.spend.save_trial_spend", side_effect=RuntimeError("write failed")):
            with self.assertRaisesMessage(RuntimeError, "write failed"):
                self.make_run()
        assert not SignalSpend.objects.for_team(self.team.id).exists()

    @parameterized.expand(
        [("implementation", True, "cancelled"), ("research", True, "proceed"), ("research", False, "cancelled")]
    )
    def test_workflow_quota_recheck_enforces_shared_costs(self, stage: str, started: bool, outcome: str) -> None:
        self.claim()
        run = self.make_run(stage)
        run.status = TaskRun.Status.IN_PROGRESS
        run.state["sandbox_provisioning_started"] = started
        run.state["token_cost"] = {"model": {"provider": {"cost_microusd": 10_000_001}}}
        run.save(update_fields=["state", "status"])
        with patch("products.signals.backend.trial.tasks.cancel_task_run", return_value=("accepted", None)) as cancel:
            assert check_trial_run_quota(team=self.team, run_id=run.id) == outcome
        assert cancel.called == (outcome == "cancelled")

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
        assert ("self_driving_funding" in run.state) == (claimed and accounted)
        assert SignalSpend.objects.for_team(self.team.id).filter(task_run_id=run.id).exists() == accounted
        if claimed and not accounted:
            grant = self.policy.grant()
            assert grant is not None and grant.incomplete_sources == 0

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
        assert grant.settled_microusd == 40_123

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

    @parameterized.expand([(True,), (False,)])
    def test_cost_exhaustion_cancels_implementation_with_existing_pr(self, enabled: bool) -> None:
        grant = self.claim()
        run = self.make_run()
        task = run.task
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
        with patch("products.signals.backend.trial.tasks.cancel_task_run", return_value=("accepted", None)) as cancel:
            cancel_trial_grant(self.team.id, str(grant.id))
        if enabled:
            assert cancel.call_args.args[:3] == (run.id, task.id, self.team.id)
        else:
            cancel.assert_not_called()
            assert not start_task_trial(team=self.team, run_id=run.id)
            assert check_trial_run_quota(team=self.team, run_id=run.id) is None
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
        quota = trial_quota_gate(self.team)
        if enabled:
            assert quota is not None and not quota.enforced
        else:
            assert quota is None
        admission = prepare_task_trial(team=self.team, origin="signals_scout")
        if not enabled:
            assert admission is None
            task = Task.objects.create(team=self.team, title="Scout outside rollout", origin_product="signals_scout")
            run = task.create_run()
            assert "self_driving_funding" not in run.state
            assert not start_task_trial(team=self.team, run_id=run.id)
            assert check_trial_run_quota(team=self.team, run_id=run.id) is None
            report = SignalReport.objects.create(
                team=self.team, status=SignalReport.Status.IN_PROGRESS, triggering_signal_id=uuid4()
            )
            prepare_report_pass(team=self.team, report_id=str(report.id), operation_key="outside-rollout")
            report.refresh_from_db()
            assert report.self_driving_funding is None
            assert not implementation_requires_trial_opt_in(self.team.id, str(report.id))
            assert not SignalTrialReportReservation.objects.for_team(self.team.id).exists()
            return
        assert admission is not None
        funding = admission.bind(
            origin="signals_scout",
            stage="scout",
            report_id=None,
        )
        assert funding["funding"] == "trial"
        assert funding["grant_id"] == str(grant.id)

    def test_only_executing_research_finishes_after_exhaustion(self) -> None:
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
        research.state["sandbox_provisioning_started"] = True
        research.save(update_fields=["state", "status"])
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
            with self.assertRaises(TrialRefused):
                start_task_trial(team=self.team, run_id=run.id)
        report.status = SignalReport.Status.PENDING_INPUT
        report.save(update_fields=["status"])
        assert SignalTrialReportReservation.objects.for_team(self.team.id).get(report_id=report.id).status == "consumed"
