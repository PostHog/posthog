from datetime import UTC, datetime

from django.test import TestCase

from posthog.models import Organization, Team

from products.tasks.backend.management.commands.backfill_task_status import backfill_task_status
from products.tasks.backend.models import Task, TaskRun

PR_URL = "https://github.com/posthog/posthog/pull/1"
OTHER_PR_URL = "https://github.com/posthog/posthog/pull/2"
EARLIER = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
LATER = datetime(2026, 1, 1, 10, 5, tzinfo=UTC)


class TestBackfillTaskStatus(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.team = Team.objects.create(organization=Organization.objects.create(name="Org"), name="Team")

    def _unfilled_task(self, *runs: dict) -> Task:
        task = Task.objects.create(
            team=self.team, title="Task", description="d", origin_product=Task.OriginProduct.USER_CREATED
        )
        for run in runs:
            TaskRun.objects.create(task=task, team=self.team, **run)
        Task.objects.filter(pk=task.pk).update(status=None, status_reason=None, status_changed_by=None)
        return task

    def test_fills_unfilled_tasks_from_their_runs_and_leaves_filled_ones(self) -> None:
        unfilled = self._unfilled_task(
            {
                "status": TaskRun.Status.COMPLETED,
                "created_at": EARLIER,
                "state": {"verified_pr_urls": [OTHER_PR_URL]},
            },
            {
                "status": TaskRun.Status.FAILED,
                "created_at": LATER,
                "error_message": "boom",
                "state": {"verified_pr_urls": [PR_URL], "wizard_head_branch": "posthog/wizard-abc"},
            },
        )
        filled = Task.objects.create(
            team=self.team, title="Task", description="d", origin_product=Task.OriginProduct.USER_CREATED
        )
        Task.objects.filter(pk=filled.pk).update(status=Task.Status.RUNNING)

        self.assertEqual(sum(batch.tasks for batch in backfill_task_status(batch_size=1)), 1)
        self.assertEqual(sum(batch.tasks for batch in backfill_task_status()), 0)

        unfilled.refresh_from_db()
        filled.refresh_from_db()
        self.assertEqual(
            (
                unfilled.status,
                unfilled.status_reason,
                unfilled.status_detail,
                unfilled.status_changed_by,
                unfilled.head_branch,
                unfilled.pr_urls,
            ),
            ("idle", "unexpected_failure", "boom", "backfill", "posthog/wizard-abc", [PR_URL, OTHER_PR_URL]),
        )
        self.assertEqual(filled.status, Task.Status.RUNNING)
