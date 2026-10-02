from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from posthog.models import Organization, Team

from products.tasks.backend.management.commands.backfill_task_tags import backfill_task_tags
from products.tasks.backend.models import Task, TaskRun


class TestBackfillTaskTags(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.team = Team.objects.create(organization=Organization.objects.create(name="Org"), name="Team")

    def _task_with_runs(self, *states: dict, deleted: bool = False) -> Task:
        task = Task.objects.create(
            team=self.team,
            title="Task",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
            deleted=deleted,
        )
        start = timezone.now() - timedelta(hours=len(states))
        for offset, state in enumerate(states):
            TaskRun.objects.create(task=task, team=self.team, state=state, created_at=start + timedelta(hours=offset))
        return task

    def test_writes_the_latest_run_tags_of_live_tasks(self) -> None:
        current = self._task_with_runs({"task_tags": ["old-tag"]}, {"task_tags": ["bug-fix"]})
        inherited = self._task_with_runs({"task_tags": ["old-tag"]}, {"prior_run_tags": ["research"]})
        cleared = self._task_with_runs({"task_tags": ["old-tag"]}, {"task_tags": []})
        deleted = self._task_with_runs({"task_tags": ["bug-fix"]}, deleted=True)

        self.assertEqual(backfill_task_tags(dry_run=True), 2)
        self.assertFalse(current.tagged_items.exists())

        self.assertEqual(backfill_task_tags(), 2)
        self.assertEqual(list(current.tagged_items.values_list("tag__name", flat=True)), ["bug-fix"])
        self.assertEqual(list(inherited.tagged_items.values_list("tag__name", flat=True)), ["research"])
        self.assertFalse(cleared.tagged_items.exists())
        self.assertFalse(deleted.tagged_items.exists())
