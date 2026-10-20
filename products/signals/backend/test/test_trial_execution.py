from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.signals.backend.facade.trial import check_trial_run_quota, prepare_task_trial, start_task_trial
from products.signals.backend.free_trial import self_driving_free_trial_enabled
from products.signals.backend.models import SignalReport, SignalSpend
from products.signals.backend.quota import trial_quota_gate
from products.signals.backend.spend import record_llm_spend, record_task_spend
from products.signals.backend.spend_billing import usage_billing_enabled
from products.signals.backend.trial.models import SignalTrialGrant, SignalTrialReportReservation
from products.signals.backend.trial.policy import TrialPolicy, TrialRefused
from products.signals.backend.trial.reports import (
    implementation_requires_trial_opt_in,
    prepare_report_pass,
    requires_trial_accounting,
)
from products.signals.backend.trial.scouts import trial_scout_limit
from products.signals.backend.trial.tasks import cancel_trial_grant
from products.tasks.backend.facade.billing import get_task_run_actual_cost
from products.tasks.backend.facade.contracts import TaskRunActualCost
from products.tasks.backend.logic.services.gateway_usage import record_gateway_routing
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

    def test_cost_notification_updates_grant_without_trial_polling(self) -> None:
        grant = self.claim()
        task = Task.objects.create(team=self.team, title="Usage notification", origin_product="signal_report")
        run = task.create_run()
        assert start_task_trial(team=self.team, run_id=run.id)
        with (
            patch(
                "products.tasks.backend.facade.billing.get_task_run_actual_cost",
                return_value=TaskRunActualCost(
                    token_cost_microusd=123, compute_cost_microusd=456, complete=False, compute_complete=False
                ),
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            record_gateway_routing(run_id=run.id, team_id=self.team.id, uses_gateway=True)
        grant.refresh_from_db()
        assert grant.settled_microusd == 579
        assert grant.incomplete_sources == 0  # An unfinished run is not a missing current cost.

    def test_trial_start_requires_successful_receipt_registration(self) -> None:
        self.claim()
        task = Task.objects.create(team=self.team, title="Registration failure", origin_product="signal_report")
        run = task.create_run()
        with patch("products.signals.backend.spend._save_spend", side_effect=RuntimeError("write failed")):
            with self.assertRaisesMessage(RuntimeError, "write failed"):
                start_task_trial(team=self.team, run_id=run.id)
        assert not SignalSpend.objects.for_team(self.team.id).filter(task_ids__contains=[task.id]).exists()

    @parameterized.expand(
        [("scout", False, "cancelled"), ("implementation", True, "cancelled"), ("research", True, "proceed")]
    )
    def test_workflow_quota_recheck_enforces_shared_costs(self, stage: str, started: bool, outcome: str) -> None:
        self.claim()
        task = Task.objects.create(team=self.team, title="Quota fallback", origin_product="signal_report")
        run = task.create_run(extra_state={"ai_stage": stage})
        run.status = TaskRun.Status.IN_PROGRESS
        run.state["sandbox_provisioning_started"] = started
        run.save(update_fields=["state", "status"])
        record_task_spend(team_id=self.team.id, run_id=str(run.id), stage=stage, signal_id=str(uuid4()))
        with (
            patch(
                "products.tasks.backend.facade.billing.get_task_run_actual_cost",
                return_value=TaskRunActualCost(
                    token_cost_microusd=10_000_001, compute_cost_microusd=0, complete=False, compute_complete=False
                ),
            ),
            patch("products.signals.backend.trial.tasks.cancel_task_run", return_value=("accepted", None)) as cancel,
        ):
            assert check_trial_run_quota(team=self.team, run_id=run.id) == outcome
        assert cancel.called == (outcome == "cancelled")

    def test_failure_before_provisioning_records_complete_zero_cost(self) -> None:
        grant = self.claim()
        task = Task.objects.create(team=self.team, title="Preparation failure", origin_product="signal_report")
        run = task.create_run()
        run.status = TaskRun.Status.FAILED
        run.save(update_fields=["status"])
        assert get_task_run_actual_cost(team_id=self.team.id, run_id=run.id) == TaskRunActualCost(
            token_cost_microusd=0, compute_cost_microusd=0, complete=True, compute_complete=True
        )
        record_task_spend(team_id=self.team.id, run_id=str(run.id), stage="implementation", signal_id=str(uuid4()))
        assert not SignalSpend.objects.for_team(self.team.id).get(task_ids__contains=[task.id]).accounting_failed
        grant.refresh_from_db()
        assert grant.incomplete_sources == 0

    def test_unprovisioned_run_does_not_discard_pending_gateway_usage(self) -> None:
        self.claim()
        task = Task.objects.create(team=self.team, title="Pending receipt", origin_product="signal_report")
        run = task.create_run()
        run.status = TaskRun.Status.FAILED
        run.state["unprocessed_request_ids"] = ["pending-request"]
        run.save(update_fields=["status", "state"])
        assert not get_task_run_actual_cost(team_id=self.team.id, run_id=run.id).complete

    @parameterized.expand(
        [
            ("signals_scout", "scout", "claude-opus-5", "claude"),
            ("signal_report", "research", "claude-opus-5", "claude"),
            ("signal_report", "repo_selection", "gpt-6.1-sol", "codex"),
            ("signals_chat", "generation", "gpt-6.1-sol", "codex"),
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
        task = Task.objects.create(team=self.team, title="Implementation", origin_product="signal_report")
        run = task.create_run()
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
        assert usage_billing_enabled(self.team.id) is False
        grant = self.claim()
        self.flag_mock.side_effect = lambda key, *args, **kwargs: {
            "self-driving-ubp": enabled,
            "self-driving-free-trial": True,
        }.get(key, False)
        assert usage_billing_enabled(self.team.id) is enabled
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
            report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.IN_PROGRESS)
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
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.IN_PROGRESS)
        research_task = Task.objects.create(
            team=self.team, title="Research", origin_product="signal_report", signal_report_id=report.id
        )
        research = research_task.create_run(extra_state={"ai_stage": "research"})
        queued = research_task.create_run(extra_state={"ai_stage": "research"})
        implementation_task = Task.objects.create(
            team=self.team, title="Implementation", origin_product="signal_report"
        )
        implementation = implementation_task.create_run()
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
