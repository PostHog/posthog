from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from django.test import SimpleTestCase, TestCase
from django.utils import timezone as django_timezone

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.models.user import User

from products.tasks.backend.logic.services.workflow_dispatch import materialize_due_scheduled_task_runs
from products.tasks.backend.models import Task, TaskRun, TaskStatusChange
from products.tasks.backend.task_run_sync import (
    LatestRun,
    StatusMismatch,
    collect_status_mismatches,
    derive_task_status,
)


def _run(status: str, *, scheduled_at: datetime | None = None, error_message: str | None = None) -> LatestRun:
    return LatestRun(id=uuid4(), status=status, scheduled_at=scheduled_at, error_message=error_message)


class TestDeriveTaskStatus(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_run", None, ("idle", None, None)),
            ("not_started", _run("not_started"), ("queued", None, None)),
            ("scheduled", _run("not_started", scheduled_at=datetime(2026, 1, 1, tzinfo=UTC)), ("idle", None, None)),
            ("queued", _run("queued"), ("queued", None, None)),
            ("in_progress", _run("in_progress"), ("running", None, None)),
            ("completed", _run("completed"), ("idle", "turn_closed", None)),
            ("failed", _run("failed", error_message="boom"), ("idle", "unexpected_failure", "boom")),
            ("cancelled", _run("cancelled"), ("idle", "user_stopped", None)),
        ]
    )
    def test_maps_the_latest_run(self, _name: str, run: LatestRun | None, expected: tuple) -> None:
        derived = derive_task_status(run)
        self.assertEqual((derived.status, derived.reason, derived.detail), expected)


def _save_status(status: str, **fields: object) -> Callable[[Task], None]:
    def write(task: Task) -> None:
        run = task.create_run()
        run.status = status
        for name, value in fields.items():
            setattr(run, name, value)
        run.save(update_fields=["status", *fields])

    return write


def _materialize_invalid_scheduled_run(task: Task) -> None:
    task.create_run(scheduled_at=django_timezone.now() - timedelta(minutes=1))
    materialize_due_scheduled_task_runs(10)


def _delete_with_scheduled_run(task: Task) -> None:
    task.create_run(scheduled_at=django_timezone.now() + timedelta(days=1))
    task.soft_delete()


class TestTaskRunSync(TestCase):
    def setUp(self) -> None:
        self.team = Team.objects.create(organization=Organization.objects.create(name="Org"), name="Team")
        self.user = User.objects.create(email="sync@example.com")
        self.task = self._task()

    def _task(self) -> Task:
        return Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Task",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

    @parameterized.expand(
        [
            ("created", lambda task: task.create_run(), ("queued", None)),
            (
                "scheduled",
                lambda task: task.create_run(scheduled_at=django_timezone.now() + timedelta(days=1)),
                ("idle", None),
            ),
            ("started", _save_status(TaskRun.Status.IN_PROGRESS), ("running", None)),
            ("failed", _save_status(TaskRun.Status.FAILED, error_message="boom"), ("idle", "unexpected_failure")),
            ("bulk_materialized", _materialize_invalid_scheduled_run, ("idle", "unexpected_failure")),
            ("bulk_cancelled_on_delete", _delete_with_scheduled_run, ("idle", "user_stopped")),
        ]
    )
    def test_run_status_writes_reach_the_task(
        self, _name: str, write: Callable[[Task], object], expected: tuple[str, str | None]
    ) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            write(self.task)

        self.task.refresh_from_db()
        self.assertEqual((self.task.status, self.task.status_reason), expected)

    def test_records_one_change_per_status_move(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            run = self.task.create_run()
        with self.captureOnCommitCallbacks(execute=True):
            run.state = {**run.state, "note": "unrelated"}
            run.save(update_fields=["state"])
            run.save()
        with self.captureOnCommitCallbacks(execute=True):
            run.status = TaskRun.Status.IN_PROGRESS
            run.save(update_fields=["status"])

        changes = (
            TaskStatusChange.objects.for_team(self.team.id)
            .filter(task=self.task)
            .order_by("created_at", "id")
            .values_list("status", "run_id", "changed_by")
        )
        self.assertEqual(list(changes), [("queued", run.id, "task_run"), ("running", run.id, "task_run")])

    def test_shadow_counts_a_run_moved_without_a_sync(self) -> None:
        synced = self._task()
        with self.captureOnCommitCallbacks(execute=True):
            synced.create_run()
            run = self.task.create_run()
            run.status = TaskRun.Status.IN_PROGRESS
            run.save(update_fields=["status"])

        TaskRun.objects.filter(pk=run.pk).update(status=TaskRun.Status.FAILED)

        self.assertEqual(
            collect_status_mismatches(), [StatusMismatch(stored_status="running", derived_status="idle", count=1)]
        )

    @parameterized.expand([("wizard", "wizard_head_branch"), ("self_driving", "self_driving_head_branch")])
    def test_create_records_the_server_head_branch(self, _name: str, argument: str) -> None:
        head_branch: dict[str, Any] = {argument: "posthog/generated-branch"}
        task = Task.create_and_run(
            team=self.team,
            title="Task",
            description="d",
            user_id=self.user.id,
            origin_product=Task.OriginProduct.USER_CREATED,
            start_workflow=False,
            **head_branch,
        )

        task.refresh_from_db()
        self.assertEqual(task.head_branch, "posthog/generated-branch")
