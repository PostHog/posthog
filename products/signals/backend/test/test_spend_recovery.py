from uuid import UUID, uuid4

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from django.core.cache import cache
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized

from posthog.llm.gateway_usage import GatewayRequestCost
from posthog.models import Team

from products.signals.backend.models import SignalReport, SignalSpend
from products.signals.backend.spend import complete_signal_pipeline, record_llm_spend
from products.signals.backend.spend_recovery import RECOVERY_SOURCE_LIMIT, recover_incomplete_spend, recover_spend
from products.signals.backend.trial.models import SignalTrialGrant, SignalTrialReportReservation
from products.signals.backend.trial.policy import TrialPolicy
from products.signals.backend.trial.tasks import REPORT_RESERVATION_RECOVERY_CURSOR_KEY
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
        historical = TaskRun.objects.bulk_create(
            [TaskRun(team=self.team, task=task, status=TaskRun.Status.FAILED) for _ in range(50)]
        )
        slot.attempt_run_ids += [run.id for run in historical]
        slot.save(update_fields=["attempt_run_ids"])
        with patch("products.signals.backend.spend_recovery.recover_spend.apply_async"):
            with CaptureQueriesContext(connection) as queries:
                recover_incomplete_spend()
            assert len(queries) < 20
        slot.refresh_from_db()
        assert slot.status == "released"
        assert slot.active_attempts == 0

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

    @override_settings(AI_GATEWAY_URL="https://gateway.example.com/v1", AI_GATEWAY_API_KEY="test-key")
    def test_recovery_rotates_pending_requests_and_settles_once(self) -> None:
        grant = self.claim()
        signal_id = str(uuid4())
        for index in range(RECOVERY_SOURCE_LIMIT + 1):
            record_llm_spend(
                f"request-{index:02}",
                team_id=self.team.id,
                signal_id=signal_id,
                stage="short",
                token_cost_microusd=None,
                source_id=f"source-{index:02}",
                trial_grant_id=str(grant.id),
                strict=True,
            )
        complete_signal_pipeline(team_id=self.team.id, signal_id=signal_id)
        spend = SignalSpend.objects.for_team(self.team.id).get(signal_id=signal_id)
        with (
            patch("products.signals.backend.spend_recovery.fetch_gateway_cost", new_callable=AsyncMock) as fetch,
            patch(
                "products.signals.backend.spend_recovery.submit_signal_metadata_updates", new_callable=AsyncMock
            ) as publish,
        ):
            fetch.return_value = None
            recover_spend(self.team.id, str(spend.id))
            assert fetch.call_count == RECOVERY_SOURCE_LIMIT
            publish.assert_not_awaited()
            fetch.reset_mock()
            fetch.return_value = GatewayRequestCost(model="example", provider="example", cost_microusd=123)
            recover_spend(self.team.id, str(spend.id))
            assert fetch.call_args_list[0].args[0] == f"request-{RECOVERY_SOURCE_LIMIT:02}"
            recover_spend(self.team.id, str(spend.id))
            recover_spend(self.team.id, str(spend.id))
            assert publish.await_count == 2
            publish.assert_awaited_with(team_id=self.team.id, signal_ids=[signal_id])
        grant.refresh_from_db()
        spend.refresh_from_db()
        assert grant.settled_microusd == 123 * (RECOVERY_SOURCE_LIMIT + 1)
        assert grant.incomplete_sources == 0
        assert spend.finalized_at is not None

    @parameterized.expand([(True,), (False,)])
    def test_late_child_environment_cost_recovers_against_original_grant(self, terminal: bool) -> None:
        grant = self.claim()
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child")
        report = SignalReport.objects.create(team=child, triggering_signal_id=uuid4())
        task = Task.objects.create(
            team=child, title="Child trial", origin_product="signal_report", signal_report=report
        )
        run = task.create_run(
            environment=TaskRun.Environment.CLOUD,
            extra_state={"ai_stage": "research", "unprocessed_request_ids": ["late"]},
        )
        run.status = TaskRun.Status.FAILED if terminal else TaskRun.Status.IN_PROGRESS
        run.save(update_fields=["status"])
        spend = SignalSpend.objects.for_team(child.id).get(task_run_id=run.id)
        with (
            patch(
                "products.tasks.backend.logic.services.gateway_usage._fetch_gateway_cost",
                new_callable=AsyncMock,
                return_value=GatewayRequestCost(model="example", provider="example", cost_microusd=20),
            ),
            patch("products.signals.backend.spend.submit_signal_metadata_updates", new_callable=AsyncMock),
            patch("products.signals.backend.spend_recovery.recover_spend.apply_async") as dispatch,
        ):
            recover_incomplete_spend()
            args = next(
                call.kwargs["args"] for call in dispatch.call_args_list if call.kwargs["args"][1] == str(spend.id)
            )
            assert args[0] == self.team.id
            recover_spend(*args)
            recover_spend(*args)
        grant.refresh_from_db()
        assert grant.settled_microusd == 40_020
        assert grant.incomplete_sources == 0
