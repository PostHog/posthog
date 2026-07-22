from unittest.mock import patch

from django.test import TestCase

from posthog.models import Organization, Team, User

from products.tasks.backend.loop_reconciliation import reconcile_loop_trigger_schedules
from products.tasks.backend.models import Loop, LoopTrigger

RECONCILIATION_MODULE = "products.tasks.backend.loop_reconciliation"


class TestReconcileLoopTriggerSchedules(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(email="loop-owner@example.com", first_name="Loop", password="password")
        self.loop = Loop.objects.unscoped().create(
            team=self.team,
            created_by=self.user,
            name="Daily digest",
            instructions="Summarize",
            runtime_adapter="claude",
            model="claude-sonnet-5",
        )

    def _trigger(self, status_value, *, type_value=LoopTrigger.TriggerType.SCHEDULE) -> LoopTrigger:
        return LoopTrigger.objects.unscoped().create(
            team=self.team,
            loop=self.loop,
            type=type_value,
            enabled=True,
            config={"cron_expression": "0 9 * * *", "timezone": "UTC"},
            schedule_sync_status=status_value,
        )

    def test_re_syncs_only_pending_and_failed_schedule_triggers(self):
        pending = self._trigger(LoopTrigger.ScheduleSyncStatus.PENDING)
        failed = self._trigger(LoopTrigger.ScheduleSyncStatus.FAILED)
        self._trigger(LoopTrigger.ScheduleSyncStatus.SYNCED)
        # A pending non-schedule trigger has no Temporal schedule to reconcile.
        self._trigger(LoopTrigger.ScheduleSyncStatus.PENDING, type_value=LoopTrigger.TriggerType.API)

        with patch(f"{RECONCILIATION_MODULE}.sync_loop_trigger_schedule") as mock_sync:
            reconciled = reconcile_loop_trigger_schedules()

        self.assertEqual(reconciled, 2)
        synced_ids = {call.args[0].id for call in mock_sync.call_args_list}
        self.assertEqual(synced_ids, {pending.id, failed.id})

    def test_skips_pending_triggers_on_a_soft_deleted_loop(self):
        # A soft-deleted loop's schedule was torn down on delete; reconciliation must never recreate
        # it, or a deleted loop leaves a zombie Temporal Schedule firing forever.
        deleted_loop = Loop.objects.unscoped().create(
            team=self.team,
            created_by=self.user,
            name="Gone",
            instructions="x",
            runtime_adapter="claude",
            model="claude-sonnet-5",
            deleted=True,
        )
        LoopTrigger.objects.unscoped().create(
            team=self.team,
            loop=deleted_loop,
            type=LoopTrigger.TriggerType.SCHEDULE,
            enabled=True,
            config={"cron_expression": "0 9 * * *", "timezone": "UTC"},
            schedule_sync_status=LoopTrigger.ScheduleSyncStatus.PENDING,
        )
        live = self._trigger(LoopTrigger.ScheduleSyncStatus.PENDING)

        with patch(f"{RECONCILIATION_MODULE}.sync_loop_trigger_schedule") as mock_sync:
            reconciled = reconcile_loop_trigger_schedules()

        self.assertEqual(reconciled, 1)
        synced_ids = {call.args[0].id for call in mock_sync.call_args_list}
        self.assertEqual(synced_ids, {live.id})
