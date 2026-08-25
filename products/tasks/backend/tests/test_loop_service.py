from datetime import timedelta

from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone as django_timezone

from parameterized import parameterized
from temporalio.client import ScheduleOverlapPolicy

from posthog.models import Organization, Team, User

from products.tasks.backend.loop_service import (
    build_loop_trigger_schedule,
    delete_schedules_for_team,
    sync_loop_trigger_schedule,
)
from products.tasks.backend.models import Loop, LoopFire, LoopTrigger
from products.tasks.backend.temporal.loops.activities import run_loop_trigger


class TestLoopService(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(email="loop-owner@example.com", first_name="Loop", password="password")

    def create_loop(self, **overrides) -> Loop:
        defaults = {
            "team": self.team,
            "created_by": self.user,
            "name": "Daily digest",
            "instructions": "Summarize open PRs across the team's repos",
            "runtime_adapter": "claude",
            "model": "claude-sonnet-4-5",
            "enabled": True,
        }
        defaults.update(overrides)
        loop = Loop(**defaults)
        loop.save()
        return loop

    def create_trigger(self, loop: Loop, config: dict, **overrides) -> LoopTrigger:
        defaults = {
            "team": self.team,
            "loop": loop,
            "type": LoopTrigger.TriggerType.SCHEDULE,
            "enabled": True,
            "config": config,
        }
        defaults.update(overrides)
        trigger = LoopTrigger(**defaults)
        trigger.save()
        return trigger

    def test_cron_trigger_schedule_carries_cron_expression_and_timezone(self):
        loop = self.create_loop()
        trigger = self.create_trigger(loop, {"cron_expression": "0 9 * * *", "timezone": "Europe/London"})

        schedule = build_loop_trigger_schedule(trigger)

        self.assertEqual(schedule.spec.cron_expressions, ["0 9 * * *"])
        self.assertEqual(schedule.spec.time_zone_name, "Europe/London")

    @parameterized.expand(
        [
            ("cron", {"cron_expression": "*/15 * * * *", "timezone": "UTC"}),
            ("one_time", {"run_at": "2026-08-01T10:00:00Z"}),
        ]
    )
    def test_schedule_policy_is_explicit_skip_with_five_minute_catchup_window(self, _name, config):
        loop = self.create_loop()
        trigger = self.create_trigger(loop, config)

        schedule = build_loop_trigger_schedule(trigger)

        self.assertEqual(schedule.policy.overlap, ScheduleOverlapPolicy.SKIP)
        self.assertEqual(schedule.policy.catchup_window, timedelta(minutes=5))

    def test_one_time_run_at_produces_a_single_limited_action_schedule(self):
        loop = self.create_loop()
        trigger = self.create_trigger(loop, {"run_at": "2026-08-01T10:00:00Z"})

        schedule = build_loop_trigger_schedule(trigger)

        self.assertTrue(schedule.state.limited_actions)
        self.assertEqual(schedule.state.remaining_actions, 1)

    @patch("products.tasks.backend.loop_service.schedule_exists")
    @patch("products.tasks.backend.loop_service.sync_connect")
    def test_sync_marks_schedule_sync_status_failed_and_does_not_raise_on_temporal_error(
        self, mock_sync_connect, mock_schedule_exists
    ):
        mock_sync_connect.return_value = MagicMock()
        mock_schedule_exists.side_effect = RuntimeError("temporal unavailable")
        loop = self.create_loop()
        trigger = self.create_trigger(loop, {"cron_expression": "0 9 * * *", "timezone": "UTC"})

        sync_loop_trigger_schedule(trigger)

        trigger.refresh_from_db()
        self.assertEqual(trigger.schedule_sync_status, LoopTrigger.ScheduleSyncStatus.FAILED)

    @parameterized.expand(
        [
            ("one_time", {"run_at": "2026-08-01T10:00:00Z"}, True),
            ("recurring", {"cron_expression": "0 9 * * *", "timezone": "UTC"}, False),
        ]
    )
    @patch("products.tasks.backend.loop_service.delete_schedule")
    @patch("products.tasks.backend.loop_service.schedule_exists")
    @patch("products.tasks.backend.loop_service.sync_connect")
    @patch("products.tasks.backend.logic.services.loop_runs.fire_loop")
    def test_firing_finalizes_only_one_time_triggers(
        self, _name, config, expect_completed, mock_fire_loop, mock_sync_connect, mock_schedule_exists, mock_delete
    ):
        # A one-time trigger's Schedule is spent after its single fire and Temporal never GCs it, so
        # firing must tear it down and mark the trigger completed. A recurring trigger must be left
        # untouched so it keeps firing.
        mock_sync_connect.return_value = MagicMock()
        mock_schedule_exists.return_value = True
        loop = self.create_loop()
        trigger = self.create_trigger(loop, config)

        run_loop_trigger(str(trigger.id), fire_key="workflow-123")

        mock_fire_loop.assert_called_once()
        trigger.refresh_from_db()
        if expect_completed:
            self.assertIsNotNone(trigger.completed_at)
            mock_delete.assert_called_once()
        else:
            self.assertIsNone(trigger.completed_at)
            mock_delete.assert_not_called()

    @patch("products.tasks.backend.loop_service.update_schedule")
    @patch("products.tasks.backend.loop_service.create_schedule")
    @patch("products.tasks.backend.loop_service.delete_schedule")
    @patch("products.tasks.backend.loop_service.schedule_exists")
    @patch("products.tasks.backend.loop_service.sync_connect")
    def test_sync_never_re_arms_a_completed_one_time_trigger(
        self, mock_sync_connect, mock_schedule_exists, mock_delete, mock_create, mock_update
    ):
        # Reconciliation or a later loop edit can re-drive a completed trigger through sync; it must
        # never mint a fresh Schedule for a spent one-time trigger, only ensure the old one is gone.
        mock_sync_connect.return_value = MagicMock()
        mock_schedule_exists.return_value = True
        loop = self.create_loop()
        trigger = self.create_trigger(
            loop,
            {"run_at": "2026-08-01T10:00:00Z"},
            schedule_sync_status=LoopTrigger.ScheduleSyncStatus.PENDING,
            completed_at=django_timezone.now(),
        )

        sync_loop_trigger_schedule(trigger)

        mock_create.assert_not_called()
        mock_update.assert_not_called()
        mock_delete.assert_called_once()
        trigger.refresh_from_db()
        self.assertEqual(trigger.schedule_sync_status, LoopTrigger.ScheduleSyncStatus.SYNCED)

    @patch("products.tasks.backend.loop_service.delete_schedule")
    @patch("products.tasks.backend.loop_service.schedule_exists")
    @patch("products.tasks.backend.loop_service.sync_connect")
    def test_delete_schedules_for_team_tears_down_every_schedule_trigger(
        self, mock_sync_connect, mock_schedule_exists, mock_delete
    ):
        # Team deletion cascades LoopTrigger rows away but never talks to Temporal, so this must
        # delete every schedule trigger's Schedule (and ignore non-schedule triggers).
        mock_sync_connect.return_value = MagicMock()
        mock_schedule_exists.return_value = True
        loop = self.create_loop()
        cron = self.create_trigger(loop, {"cron_expression": "0 9 * * *", "timezone": "UTC"})
        one_time = self.create_trigger(loop, {"run_at": "2026-08-01T10:00:00Z"})
        self.create_trigger(loop, {"repository": "acme/web"}, type=LoopTrigger.TriggerType.GITHUB)

        delete_schedules_for_team(self.team.id)

        deleted_schedule_ids = {call.args[1] for call in mock_delete.call_args_list}
        self.assertEqual(deleted_schedule_ids, {cron.schedule_id, one_time.schedule_id})

    def test_deleting_a_trigger_nulls_its_fires_instead_of_deleting_them(self):
        # LoopFire rows carry the rate-cap history (counted by `loop`, which survives). Replacing a
        # trigger during an edit must SET_NULL, not CASCADE, or an owner could reset their own cost
        # caps just by editing triggers.
        loop = self.create_loop()
        trigger = self.create_trigger(loop, {"cron_expression": "0 9 * * *", "timezone": "UTC"})
        fire = LoopFire(team=self.team, loop=loop, loop_trigger=trigger, fire_key="key-1")
        fire.save()

        trigger.delete()

        fire.refresh_from_db()
        self.assertIsNone(fire.loop_trigger_id)
        self.assertEqual(fire.loop_id, loop.id)
