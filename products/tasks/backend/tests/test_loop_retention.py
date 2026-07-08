from datetime import timedelta

from django.test import TestCase
from django.utils import timezone as django_timezone

from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.tasks.backend.loop_retention import sweep_loop_task_retention
from products.tasks.backend.models import Loop, Task, TaskRun


class LoopRetentionTestCase(TestCase):
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

    def create_loop_task(self, loop: Loop, *, created_at, run_status=TaskRun.Status.COMPLETED) -> Task:
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Loop run",
            description="Loop instructions plus trigger context",
            origin_product=Task.OriginProduct.LOOP,
            internal=True,
            loop=loop,
            created_at=created_at,
        )
        TaskRun.objects.create(task=task, team=self.team, status=run_status, state={"loop_id": str(loop.id)})
        return task


class TestSweepLoopTaskRetention(LoopRetentionTestCase):
    @parameterized.expand(
        [
            ("terminal_run_is_trimmed", TaskRun.Status.COMPLETED, True),
            ("non_terminal_run_is_preserved", TaskRun.Status.IN_PROGRESS, False),
        ]
    )
    def test_stale_task_deletion_depends_on_run_terminality(self, _name, run_status, expect_deleted):
        loop = self.create_loop()
        base = django_timezone.now()
        stale = self.create_loop_task(loop, created_at=base - timedelta(days=1), run_status=run_status)
        newest = self.create_loop_task(loop, created_at=base)

        deleted_count = sweep_loop_task_retention(retention_limit=1)

        self.assertEqual(deleted_count, 1 if expect_deleted else 0)
        self.assertEqual(Task.objects.get(id=stale.id).deleted, expect_deleted)
        self.assertFalse(Task.objects.get(id=newest.id).deleted)

    def test_retention_limit_applies_per_loop_not_globally(self):
        loop_a = self.create_loop(name="Loop A")
        loop_b = self.create_loop(name="Loop B")
        base = django_timezone.now()
        stale_a = self.create_loop_task(loop_a, created_at=base - timedelta(days=1))
        newest_a = self.create_loop_task(loop_a, created_at=base)
        stale_b = self.create_loop_task(loop_b, created_at=base - timedelta(days=1))
        newest_b = self.create_loop_task(loop_b, created_at=base)

        deleted_count = sweep_loop_task_retention(retention_limit=1)

        self.assertEqual(deleted_count, 2)
        self.assertTrue(Task.objects.get(id=stale_a.id).deleted)
        self.assertTrue(Task.objects.get(id=stale_b.id).deleted)
        self.assertFalse(Task.objects.get(id=newest_a.id).deleted)
        self.assertFalse(Task.objects.get(id=newest_b.id).deleted)
