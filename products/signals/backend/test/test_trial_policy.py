from datetime import timedelta
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import BaseTest, NonAtomicBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.apps import apps
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from asgiref.sync import async_to_sync
from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.llm.gateway_client import GatewayNotConfiguredError
from posthog.models import Team

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.emission.pipeline import LLM_MODEL, _create_message
from products.signals.backend.free_trial import self_driving_free_trial_enabled
from products.signals.backend.models import SignalReport, SignalScoutConfig
from products.signals.backend.quota import self_driving_quota_gate
from products.signals.backend.report_generation.research import ReportLayer
from products.signals.backend.stack_plan import create_layer_reports
from products.signals.backend.trial_gateway import TrialGatewayCost
from products.signals.backend.trial_models import (
    SignalTrialGrant,
    SignalTrialOperation,
    SignalTrialOrganization,
    SignalTrialReportReservation,
)
from products.signals.backend.trial_policy import OperationAdmission, TrialPolicy, TrialRefused
from products.signals.backend.trial_reports import active_report_pass
from products.signals.backend.trial_tasks import cancel_trial_operation, reconcile_trial_operation, reconcile_trials
from products.tasks.backend.facade.run_config import get_default_model_for_runtime_adapter


@override_settings(SELF_DRIVING_TRIAL_V2_BILLING_READY=True)
class TestTrialPolicy(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag = patch("products.signals.backend.trial_policy.posthoganalytics.feature_enabled", return_value=True)
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
            OperationAdmission(
                operation_key=str(uuid4()), stage=stage, estimated_microusd=100_000, report_id=report_id
            ),
            paid_authorized=False,
        )

    def test_duplicate_and_child_activation_share_lifetime_grant(self) -> None:
        grant = self.claim()
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child")
        assert TrialPolicy(child).claim(user_id=self.user.pk).id == grant.id
        assert self.policy.claim(user_id=self.user.pk).id == grant.id
        assert SignalTrialOrganization.objects.get(organization_id=self.organization.pk).grants_claimed == 1

    @parameterized.expand([(True, False), (True, True), (False, False), (False, True)])
    def test_claimed_trial_replaces_legacy_pr_restriction(self, enabled: bool, exhausted: bool) -> None:
        grant = self.claim()
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child")
        unclaimed = Team.objects.create(organization=self.organization, name="Unclaimed")
        if exhausted:
            SignalTrialGrant.objects.for_team(self.team.id).filter(id=grant.id).update(
                exhausted_at=timezone.now(), exhaustion_reason="report_limit"
            )
        self.flag_mock.side_effect = lambda key, *args, **kwargs: (
            enabled if key == "self-driving-free-tier-v2" else True
        )
        assert self_driving_free_trial_enabled(self.team) is not enabled
        assert self_driving_free_trial_enabled(child) is not enabled
        assert self_driving_free_trial_enabled(unclaimed) is True

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

    @parameterized.expand([(True, SignalReport.Status.POTENTIAL), (False, SignalReport.Status.READY)])
    def test_report_pass_ends_without_leaking_slot_or_funding(self, trial: bool, status: str) -> None:
        if trial:
            self.claim()
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.IN_PROGRESS)
        operation = self.policy.admit(
            OperationAdmission(
                operation_key=str(uuid4()),
                stage=SignalTrialOperation.Stage.REPORT_PASS,
                report_id=report.id,
                estimated_microusd=100_000,
            ),
            paid_authorized=True,
        )
        report.status = status
        report.save(update_fields=["status"])
        assert active_report_pass(self.team, report.id) is None
        operation.refresh_from_db()
        assert operation.finished_at is not None
        if trial:
            slot = SignalTrialReportReservation.objects.for_team(self.team.id).get(report_id=report.id)
            assert slot.status == SignalTrialReportReservation.Status.RELEASED
            assert operation.reserved_microusd == 100_000
        else:
            self.claim()
            assert self.admit(stage=SignalTrialOperation.Stage.IMPLEMENTATION, report_id=report.id).grant_id is not None

    @parameterized.expand(
        [
            (SignalTrialOperation.Funding.PAID, SignalReport.Status.READY),
            (SignalTrialOperation.Funding.PAID, SignalReport.Status.PENDING_INPUT),
            (SignalTrialOperation.Funding.EXISTING, SignalReport.Status.READY),
            (SignalTrialOperation.Funding.EXISTING, SignalReport.Status.PENDING_INPUT),
        ]
    )
    def test_nontrial_pass_can_publish_after_released_trial_pass(self, funding: str, status: str) -> None:
        grant = self.claim()
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.IN_PROGRESS)
        self.admit(stage=SignalTrialOperation.Stage.REPORT_PASS, report_id=report.id)
        report.status = SignalReport.Status.POTENTIAL
        report.save(update_fields=["status"])

        report.status = status
        with self.assertRaisesMessage(TrialRefused, "report_reservation_released"):
            report.save(update_fields=["status"])

        SignalTrialGrant.objects.for_team(self.team.id).filter(id=grant.id).update(
            exhausted_at=timezone.now(), exhaustion_reason="cost_limit"
        )
        self.flag_mock.return_value = funding == SignalTrialOperation.Funding.PAID
        operation = self.policy.admit(
            OperationAdmission(
                operation_key=str(uuid4()),
                stage=SignalTrialOperation.Stage.REPORT_PASS,
                report_id=report.id,
                estimated_microusd=100_000,
            ),
            paid_authorized=True,
        )
        assert operation.funding == funding
        report.status = SignalReport.Status.IN_PROGRESS
        report.save(update_fields=["status"])
        report.status = status
        report.save(update_fields=["status"])
        report.save(update_fields=["status"])

        report.refresh_from_db()
        assert report.status == status
        assert active_report_pass(self.team, report.id) is None
        operation.refresh_from_db()
        assert operation.finished_at is not None
        slot = SignalTrialReportReservation.objects.for_team(self.team.id).get(report_id=report.id)
        assert slot.status == SignalTrialReportReservation.Status.RELEASED
        assert slot.consumed_at is None

    @parameterized.expand([(4, 4), (5, 0)])
    def test_stack_layers_share_report_ceiling(self, count: int, delivered: int) -> None:
        self.claim()
        parent = SignalReport.objects.create(team=self.team, status=SignalReport.Status.IN_PROGRESS)
        self.admit(stage=SignalTrialOperation.Stage.REPORT_PASS, report_id=parent.id)
        parent.status = SignalReport.Status.READY
        parent.save(update_fields=["status"])
        children = create_layer_reports(
            parent=parent,
            layers=[ReportLayer(title=f"Layer {i}", scope="Implement this step") for i in range(count)],
            attribution=ArtefactAttribution.system(),
        )
        assert len(children) == delivered
        assert SignalReport.objects.filter(team=self.team, status=SignalReport.Status.READY).count() == delivered + 1
        assert (
            SignalTrialReportReservation.objects.for_team(self.team.id).filter(status="consumed").count()
            == delivered + 1
        )
        assert not SignalTrialReportReservation.objects.for_team(self.team.id).filter(status="reserved").exists()

    def test_billing_outage_pauses_new_work_without_breaking_quota_status(self) -> None:
        with patch("products.signals.backend.trial_billing.TrialBilling.status", side_effect=TimeoutError):
            gate = self_driving_quota_gate(self.team)
        assert gate.limited and gate.enforced

    @parameterized.expand([(True,), (False,)])
    def test_cancelled_unprovisioned_run_releases_only_a_complete_reservation(self, gateway_complete: bool) -> None:
        grant = self.claim()
        operation = self.admit(stage=SignalTrialOperation.Stage.IMPLEMENTATION)
        task_model = apps.get_model("tasks", "Task")
        task = task_model.objects.create(team=self.team, title="Queued implementation", origin_product="signal_report")
        run = task.create_run(_trial_admission=None)
        run.status = "cancelled"
        run.save(update_fields=["status"])
        operation.task_run_id = run.id
        operation.save(update_fields=["task_run_id"])

        with patch(
            "products.signals.backend.trial_tasks.fetch_trial_gateway_cost",
            return_value=TrialGatewayCost(token_cost_microusd=0, complete=gateway_complete),
        ):
            reconcile_trial_operation(self.team.id, str(operation.id))
            reconcile_trial_operation(self.team.id, str(operation.id))

        operation.refresh_from_db()
        grant.refresh_from_db()
        assert operation.accounting_complete is gateway_complete
        assert operation.reserved_microusd == (0 if gateway_complete else 100_000)
        assert grant.reserved_microusd == operation.reserved_microusd
        assert grant.settled_microusd == 0

    def test_recovery_leases_lost_jobs_and_recovers_late_costs(self) -> None:
        self.claim()
        operation = self.admit()
        self.policy.finish(operation.id)
        with (
            time_machine.travel(timezone.now(), tick=False) as clock,
            patch("products.signals.backend.trial_tasks.reconcile_trial_operation.apply_async") as enqueue,
        ):
            reconcile_trials()
            reconcile_trials()
            assert enqueue.call_count == 1
            clock.shift(timedelta(minutes=5))
            reconcile_trials()
            assert enqueue.call_count == 2
            with patch("products.signals.backend.trial_tasks.fetch_trial_gateway_cost", return_value=None):
                reconcile_trial_operation(self.team.id, str(operation.id))
            operation.refresh_from_db()
            assert not operation.accounting_complete
            assert operation.reserved_microusd == 100_000
            clock.shift(timedelta(minutes=1))
            reconcile_trials()
            assert enqueue.call_count == 3
            with patch(
                "products.signals.backend.trial_tasks.fetch_trial_gateway_cost",
                return_value=TrialGatewayCost(token_cost_microusd=12_345, complete=True),
            ):
                reconcile_trial_operation(self.team.id, str(operation.id))
            operation = SignalTrialOperation.objects.for_team(self.team.id).get(id=operation.id)
            assert operation.accounting_complete
            assert operation.reserved_microusd == 0
            clock.shift(timedelta(minutes=1))
            reconcile_trials()
            assert enqueue.call_count == 3
            clock.shift(timedelta(days=1))
            reconcile_trials()
            assert enqueue.call_count == 4

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

    @parameterized.expand([(False,), (True,)])
    def test_exhaustion_cancels_implementation_and_preserves_existing_pr(self, has_pr: bool) -> None:
        self.claim()
        operation = self.admit(stage=SignalTrialOperation.Stage.IMPLEMENTATION)
        task_model = apps.get_model("tasks", "Task")
        run_model = apps.get_model("tasks", "TaskRun")
        task = task_model.objects.create(team=self.team, title="Implementation", origin_product="signal_report")
        output = {"pr_url": "https://github.com/example/project/pull/1"} if has_pr else {}
        run = run_model.objects.create(team=self.team, task=task, status="in_progress", output=output)
        operation.task_run_id = run.id
        operation.save(update_fields=["task_run_id"])
        self.policy.reconcile(
            operation_id=operation.id,
            source_id="implementation-cost",
            is_task=True,
            token_cost_microusd=10_000_001,
            compute_cost_microusd=0,
            complete=False,
        )
        operation.refresh_from_db()
        with (
            patch("products.tasks.backend.facade.cancellation._interrupt_agent_turn"),
            patch("products.tasks.backend.facade.cancellation._signal_complete_task", return_value="signaled"),
        ):
            cancel_trial_operation(operation)
        operation.refresh_from_db()
        run.refresh_from_db()
        assert operation.cancelled_at is not None
        assert run.state["cancel_source"] == "self_driving_trial"
        assert run.output == output
        assert task_model.objects.filter(id=task.id).exists()

    def test_gateway_remint_reserves_another_cap_and_cannot_reuse_exhausted_allowance(self) -> None:
        grant = self.claim()
        operation = self.admit()
        self.policy.reserve_task_gateway(operation.id, 6_000_000)
        self.policy.reserve_task_gateway(operation.id, 6_000_000)
        grant.refresh_from_db()
        assert grant.reserved_microusd == 6_100_000
        with self.assertRaisesMessage(TrialRefused, "allowance_reserved"):
            self.policy.reserve_task_gateway(operation.id, 6_000_000)

    @parameterized.expand(
        [({}, "claude", None), ({"runtime_adapter": "codex", "model": "gpt-6.1-sol"}, "codex", "gpt-6.1-sol")]
    )
    def test_implementation_keeps_existing_model_selection(
        self, selection: dict[str, str], runtime: str, model: str | None
    ) -> None:
        self.claim()
        task = apps.get_model("tasks", "Task").objects.create(
            team=self.team,
            title="Implementation",
            origin_product="signal_report",
            internal=True,
        )
        run = task.create_run(extra_state={"ai_stage": "implementation", **selection})
        operation = SignalTrialOperation.objects.for_team(self.team.id).get(task_run_id=run.id)
        assert operation.stage == SignalTrialOperation.Stage.IMPLEMENTATION
        assert operation.model == run.state["model"] == (model or get_default_model_for_runtime_adapter(runtime))
        assert operation.runtime == run.state["runtime_adapter"] == runtime

    def test_admitted_report_pass_keeps_trial_funding_after_flag_off(self) -> None:
        self.claim()
        report = uuid4()
        parent = self.admit(stage=SignalTrialOperation.Stage.REPORT_PASS, report_id=report)
        self.flag_mock.return_value = False
        child = self.policy.admit(
            OperationAdmission(
                operation_key="child",
                stage=SignalTrialOperation.Stage.RESEARCH,
                estimated_microusd=100_000,
                report_id=report,
                report_pass_id=parent.id,
            ),
            paid_authorized=True,
        )
        assert child.funding == SignalTrialOperation.Funding.TRIAL
        assert child.grant_id == parent.grant_id

    def test_late_costs_are_deduplicated_and_keep_overrun_after_flag_off(self) -> None:
        grant = self.claim()
        operation = self.admit()
        self.policy.finish(operation.id)
        for _ in range(2):
            self.policy.reconcile(
                operation_id=operation.id,
                source_id="request-one",
                is_task=False,
                token_cost_microusd=11_000_001,
                compute_cost_microusd=0,
                complete=True,
            )
        self.flag_mock.return_value = False
        grant.refresh_from_db()
        assert grant.settled_microusd == 11_000_001
        assert grant.overrun_microusd == 1_000_001
        assert grant.exhaustion_reason == "cost_limit"
        assert self.policy.claim(user_id=self.user.pk).id == grant.id
        operation.refresh_from_db()
        assert operation.funding == SignalTrialOperation.Funding.TRIAL

    def test_missing_costs_hold_reservation_until_final_accounting(self) -> None:
        grant = self.claim()
        operation = self.admit()
        self.policy.finish(operation.id)
        self.policy.reconcile(
            operation_id=operation.id,
            source_id="request-one",
            is_task=False,
            token_cost_microusd=1,
            compute_cost_microusd=None,
            complete=False,
        )
        grant.refresh_from_db()
        assert grant.settled_microusd == 1
        assert grant.reserved_microusd == 99_999
        self.policy.reconcile(
            operation_id=operation.id,
            source_id="request-one",
            is_task=False,
            token_cost_microusd=2,
            compute_cost_microusd=0,
            complete=True,
        )
        grant.refresh_from_db()
        assert grant.settled_microusd == 2
        assert grant.reserved_microusd == 0

    @parameterized.expand([(True, True), (True, False), (False, True), (False, False)])
    def test_trial_hands_off_only_when_exhausted_and_paid(self, exhausted: bool, authorized: bool) -> None:
        grant = self.claim()
        if exhausted:
            SignalTrialGrant.objects.for_team(self.team.pk).filter(id=grant.id).update(
                exhausted_at=timezone.now(), exhaustion_reason="report_limit"
            )
        else:
            operation = self.admit()
            self.policy.finish(operation.id)
            self.policy.reconcile(
                operation_id=operation.id,
                source_id="settled",
                is_task=False,
                token_cost_microusd=9_700_000,
                compute_cost_microusd=0,
                complete=True,
            )
        admission = OperationAdmission(
            operation_key="next", stage=SignalTrialOperation.Stage.SCOUT, estimated_microusd=1_000_000
        )
        if exhausted and authorized:
            assert self.policy.admit(admission, paid_authorized=True).funding == SignalTrialOperation.Funding.PAID
        else:
            with self.assertRaisesMessage(TrialRefused, "report_limit" if exhausted else "allowance_reserved"):
                self.policy.admit(admission, paid_authorized=authorized)
        grant.refresh_from_db()
        assert (grant.exhausted_at is not None) == exhausted

    def test_executing_research_can_publish_pending_input_after_cost_exhaustion(self) -> None:
        self.claim()
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.IN_PROGRESS)
        operation = self.admit(stage=SignalTrialOperation.Stage.RESEARCH, report_id=report.id)
        self.policy.start(operation.id)
        self.policy.reconcile(
            operation_id=operation.id,
            source_id="research",
            is_task=True,
            token_cost_microusd=11_000_000,
            compute_cost_microusd=0,
            complete=False,
        )
        self.policy.reserve_finalization(operation.id, 100_000)
        report.status = SignalReport.Status.PENDING_INPUT
        report.save(update_fields=["status"])
        slot = SignalTrialReportReservation.objects.for_team(self.team.id).get(report_id=report.id)
        assert slot.status == SignalTrialReportReservation.Status.CONSUMED
        report.refresh_from_db()
        assert report.status == SignalReport.Status.PENDING_INPUT

    def test_exhaustion_preserves_only_executing_research(self) -> None:
        self.claim()
        active = self.admit(stage=SignalTrialOperation.Stage.RESEARCH, report_id=uuid4())
        queued = self.admit(stage=SignalTrialOperation.Stage.RESEARCH, report_id=uuid4())
        implementation = self.admit(stage=SignalTrialOperation.Stage.IMPLEMENTATION)
        scout = self.admit()
        self.policy.start(active.id)
        self.policy.reconcile(
            operation_id=scout.id,
            source_id="task-cost",
            is_task=True,
            token_cost_microusd=10_000_001,
            compute_cost_microusd=0,
            complete=False,
        )
        assert self.policy.start(active.id).funding == SignalTrialOperation.Funding.TRIAL
        for operation in (queued, implementation, scout):
            with self.assertRaises(TrialRefused):
                self.policy.start(operation.id)
        assert active.report_id is not None
        with self.policy.publish_report(active.report_id, delivered=True):
            pass


class TestTrialLLMExecution(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        flag = patch("products.signals.backend.trial_policy.posthoganalytics.feature_enabled", return_value=True)
        flag.start()
        self.addCleanup(flag.stop)
        self.policy = TrialPolicy(self.team)

    @parameterized.expand([(True, False), (True, True), (False, False)])
    @override_settings(
        AI_GATEWAY_URL="https://gateway.example.com/v1",
        AI_GATEWAY_API_KEY="phs_example",
        SELF_DRIVING_TRIAL_V2_BILLING_READY=True,
    )
    def test_emission_uses_trial_token_and_refuses_next_request_after_exhaustion(
        self, gateway_ready: bool, revoke_fails: bool
    ) -> None:
        self.policy.claim(user_id=self.user.pk)
        SignalTrialOrganization.objects.filter(organization_id=self.organization.pk).update(
            billing_migrated_at=timezone.now()
        )
        ordinary = MagicMock()
        ordinary.messages.create = AsyncMock()
        accounted = MagicMock()
        accounted.messages.create = AsyncMock(return_value=MagicMock())
        builder = MagicMock()
        builder.with_options.return_value.__aenter__.return_value = accounted

        def gateway_post(url: str, **kwargs: object) -> MagicMock:
            if not gateway_ready:
                return MagicMock(status_code=401, text="unavailable")
            body = kwargs.get("json")
            assert isinstance(body, dict)
            return MagicMock(
                status_code=200,
                json=lambda: {
                    "token": "phe_example",
                    "trial_funding": body.get("trial_funding"),
                    "revoked": True,
                },
            )

        with (
            patch("posthog.security.outbound_proxy.internal_requests.post", side_effect=gateway_post),
            patch("products.signals.backend.trial_llm_execution.build_async_anthropic_client", return_value=builder),
            patch("products.signals.backend.trial_llm_execution.reconcile_trial_operation.delay"),
            patch(
                "products.signals.backend.trial_llm_execution.revoke_private_gateway_token",
                side_effect=TimeoutError if revoke_fails else None,
            ),
        ):
            if not gateway_ready:
                with self.assertRaises(GatewayNotConfiguredError):
                    async_to_sync(_create_message)(ordinary, team_id=self.team.id, messages=[], extra_headers={})
                failed = SignalTrialOperation.objects.for_team(self.team.id).get(stage=SignalTrialOperation.Stage.SHORT)
                assert failed.finished_at is not None
                assert not failed.accounting_complete
                assert failed.reserved_microusd > 0
                accounted.messages.create.assert_not_called()
                ordinary.messages.create.assert_not_called()
                return
            async_to_sync(_create_message)(ordinary, team_id=self.team.id, messages=[], extra_headers={})
            operation = SignalTrialOperation.objects.for_team(self.team.id).get(stage=SignalTrialOperation.Stage.SHORT)
            assert operation.model == LLM_MODEL
            assert operation.finished_at is not None
            assert operation.funding == SignalTrialOperation.Funding.TRIAL
            self.policy.reconcile(
                operation_id=operation.id,
                source_id="emission",
                is_task=False,
                token_cost_microusd=10_000_000,
                compute_cost_microusd=0,
                complete=True,
            )
            with self.assertRaises(TrialRefused):
                async_to_sync(_create_message)(ordinary, team_id=self.team.id, messages=[], extra_headers={})
        accounted.messages.create.assert_awaited_once()
        ordinary.messages.create.assert_not_called()
