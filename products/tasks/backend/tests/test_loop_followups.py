from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone as django_timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.user import User

from products.tasks.backend.exceptions import FollowupDeferError
from products.tasks.backend.logic.services.loop_followups import request_followup_defer
from products.tasks.backend.models import Loop, LoopTrigger, Task, TaskRun
from products.tasks.backend.tests.test_loop_runs import SlackFollowupTestCase

LOOP_FOLLOWUPS_MODULE = "products.tasks.backend.logic.services.loop_followups"


class TestRequestFollowupDefer(SlackFollowupTestCase):
    def setUp(self):
        super().setUp()
        sync = patch(f"{LOOP_FOLLOWUPS_MODULE}.sync_loop_trigger_schedule")
        self.mock_sync = sync.start()
        self.addCleanup(sync.stop)

    def fired_bound_run(self) -> TaskRun:
        self.loop = self.create_loop(slack_thread_target=self.slack_target())
        # The one-time trigger that fired this run; the schedule workflow stamps it
        # completed before the run's agent gets to work.
        self.create_trigger(
            self.loop,
            type=LoopTrigger.TriggerType.SCHEDULE,
            config={"run_at": (django_timezone.now() - timedelta(minutes=5)).isoformat()},
            completed_at=django_timezone.now(),
        )
        result = self.fire_bound_loop(self.loop)
        return TaskRun.objects.get(id=result.task_run_id)

    def pending_trigger_count(self) -> int:
        return (
            LoopTrigger.objects.for_team(self.team.id, canonical=True)
            .filter(loop=self.loop, type=LoopTrigger.TriggerType.SCHEDULE, completed_at__isnull=True)
            .count()
        )

    def test_defer_rearms_the_loop_with_a_fresh_one_time_trigger(self):
        run = self.fired_bound_run()
        until = django_timezone.now() + timedelta(days=7)

        result = request_followup_defer(run, until=until, reason="Cohort is still too small")

        self.assertEqual(result.defers_used, 1)
        self.assertEqual(result.max_defers, 3)
        pending = LoopTrigger.objects.for_team(self.team.id, canonical=True).get(
            loop=self.loop, type=LoopTrigger.TriggerType.SCHEDULE, completed_at__isnull=True
        )
        self.assertEqual(pending.config["run_at"], until.isoformat())
        self.assertEqual(pending.config["deferred_from_run_id"], str(run.id))
        self.assertEqual(pending.config["defer_reason"], "Cohort is still too small")
        self.mock_sync.assert_called_once_with(pending)

    @parameterized.expand(
        [
            ("too_soon", timedelta(minutes=30), None, "invalid_until"),
            ("too_far", timedelta(days=120), None, "invalid_until"),
            ("already_scheduled", timedelta(days=7), "PENDING_TRIGGER", "already_scheduled"),
            ("cap_exhausted", timedelta(days=7), "SPEND_CAP", "limit_reached"),
        ]
    )
    def test_rejected_defers_do_not_rearm(self, _name, until_delta, setup, expected_code):
        run = self.fired_bound_run()
        if setup == "PENDING_TRIGGER":
            self.create_trigger(
                self.loop,
                type=LoopTrigger.TriggerType.SCHEDULE,
                config={"run_at": (django_timezone.now() + timedelta(days=3)).isoformat()},
            )
        elif setup == "SPEND_CAP":
            # Three spent defer triggers on top of the original ask exhaust the default budget.
            for _ in range(3):
                self.create_trigger(
                    self.loop,
                    type=LoopTrigger.TriggerType.SCHEDULE,
                    config={"run_at": (django_timezone.now() - timedelta(days=1)).isoformat()},
                    completed_at=django_timezone.now(),
                )
        pending_before = self.pending_trigger_count()

        with self.assertRaises(FollowupDeferError) as ctx:
            request_followup_defer(run, until=django_timezone.now() + until_delta)

        self.assertEqual(ctx.exception.code, expected_code)
        self.assertEqual(self.pending_trigger_count(), pending_before)

    def test_a_run_without_a_thread_bound_loop_cannot_defer(self):
        task = Task.objects.create(team=self.team, created_by=self.user, title="t", description="d")
        run = task.create_run(mode="background")

        with self.assertRaises(FollowupDeferError) as ctx:
            request_followup_defer(run, until=django_timezone.now() + timedelta(days=7))

        self.assertEqual(ctx.exception.code, "not_a_followup")


class TestDisableSlackFollowupLoopsForThread(SlackFollowupTestCase):
    def setUp(self):
        super().setUp()
        pause = patch("products.tasks.backend.facade.loops.loop_service.pause_loop_schedules")
        self.mock_pause = pause.start()
        self.addCleanup(pause.stop)

    def test_disables_only_the_requesters_loops_bound_to_the_thread(self):
        from products.tasks.backend.facade.loops import disable_slack_followup_loops_for_thread

        mine = self.create_loop(slack_thread_target=self.slack_target(), origin_product=Task.OriginProduct.SLACK)
        other_thread = self.create_loop(
            slack_thread_target=self.slack_target(thread_ts="999.888"),
            origin_product=Task.OriginProduct.SLACK,
        )
        teammate = User.objects.create_user(email="teammate@example.com", first_name="T", password="password")
        theirs = self.create_loop(
            slack_thread_target=self.slack_target(),
            origin_product=Task.OriginProduct.SLACK,
            created_by=teammate,
        )

        disabled = disable_slack_followup_loops_for_thread(
            self.team.id,
            self.user,
            integration_id=self.slack_integration.id,
            channel="C0456",
            thread_ts=self.THREAD_TS,
        )

        self.assertEqual(disabled, 1)
        mine.refresh_from_db()
        other_thread.refresh_from_db()
        theirs.refresh_from_db()
        self.assertFalse(mine.enabled)
        self.assertTrue(other_thread.enabled)
        self.assertTrue(theirs.enabled)
        self.mock_pause.assert_called_once()


class TestDeferFollowupEndpoint(APIBaseTest):
    def setUp(self):
        super().setUp()
        sync = patch(f"{LOOP_FOLLOWUPS_MODULE}.sync_loop_trigger_schedule")
        self.mock_sync = sync.start()
        self.addCleanup(sync.stop)
        loop = Loop(
            team=self.team,
            created_by=self.user,
            name="Follow-up",
            instructions="Check the cohort",
            runtime_adapter="claude",
            slack_thread_target={"integration_id": 1, "channel": "C1", "thread_ts": "111.222"},
        )
        loop.save()
        self.loop = loop
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Follow-up run",
            description="d",
            origin_product=Task.OriginProduct.LOOP,
            loop=self.loop,
        )
        self.run = self.task.create_run(mode="background", extra_state={"loop_id": str(self.loop.id)})

    def defer(self, until):
        return self.client.post(
            f"/api/projects/@current/tasks/{self.task.id}/runs/{self.run.id}/defer_followup/",
            {"until": until.isoformat(), "reason": "Not enough data yet"},
            format="json",
        )

    def test_defer_endpoint_schedules_and_reports_the_budget(self):
        response = self.defer(django_timezone.now() + timedelta(days=7))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual((body["defers_used"], body["max_defers"]), (1, 3))
        self.assertEqual(
            LoopTrigger.objects.for_team(self.team.id, canonical=True)
            .filter(loop=self.loop, completed_at__isnull=True)
            .count(),
            1,
        )

    def test_defer_endpoint_maps_rejections_to_conflict(self):
        pending = LoopTrigger(
            team=self.team,
            loop=self.loop,
            type=LoopTrigger.TriggerType.SCHEDULE,
            config={"run_at": (django_timezone.now() + timedelta(days=3)).isoformat()},
        )
        pending.save()

        response = self.defer(django_timezone.now() + timedelta(days=7))

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("error", response.json())
