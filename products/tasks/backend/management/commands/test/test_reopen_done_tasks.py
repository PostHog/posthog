from datetime import timedelta
from io import StringIO

from unittest.mock import patch

from django.core.management import call_command
from django.db.models import QuerySet
from django.test import TestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team

from products.tasks.backend.management.commands.reopen_done_tasks import reopen_done_tasks
from products.tasks.backend.models import Task, TaskRun, TaskStatusChange
from products.tasks.backend.task_run_sync import DoneMode

PROFILE = "cloud"
DONE_MODE = "products.tasks.backend.management.commands.reopen_done_tasks.done_mode"


class TestReopenDoneTasks(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.team = Team.objects.create(organization=Organization.objects.create(name="Org"), name="Team")
        self.activity_at = timezone.now() - timedelta(days=30)

    def _task(
        self,
        *,
        team: Team | None = None,
        status: str = Task.Status.DONE,
        profile: str = PROFILE,
        run: dict | None = None,
    ) -> Task:
        team = team or self.team
        task = Task.objects.create(
            team=team,
            title="Task",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
            profile=profile,
        )
        if run is not None:
            TaskRun.objects.create(task=task, team=team, **run)
        Task.objects.filter(pk=task.pk).update(
            status=status, status_reason=Task.StatusReason.FINISHED, last_activity_at=self.activity_at
        )
        task.refresh_from_db()
        return task

    def _changes(self) -> QuerySet[TaskStatusChange]:
        return TaskStatusChange.objects.for_team(self.team.pk, canonical=True)

    @parameterized.expand(
        [
            (
                "completed_run",
                {"status": TaskRun.Status.COMPLETED},
                (Task.Status.IDLE, Task.StatusReason.TURN_CLOSED, None),
            ),
            (
                "failed_run",
                {"status": TaskRun.Status.FAILED, "error_message": "boom"},
                (Task.Status.IDLE, Task.StatusReason.UNEXPECTED_FAILURE, "boom"),
            ),
            ("in_progress_run", {"status": TaskRun.Status.IN_PROGRESS}, (Task.Status.RUNNING, None, None)),
            ("no_run", None, (Task.Status.IDLE, None, None)),
        ]
    )
    def test_reopens_to_the_status_the_latest_run_derives(
        self, _name: str, run: dict | None, expected: tuple[str, str | None, str | None]
    ) -> None:
        task = self._task(run=run)

        with patch(DONE_MODE, return_value=DoneMode.OFF):
            self.assertEqual(sum(reopen_done_tasks(profile=PROFILE)), 1)

        task.refresh_from_db()
        self.assertEqual((task.status, task.status_reason, task.status_detail), expected)
        self.assertEqual(task.status_changed_by, "reopen")
        change = self._changes().get(task_id=task.pk)
        self.assertEqual((change.status, change.reason, change.detail, change.changed_by), (*expected, "reopen"))

    def test_does_not_touch_last_activity(self) -> None:
        task = self._task(run={"status": TaskRun.Status.COMPLETED})

        with patch(DONE_MODE, return_value=DoneMode.OFF):
            list(reopen_done_tasks(profile=PROFILE))

        task.refresh_from_db()
        self.assertEqual(task.last_activity_at, self.activity_at)

    @parameterized.expand(
        [
            ("other_profile", Task.Status.DONE, "other", DoneMode.OFF),
            ("not_done", Task.Status.IDLE, PROFILE, DoneMode.OFF),
            ("shadow_mode", Task.Status.DONE, PROFILE, DoneMode.SHADOW),
            ("enforce_mode", Task.Status.DONE, PROFILE, DoneMode.ENFORCE),
            ("unresolved_mode", Task.Status.DONE, PROFILE, None),
        ]
    )
    def test_leaves_other_tasks_alone(self, _name: str, status: str, profile: str, mode: DoneMode | None) -> None:
        task = self._task(status=status, profile=profile, run={"status": TaskRun.Status.COMPLETED})

        with patch(DONE_MODE, return_value=mode):
            self.assertEqual(sum(reopen_done_tasks(profile=PROFILE)), 0)

        task.refresh_from_db()
        self.assertEqual(task.status, status)
        self.assertFalse(self._changes().exists())

    def test_skips_a_task_that_stopped_being_done_after_it_was_listed(self) -> None:
        task = self._task(run={"status": TaskRun.Status.COMPLETED})

        def mode_while_task_moves_on(profile: str, team_id: int) -> DoneMode:
            Task.objects.filter(pk=task.pk).update(status=Task.Status.RUNNING, status_reason=None)
            return DoneMode.OFF

        with patch(DONE_MODE, side_effect=mode_while_task_moves_on):
            self.assertEqual(sum(reopen_done_tasks(profile=PROFILE)), 0)

        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.RUNNING)
        self.assertFalse(self._changes().exists())

    def test_pages_through_every_batch(self) -> None:
        tasks = [self._task(run={"status": TaskRun.Status.COMPLETED}) for _ in range(3)]

        with patch(DONE_MODE, return_value=DoneMode.OFF):
            self.assertEqual(list(reopen_done_tasks(profile=PROFILE, batch_size=2)), [2, 1])

        self.assertEqual(Task.objects.filter(pk__in=[t.pk for t in tasks], status=Task.Status.IDLE).count(), 3)

    def test_pages_past_tasks_that_stay_done(self) -> None:
        for _ in range(2):
            self._task()

        with patch(DONE_MODE, return_value=DoneMode.ENFORCE):
            self.assertEqual(list(reopen_done_tasks(profile=PROFILE, batch_size=1)), [0, 0])

    def test_only_reopens_the_given_team(self) -> None:
        other_team = Team.objects.create(organization=self.team.organization, name="Other")
        task = self._task()
        other = self._task(team=other_team)

        with patch(DONE_MODE, return_value=DoneMode.OFF):
            self.assertEqual(sum(reopen_done_tasks(profile=PROFILE, team_id=self.team.pk)), 1)

        task.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual((task.status, other.status), (Task.Status.IDLE, Task.Status.DONE))

    def test_dry_run_counts_without_writing(self) -> None:
        task = self._task(run={"status": TaskRun.Status.COMPLETED})

        stdout = StringIO()
        with patch(DONE_MODE, return_value=DoneMode.OFF):
            call_command("reopen_done_tasks", "--profile", PROFILE, "--dry-run", "--sleep-seconds", "0", stdout=stdout)

        task.refresh_from_db()
        self.assertEqual((stdout.getvalue().strip(), task.status), ("Would reopen 1 tasks in all", Task.Status.DONE))
        self.assertFalse(self._changes().exists())
