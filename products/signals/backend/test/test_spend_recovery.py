from datetime import timedelta
from uuid import UUID, uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team

from products.signals.backend.facade.trial import start_task_trial
from products.signals.backend.models import SignalSpend
from products.signals.backend.spend import record_llm_spend, record_task_spend
from products.signals.backend.spend_recovery import recover_incomplete_spend, recover_spend
from products.signals.backend.trial.models import SignalTrialGrant, SignalTrialReportReservation
from products.signals.backend.trial.policy import TrialPolicy
from products.signals.backend.trial.tasks import REPORT_RESERVATION_RECOVERY_CURSOR_KEY
from products.tasks.backend.facade.contracts import TaskRunActualCost
from products.tasks.backend.logic.services.gateway_usage import record_gateway_routing
from products.tasks.backend.models import Task, TaskRun


class TestTrialSpendRecovery(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag = patch("products.signals.backend.trial.policy.posthoganalytics.feature_enabled", return_value=True)
        self.flag.start()
        self.addCleanup(self.flag.stop)
        self.policy = TrialPolicy(self.team)
        cache.delete(REPORT_RESERVATION_RECOVERY_CURSOR_KEY)
        self.addCleanup(cache.delete, REPORT_RESERVATION_RECOVERY_CURSOR_KEY)

    def claim(self) -> SignalTrialGrant:
        return self.policy.claim(user_id=self.user.pk)

    def test_failed_cost_notification_keeps_settled_receipt_recoverable(self) -> None:
        grant = self.claim()
        task = Task.objects.create(team=self.team, title="Late usage", origin_product="signal_report")
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.FAILED,
            state={
                "sandbox_provisioning_started": False,
                "self_driving_funding": {"funding": "trial", "grant_id": str(grant.id)},
            },
        )
        record_task_spend(team_id=self.team.id, run_id=str(run.id), stage="research", signal_id=str(uuid4()))
        spend = SignalSpend.objects.for_team(self.team.id).get(task_ids__contains=[task.id])
        self.assertFalse(spend.accounting_failed)
        with (
            patch("products.signals.backend.spend.refresh_task_spend", side_effect=RuntimeError("callback failed")),
            self.captureOnCommitCallbacks(execute=True),
        ):
            record_gateway_routing(run_id=run.id, team_id=self.team.id, uses_gateway=True)
        spend.refresh_from_db()
        self.assertTrue(spend.accounting_failed)
        with patch(
            "products.tasks.backend.facade.billing.get_task_run_actual_cost",
            return_value=TaskRunActualCost(
                token_cost_microusd=100, compute_cost_microusd=200, complete=True, compute_complete=True
            ),
        ):
            recover_spend(self.team.id, str(spend.id))
            recover_spend(self.team.id, str(spend.id))
        spend.refresh_from_db()
        self.assertFalse(spend.accounting_failed)
        grant.refresh_from_db()
        assert grant.settled_microusd == 300

    def test_worker_loss_releases_report_slot_only_after_all_attempt_runs_finish(self) -> None:
        self.claim()
        task = Task.objects.create(team=self.team, title="Scout attempts", origin_product="signals_scout")
        first, second = task.create_run(), task.create_run()
        funding = self.policy.admit(paid_authorized=False)
        report_id = uuid4()
        self.policy.reserve_direct_report(funding, report_id, run_id=first.id)
        self.policy.reserve_direct_report(funding, report_id, run_id=second.id)
        with self.captureOnCommitCallbacks(execute=True):
            first.status = TaskRun.Status.FAILED
            first.save(update_fields=["status"])
        slot = SignalTrialReportReservation.objects.for_team(self.team.id).get(report_id=report_id)
        assert slot.status == "reserved"
        # Bulk terminalization bypasses post_save; shared recovery still releases the slot.
        TaskRun.objects.filter(id=second.id).update(status=TaskRun.Status.FAILED)
        with patch("products.signals.backend.spend_recovery.recover_spend.apply_async"):
            recover_incomplete_spend()
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
            patch("products.tasks.backend.facade.billing.process_pending_gateway_usage") as pending,
        ):
            recover_spend(self.team.id, str(spend.id))
        pending.assert_called_once_with(run_id=run.id, team_id=child.id, limit=1000)
        grant.refresh_from_db()
        assert grant.settled_microusd == 50
        assert grant.incomplete_sources == 0

    @parameterized.expand([("active_owners", True), ("deleted_team", False)])
    def test_reservation_scan_advances_past_full_batch_and_wraps(self, _name: str, team_exists: bool) -> None:
        grant = self.claim()
        task = Task.objects.create(team=self.team, title="Recovery scan", origin_product="signals_scout")
        active, abandoned = task.create_run(), task.create_run()
        TaskRun.objects.filter(id=abandoned.id).update(status=TaskRun.Status.FAILED)
        reservations = [
            SignalTrialReportReservation(
                id=UUID(int=index + 1),
                team_id=self.team.id if team_exists else -1,
                grant=grant,
                report_id=uuid4(),
                active_attempts=1,
                attempt_run_ids=[active.id],
            )
            for index in range(100)
        ]
        last = SignalTrialReportReservation(
            id=UUID(int=101),
            team_id=self.team.id,
            grant=grant,
            report_id=uuid4(),
            active_attempts=1,
            attempt_run_ids=[abandoned.id],
        )
        SignalTrialReportReservation.objects.bulk_create([*reservations, last])
        with patch("products.signals.backend.spend_recovery.recover_spend.apply_async"):
            recover_incomplete_spend()
            last.refresh_from_db()
            assert last.status == SignalTrialReportReservation.Status.RESERVED
            recover_incomplete_spend()
            last.refresh_from_db()
            assert last.status == SignalTrialReportReservation.Status.RELEASED
            assert last.active_attempts == 0
            TaskRun.objects.filter(id=active.id).update(status=TaskRun.Status.FAILED)
            recover_incomplete_spend()
        remaining = SignalTrialReportReservation.objects.unscoped().filter(
            status=SignalTrialReportReservation.Status.RESERVED
        )
        assert remaining.count() == (0 if team_exists else 100)

    def test_recovery_sweep_skips_legacy_failures_without_using_its_batch_budget(self) -> None:
        SignalSpend.objects.bulk_create(
            [SignalSpend(team=self.team, signal_id=uuid4(), accounting_failed=True) for _ in range(100)]
        )
        SignalSpend.objects.for_team(self.team.id).update(updated_at=timezone.now() - timedelta(days=1))
        grant = self.claim()
        signal_id = uuid4()
        record_llm_spend(
            "pending-cost",
            team_id=self.team.id,
            signal_id=str(signal_id),
            stage="research",
            token_cost_microusd=None,
            trial_grant_id=str(grant.id),
        )
        pending = SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id)
        with patch("products.signals.backend.spend_recovery.recover_spend.apply_async") as dispatch:
            recover_incomplete_spend()
        dispatch.assert_called_once_with(args=(self.team.id, str(pending.id)), expires=60)

    def test_terminal_accounting_failure_recovers_from_pre_execution_receipt(self) -> None:
        grant = self.claim()
        task = Task.objects.create(team=self.team, title="Trial implementation", origin_product="signal_report")
        run = task.create_run()
        assert start_task_trial(team=self.team, run_id=run.id)
        spend = SignalSpend.objects.for_team(self.team.id).get(task_ids__contains=[task.id])
        self.assertTrue(spend.accounting_failed)
        TaskRun.objects.filter(id=run.id).update(status=TaskRun.Status.FAILED)
        with patch(
            "products.tasks.backend.facade.billing.get_task_run_actual_cost",
            return_value=TaskRunActualCost(
                token_cost_microusd=100, compute_cost_microusd=None, complete=False, compute_complete=False
            ),
        ):
            recover_spend(self.team.id, str(spend.id))
        spend.refresh_from_db()
        self.assertTrue(spend.accounting_failed)
        assert spend.trial_sources[f"task:{run.id}"]["actual_cost_incomplete"]
        with patch(
            "products.tasks.backend.facade.billing.get_task_run_actual_cost",
            return_value=TaskRunActualCost(
                token_cost_microusd=100, compute_cost_microusd=200, complete=True, compute_complete=True
            ),
        ):
            recover_spend(self.team.id, str(spend.id))
        spend.refresh_from_db()
        assert not spend.trial_sources[f"task:{run.id}"]["actual_cost_incomplete"]
        self.assertFalse(spend.accounting_failed)
        grant.refresh_from_db()
        assert grant.settled_microusd == 300
