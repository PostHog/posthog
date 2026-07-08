from datetime import timedelta

from unittest.mock import MagicMock, patch

from django.test import TestCase

from parameterized import parameterized
from temporalio.client import ScheduleOverlapPolicy

from posthog.models import Organization, Team, User

from products.tasks.backend.loop_service import build_loop_trigger_schedule, sync_loop_trigger_schedule
from products.tasks.backend.models import Loop, LoopTrigger


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
