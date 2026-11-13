from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team

from products.tasks.backend.management.commands.complete_unstarted_local_task_runs import (
    complete_unstarted_local_task_runs,
)
from products.tasks.backend.models import Task, TaskRun

LONG_IDLE = timedelta(days=30)
JUST_TOUCHED = timedelta(hours=1)


class TestCompleteUnstartedLocalTaskRuns(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.team = Team.objects.create(organization=Organization.objects.create(name="Org"), name="Team")
        self.now = timezone.now()

    def _queued_task_with_run(self, *, idle_for: timedelta = LONG_IDLE, **run: object) -> tuple[Task, TaskRun]:
        task = Task.objects.create(
            team=self.team, title="Task", description="d", origin_product=Task.OriginProduct.USER_CREATED
        )
        task_run = TaskRun.objects.create(task=task, team=self.team, **run)
        TaskRun.objects.filter(pk=task_run.pk).update(updated_at=self.now - idle_for)
        Task.objects.filter(pk=task.pk).update(status=Task.Status.QUEUED, last_activity_at=self.now - idle_for)
        task.refresh_from_db()
        task_run.refresh_from_db()
        return task, task_run

    def test_completes_the_run_and_idles_its_task_without_touching_activity(self) -> None:
        task, task_run = self._queued_task_with_run(
            status=TaskRun.Status.NOT_STARTED, environment=TaskRun.Environment.LOCAL
        )

        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(sum(complete_unstarted_local_task_runs(batch_size=1)), 1)
            self.assertEqual(sum(complete_unstarted_local_task_runs()), 0)

        previous_activity, previous_update = task.last_activity_at, task_run.updated_at
        task.refresh_from_db()
        task_run.refresh_from_db()
        self.assertEqual(
            (task_run.status, task_run.completed_at, task_run.updated_at),
            (TaskRun.Status.COMPLETED, previous_update, previous_update),
        )
        self.assertEqual(
            (task.status, task.status_reason, task.status_changed_by, task.last_activity_at),
            (Task.Status.IDLE, Task.StatusReason.TURN_CLOSED, "backfill", previous_activity),
        )

    @parameterized.expand(
        [
            ("cloud_run", {"status": TaskRun.Status.NOT_STARTED, "environment": TaskRun.Environment.CLOUD}, LONG_IDLE),
            ("queued_run", {"status": TaskRun.Status.QUEUED, "environment": TaskRun.Environment.LOCAL}, LONG_IDLE),
            (
                "scheduled_run",
                {
                    "status": TaskRun.Status.NOT_STARTED,
                    "environment": TaskRun.Environment.LOCAL,
                    "scheduled_at": timezone.now() + timedelta(days=1),
                },
                LONG_IDLE,
            ),
            (
                "recently_touched_run",
                {"status": TaskRun.Status.NOT_STARTED, "environment": TaskRun.Environment.LOCAL},
                JUST_TOUCHED,
            ),
        ]
    )
    def test_leaves_other_runs_alone(self, _name: str, run: dict, idle_for: timedelta) -> None:
        task, task_run = self._queued_task_with_run(idle_for=idle_for, **run)

        self.assertEqual(sum(complete_unstarted_local_task_runs()), 0)

        task.refresh_from_db()
        task_run.refresh_from_db()
        self.assertEqual((task_run.status, task_run.completed_at, task.status), (run["status"], None, "queued"))

    def test_dry_run_counts_without_writing(self) -> None:
        _, task_run = self._queued_task_with_run(
            status=TaskRun.Status.NOT_STARTED, environment=TaskRun.Environment.LOCAL
        )

        self.assertEqual(sum(complete_unstarted_local_task_runs(dry_run=True)), 1)

        task_run.refresh_from_db()
        self.assertEqual(task_run.status, TaskRun.Status.NOT_STARTED)
