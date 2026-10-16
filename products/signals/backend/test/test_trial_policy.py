from datetime import timedelta
from uuid import UUID, uuid4

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from django.core.management import call_command
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

import httpx
from anthropic import APIStatusError
from asgiref.sync import async_to_sync
from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.llm.gateway_client import AIGatewayConfig
from posthog.llm.gateway_usage import GatewayRequestCost
from posthog.models import Team

from products.signals.backend.llm_spend import generate_with_spend
from products.signals.backend.models import SignalReport, SignalScoutConfig, SignalSpend
from products.signals.backend.spend import complete_signal_pipeline, record_llm_spend, record_task_spend
from products.signals.backend.spend_billing import spend_billing_credits_by_team, usage_billing_enabled
from products.signals.backend.spend_recovery import recover_spend
from products.signals.backend.trial.models import (
    SignalTrialGrant,
    SignalTrialOperation,
    SignalTrialOrganization,
    SignalTrialReportReservation,
)
from products.signals.backend.trial.policy import OperationAdmission, TrialPolicy, TrialRefused
from products.signals.backend.trial.tasks import cancel_trial_grant, reconcile_trial_operation
from products.tasks.backend.facade.billing import get_task_run_actual_cost
from products.tasks.backend.facade.contracts import TaskRunActualCost
from products.tasks.backend.models import Task, TaskRun


@override_settings(SELF_DRIVING_TRIAL_V2_BILLING_READY=True)
class TestTrialPolicy(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag = patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True)
        self.flag_mock = self.flag.start()
        self.addCleanup(self.flag.stop)
        self.policy = TrialPolicy(self.team)

    def claim(self) -> SignalTrialGrant:
        grant = self.policy.claim(user_id=self.user.pk)
        SignalTrialOrganization.objects.filter(organization_id=self.organization.pk).update(
            billing_migrated_at=timezone.now()
        )
        return grant

    def admit(
        self, *, stage: SignalTrialOperation.Stage = SignalTrialOperation.Stage.SCOUT, report_id: UUID | None = None
    ) -> SignalTrialOperation:
        return self.policy.admit(
            OperationAdmission(operation_key=str(uuid4()), stage=stage, report_id=report_id),
            paid_authorized=False,
        )

    def test_duplicate_and_child_activation_share_lifetime_grant(self) -> None:
        grant = self.claim()
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child")
        assert TrialPolicy(child).claim(user_id=self.user.pk).id == grant.id
        assert self.policy.claim(user_id=self.user.pk).id == grant.id
        assert SignalTrialOrganization.objects.get(organization_id=self.organization.pk).grants_claimed == 1

    def test_deleting_project_does_not_return_organization_slot(self) -> None:
        projects = [Team.objects.create(organization=self.organization, name=f"Project {index}") for index in range(3)]
        for team in projects:
            TrialPolicy(team).claim(user_id=self.user.pk)
        deleted_id = projects[0].pk
        projects[0].delete()
        assert SignalTrialGrant.objects.for_team(deleted_id, canonical=True).exists()
        with self.assertRaisesMessage(TrialRefused, "organization_limit"):
            self.policy.claim(user_id=self.user.pk)

    def test_unknown_flag_retains_confirmed_decision_but_cannot_claim(self) -> None:
        assert self.policy.flag_decision().enabled is True
        with CaptureQueriesContext(connection) as queries:
            assert self.policy.flag_decision().enabled is True
        assert not any(query["sql"].startswith("UPDATE") for query in queries)
        self.flag_mock.side_effect = RuntimeError("unavailable")
        assert self.policy.flag_decision().enabled is True
        with self.assertRaisesMessage(TrialRefused, "flag_unavailable"):
            self.policy.claim(user_id=self.user.pk)
        self.flag_mock.side_effect = None
        self.flag_mock.return_value = False
        assert self.policy.flag_decision().enabled is False

    def test_activation_pauses_excess_scouts_and_preserves_user_pause(self) -> None:
        scouts = [SignalScoutConfig.objects.create(team=self.team, skill_name=f"scout-{index}") for index in range(5)]
        paused = SignalScoutConfig.objects.create(team=self.team, skill_name="paused", enabled=False)
        self.claim()
        for scout in scouts:
            scout.refresh_from_db()
        paused.refresh_from_db()
        assert [scout.enabled for scout in scouts] == [True, True, True, False, False]
        assert scouts[-1].pause_reason == SignalScoutConfig.PauseReason.TRIAL_SCOUT_LIMIT
        assert paused.status == SignalScoutConfig.Status.PAUSED_BY_USER

    def test_report_slots_release_only_before_delivery(self) -> None:
        grant = self.claim()
        reports = [uuid4() for _ in range(6)]
        for report_id in reports[:5]:
            self.admit(stage=SignalTrialOperation.Stage.RESEARCH, report_id=report_id)
        with self.assertRaisesMessage(TrialRefused, "report_limit"):
            self.admit(stage=SignalTrialOperation.Stage.RESEARCH, report_id=reports[5])
        with self.policy.publish_report(reports[0], delivered=False):
            pass
        self.admit(stage=SignalTrialOperation.Stage.RESEARCH, report_id=reports[5])
        for report_id in reports[1:]:
            with self.policy.publish_report(report_id, delivered=True):
                pass
            with self.policy.publish_report(report_id, delivered=False):
                pass
        grant.refresh_from_db()
        assert grant.exhaustion_reason == "report_limit"
        with self.assertRaisesMessage(TrialRefused, "report_limit"):
            self.admit()

    def test_publication_rollback_preserves_reservation(self) -> None:
        self.claim()
        report_id = uuid4()
        self.admit(stage=SignalTrialOperation.Stage.RESEARCH, report_id=report_id)

        def failed_write() -> None:
            raise ValueError("publish failed")

        with self.assertRaisesMessage(ValueError, "publish failed"):
            with self.policy.publish_report(report_id, delivered=True):
                failed_write()
        with self.policy.publish_report(report_id, delivered=True):
            pass

    def test_editing_historical_report_does_not_consume_its_new_research_slot(self) -> None:
        historical = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY, title="Original")
        self.claim()
        self.admit(stage=SignalTrialOperation.Stage.RESEARCH, report_id=historical.id)
        SignalReport.objects.filter(team=self.team, id=historical.id).update(status=SignalReport.Status.IN_PROGRESS)
        historical.title = "Edited"
        historical.save(update_fields=["title"])
        slot = SignalTrialReportReservation.objects.for_team(self.team.id).get(report_id=historical.id)
        assert slot.status == SignalTrialReportReservation.Status.RESERVED
        historical.refresh_from_db()
        assert historical.status == SignalReport.Status.IN_PROGRESS
        historical.status = SignalReport.Status.READY
        historical.save(update_fields=["status"])
        slot.refresh_from_db()
        assert slot.status == SignalTrialReportReservation.Status.CONSUMED

    def test_direct_report_retries_hold_slot_until_last_attempt_finishes(self) -> None:
        self.claim()
        operation = self.admit()
        report = uuid4()
        for _ in range(2):
            self.policy.reserve_direct_report(operation.id, report)
        self.policy.finish_direct_report_attempt(report)
        with self.policy.publish_report(report, delivered=True):
            pass
        self.policy.finish_direct_report_attempt(report)
        slot = SignalTrialReportReservation.objects.for_team(self.team.pk).get(report_id=report)
        assert slot.status == SignalTrialReportReservation.Status.CONSUMED

    def test_scout_cap_is_shared_with_environments_and_supports_swapping(self) -> None:
        self.claim()
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child")
        scouts = [SignalScoutConfig.objects.create(team=child, skill_name=f"scout-{i}") for i in range(4)]
        assert [scout.enabled for scout in scouts] == [True, True, True, False]
        scouts[-1].enabled = True
        with self.assertRaises(ValidationError):
            scouts[-1].save(update_fields=["enabled"])
        scouts[-1].refresh_from_db()
        scouts[0].enabled = False
        scouts[0].save(update_fields=["enabled"])
        scouts[-1].enabled = True
        scouts[-1].save(update_fields=["enabled"])
        assert SignalScoutConfig.objects.for_team(self.team.pk).filter(enabled=True).count() == 3

    def test_admitted_report_pass_keeps_trial_funding_after_flag_off(self) -> None:
        self.claim()
        report = uuid4()
        parent = self.admit(stage=SignalTrialOperation.Stage.REPORT_PASS, report_id=report)
        self.flag_mock.return_value = False
        child = self.policy.admit(
            OperationAdmission(
                operation_key="child",
                stage=SignalTrialOperation.Stage.RESEARCH,
                report_id=report,
                report_pass_id=parent.id,
            ),
            paid_authorized=True,
        )
        assert child.funding == SignalTrialOperation.Funding.TRIAL
        assert child.grant_id == parent.grant_id

    @parameterized.expand([(True, True), (True, False), (False, True), (False, False)])
    def test_paid_handoff_requires_exhaustion_and_authorization(self, exhausted: bool, authorized: bool) -> None:
        grant = self.claim()
        record_llm_spend(
            "cost",
            team_id=self.team.id,
            signal_id=str(uuid4()),
            stage="research",
            token_cost_microusd=10_000_000 if exhausted else 9_999_999,
            trial_grant_id=str(grant.id),
        )
        admission = OperationAdmission(operation_key="next", stage=SignalTrialOperation.Stage.SCOUT)
        if exhausted and not authorized:
            with self.assertRaisesMessage(TrialRefused, "cost_limit"):
                self.policy.admit(admission, paid_authorized=authorized)
        else:
            operation = self.policy.admit(admission, paid_authorized=authorized)
            assert operation.funding == ("paid" if exhausted else "trial")

    def test_one_allowance_includes_late_costs_failed_runs_and_all_stages(self) -> None:
        grant = self.claim()
        signal_id = str(uuid4())
        for stage, cost in [("scout", 3_000_001), ("research", 4_000_002), ("implementation", 3_000_003)]:
            record_llm_spend(
                stage,
                team_id=self.team.id,
                signal_id=signal_id,
                stage=stage,
                token_cost_microusd=cost,
                trial_grant_id=str(grant.id),
            )
        grant.refresh_from_db()
        assert grant.settled_microusd == 10_000_006
        assert grant.exhaustion_reason == "cost_limit"
        self.flag_mock.return_value = False
        for _ in range(2):
            record_llm_spend(
                "implementation",
                team_id=self.team.id,
                signal_id=signal_id,
                stage="implementation",
                token_cost_microusd=4_000_003,
            )
        grant.refresh_from_db()
        assert grant.settled_microusd == 11_000_006
        assert grant.exhaustion_reason == "cost_limit"
        assert not SignalTrialReportReservation.objects.for_team(self.team.id).exists()

    def test_missing_cost_pauses_admission_then_recovers_without_regrant(self) -> None:
        grant = self.claim()
        signal_id = str(uuid4())
        record_llm_spend(
            "late",
            team_id=self.team.id,
            signal_id=signal_id,
            stage="short",
            token_cost_microusd=None,
            trial_grant_id=str(grant.id),
        )
        SignalTrialGrant.objects.for_team(self.team.id).filter(id=grant.id).update(
            incomplete_since=timezone.now() - timedelta(minutes=3)
        )
        with self.assertRaisesMessage(TrialRefused, "accounting_pending"):
            self.admit()
        record_llm_spend("late", team_id=self.team.id, signal_id=signal_id, stage="short", token_cost_microusd=101)
        assert self.admit().grant_id == grant.id
        grant.refresh_from_db()
        assert grant.incomplete_sources == 0
        assert grant.settled_microusd == 101

    def test_trial_sources_never_bill_but_later_paid_work_on_same_owner_does(self) -> None:
        grant = self.claim()
        signal_id = str(uuid4())
        record_llm_spend(
            "trial",
            team_id=self.team.id,
            signal_id=signal_id,
            stage="short",
            token_cost_microusd=10_000_000,
            trial_grant_id=str(grant.id),
        )
        SignalSpend.objects.for_team(self.team.id).filter(signal_id=signal_id).update(usage_based_billing=True)
        complete_signal_pipeline(team_id=self.team.id, signal_id=signal_id)
        spend = SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id)
        assert spend.billing_amounts == {}
        self.flag_mock.return_value = False
        record_llm_spend(
            "trial", team_id=self.team.id, signal_id=signal_id, stage="short", token_cost_microusd=11_000_000
        )
        record_llm_spend(
            "paid", team_id=self.team.id, signal_id=signal_id, stage="implementation", token_cost_microusd=200_000
        )
        complete_signal_pipeline(team_id=self.team.id, signal_id=signal_id)
        spend.refresh_from_db()
        assert sum(spend.billing_amounts.values()) == 200_000
        assert spend_billing_credits_by_team(
            timezone.now() - timedelta(days=1), timezone.now() + timedelta(days=1)
        ) == {self.team.id: 20}

    def test_tasks_charge_raw_tokens_and_compute_once_without_task_fee(self) -> None:
        from products.tasks.backend.facade.contracts import TaskRunActualCost

        grant = self.claim()
        task = Task.objects.create(team=self.team, title="Trial research", origin_product="signal_report")
        run = task.create_run(_trial_admission=None)
        run.state = {
            "self_driving_funding": {"funding": "trial", "grant_id": str(grant.id)},
            "token_cost": {"model": {"provider": {"cost_microusd": 200_001}}},
            "unprocessed_request_ids": [],
        }
        run.status = TaskRun.Status.FAILED
        run.save(update_fields=["state", "status"])
        signal_id = str(uuid4())
        with patch(
            "products.tasks.backend.facade.billing.get_task_run_actual_cost",
            return_value=TaskRunActualCost(
                token_cost_microusd=200_001, compute_cost_microusd=300_002, complete=True, compute_complete=True
            ),
        ):
            for _ in range(2):
                record_task_spend(team_id=self.team.id, run_id=str(run.id), stage="research", signal_id=signal_id)
        grant.refresh_from_db()
        assert grant.settled_microusd == 500_003
        assert grant.incomplete_sources == 0

    def test_only_executing_research_finishes_after_exhaustion(self) -> None:
        grant = self.claim()
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.IN_PROGRESS)
        research = self.admit(stage=SignalTrialOperation.Stage.RESEARCH, report_id=report.id)
        queued = self.admit(stage=SignalTrialOperation.Stage.RESEARCH, report_id=uuid4())
        implementation = self.admit(stage=SignalTrialOperation.Stage.IMPLEMENTATION)
        scout = self.admit()
        self.policy.start(research.id)
        self.policy.start(implementation.id)
        record_llm_spend(
            "exhaust",
            team_id=self.team.id,
            signal_id=str(uuid4()),
            stage="research",
            token_cost_microusd=10_000_000,
            trial_grant_id=str(grant.id),
        )
        assert self.policy.start(research.id).grant_id == grant.id
        for operation in (queued, implementation, scout):
            operation.refresh_from_db()
            assert operation.cancel_requested_at is not None
            with self.assertRaises(TrialRefused):
                self.policy.start(operation.id)
        report.status = SignalReport.Status.PENDING_INPUT
        report.save(update_fields=["status"])
        assert SignalTrialReportReservation.objects.for_team(self.team.id).get(report_id=report.id).status == "consumed"

    @parameterized.expand([(False, "released"), (True, "consumed")])
    def test_deletion_releases_only_undelivered_report_slots(self, delivered: bool, status: str) -> None:
        self.claim()
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.IN_PROGRESS)
        operation = self.admit(stage=SignalTrialOperation.Stage.REPORT_PASS, report_id=report.id)
        if delivered:
            report.status = SignalReport.Status.READY
            report.save(update_fields=["status"])
        report.status = SignalReport.Status.DELETED
        report.save(update_fields=["status"])
        operation.refresh_from_db()
        assert operation.finished_at is not None
        assert SignalTrialReportReservation.objects.for_team(self.team.id).get(report_id=report.id).status == status

    def test_worker_loss_releases_report_slot_only_after_all_attempt_runs_finish(self) -> None:
        self.claim()
        first, second = self.admit(), self.admit()
        report_id = uuid4()
        self.policy.reserve_direct_report(first.id, report_id)
        self.policy.reserve_direct_report(second.id, report_id)
        self.policy.finish(first.id)
        self.policy.release_abandoned_report_attempts(first)
        slot = SignalTrialReportReservation.objects.for_team(self.team.id).get(report_id=report_id)
        assert slot.status == "reserved"
        self.policy.finish(second.id)
        self.policy.release_abandoned_report_attempts(second)
        slot.refresh_from_db()
        assert slot.status == "released"
        assert slot.active_attempts == 0

    def test_late_child_environment_cost_recovers_against_original_grant(self) -> None:
        grant = self.claim()
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child")
        task = Task.objects.create(team=child, title="Child trial", origin_product="signal_report")
        run = task.create_run(_trial_admission=None)
        run.state["self_driving_funding"] = {"funding": "trial", "grant_id": str(grant.id)}
        run.status = TaskRun.Status.FAILED
        run.save(update_fields=["state", "status"])
        signal_id = str(uuid4())
        with patch(
            "products.tasks.backend.facade.billing.get_task_run_actual_cost",
            return_value=TaskRunActualCost(
                token_cost_microusd=10, compute_cost_microusd=None, complete=False, compute_complete=False
            ),
        ):
            record_task_spend(team_id=child.id, run_id=str(run.id), stage="research", signal_id=signal_id)
        spend = SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id)
        assert spend.team_id == self.team.id
        with (
            patch(
                "products.tasks.backend.facade.billing.get_task_run_actual_cost",
                return_value=TaskRunActualCost(
                    token_cost_microusd=20, compute_cost_microusd=30, complete=True, compute_complete=True
                ),
            ),
            patch("products.signals.backend.spend_recovery.process_pending_gateway_usage") as pending,
        ):
            recover_spend(self.team.id, str(spend.id))
        pending.assert_called_once_with(run_id=run.id, team_id=child.id)
        grant.refresh_from_db()
        assert grant.settled_microusd == 50
        assert grant.incomplete_sources == 0

    def test_terminal_accounting_failure_remains_eligible_for_retry(self) -> None:
        self.claim()
        task = Task.objects.create(team=self.team, title="Trial implementation", origin_product="signal_report")
        run = task.create_run()
        run.status = TaskRun.Status.FAILED
        run.save(update_fields=["status"])
        operation = SignalTrialOperation.objects.for_team(self.team.id).get(task_run_id=run.id)
        with (
            patch("products.signals.backend.trial.tasks.process_pending_gateway_usage"),
            patch("products.signals.backend.trial.tasks.refresh_task_spend"),
            patch("products.signals.backend.trial.tasks.complete_task_spend", side_effect=[False, True, True]),
        ):
            reconcile_trial_operation(self.team.id, str(operation.id))
            operation.refresh_from_db()
            assert operation.finished_at is None
            with patch.object(
                TrialPolicy, "release_abandoned_report_attempts", side_effect=RuntimeError("cleanup failed")
            ):
                with self.assertRaisesMessage(RuntimeError, "cleanup failed"):
                    reconcile_trial_operation(self.team.id, str(operation.id))
            operation.refresh_from_db()
            assert operation.finished_at is None
            reconcile_trial_operation(self.team.id, str(operation.id))
        operation.refresh_from_db()
        assert operation.finished_at is not None

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
        operation = SignalTrialOperation.objects.for_team(self.team.id).get(task_run_id=run.id)
        assert (operation.model, operation.runtime) == (model, runtime)

    def test_cost_exhaustion_cancels_implementation_with_existing_pr(self) -> None:
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
        with patch("products.signals.backend.trial.tasks.cancel_task_run", return_value=("accepted", None)) as cancel:
            cancel_trial_grant(self.team.id, str(grant.id))
        assert cancel.call_args.args[:3] == (run.id, task.id, self.team.id)
        run.refresh_from_db()
        assert run.output["pr_url"] == "https://github.com/example/repository/pull/1"

    def test_http_failure_preserves_gateway_receipt_and_charges_failed_attempt(self) -> None:
        grant = self.claim()
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
            "products.signals.backend.llm_spend.fetch_gateway_cost",
            new=AsyncMock(return_value=GatewayRequestCost(model="model", provider="provider", cost_microusd=123)),
        ):
            with self.assertRaises(APIStatusError):
                async_to_sync(generate_with_spend)(
                    generation(),
                    gateway=AIGatewayConfig(url="https://gateway.example.com/v1", api_key="test-key"),
                    team_id=self.team.id,
                    signal_id=str(uuid4()),
                    stage="summarization",
                )
        grant.refresh_from_db()
        assert grant.incomplete_sources == 0
        assert grant.settled_microusd == 123

    def test_claimed_one_time_trial_uses_new_pricing_without_changing_legacy_flag(self) -> None:
        assert usage_billing_enabled(self.team.id) is False
        self.claim()
        assert usage_billing_enabled(self.team.id) is True

    def test_lost_response_can_recover_from_verified_gateway_receipt(self) -> None:
        grant = self.claim()
        signal_id, source_id = str(uuid4()), f"generation:{uuid4()}"
        record_llm_spend(
            None,
            team_id=self.team.id,
            signal_id=signal_id,
            stage="short",
            token_cost_microusd=None,
            source_id=source_id,
            trial_grant_id=str(grant.id),
        )
        spend = SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id)
        with (
            patch(
                "products.signals.backend.management.commands.recover_signal_spend.resolve_ai_gateway_config",
                return_value=AIGatewayConfig(url="https://gateway.example.com/v1", api_key="test-key"),
            ),
            patch(
                "products.signals.backend.management.commands.recover_signal_spend.fetch_gateway_cost",
                new=AsyncMock(return_value=GatewayRequestCost(model="model", provider="provider", cost_microusd=123)),
            ),
        ):
            call_command(
                "recover_signal_spend",
                team_id=self.team.id,
                spend_id=str(spend.id),
                source_id=source_id,
                request_id="recovered-request",
            )
        grant.refresh_from_db()
        assert grant.settled_microusd == 123
        assert grant.incomplete_sources == 0
