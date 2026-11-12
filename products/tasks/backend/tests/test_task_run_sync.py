from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone as django_timezone

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.models.user import User

from products.tasks.backend.logic.services.custom_prompt_internals import _update_task_run_error_message
from products.tasks.backend.logic.services.workflow_dispatch import materialize_due_scheduled_task_runs
from products.tasks.backend.models import Task, TaskRun, TaskStatusChange
from products.tasks.backend.task_profiles import USER
from products.tasks.backend.task_run_sync import (
    LatestRun,
    StatusMismatch,
    collect_status_mismatches,
    derive_task_status,
    repair_status_mismatches,
    sync_task_status,
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

    def test_first_status_fill_also_fills_legacy_pr_columns(self) -> None:
        pr_url = "https://github.com/posthog/posthog/pull/7"
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={"wizard_head_branch": "posthog/wizard-abc", "verified_pr_urls": [pr_url]},
        )
        Task.objects.filter(pk=self.task.pk).update(status=None, head_branch=None, pr_urls=[])

        with self.captureOnCommitCallbacks(execute=True):
            run.status = TaskRun.Status.COMPLETED
            run.save(update_fields=["status"])

        self.task.refresh_from_db()
        self.assertEqual(
            (self.task.status, self.task.head_branch, self.task.pr_urls), ("idle", "posthog/wizard-abc", [pr_url])
        )

    def test_recovered_agent_error_reaches_the_task(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            _save_status(TaskRun.Status.FAILED, error_message="Activity task failed")(self.task)
        with self.captureOnCommitCallbacks(execute=True):
            _update_task_run_error_message(str(self.task.runs.get().id), "Model refused the request")

        self.task.refresh_from_db()
        self.assertEqual(self.task.status_detail, "Model refused the request")

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

    def _lose_sync(self, task: Task, *, run_status: str | None, stored: str | None) -> None:
        if run_status is not None:
            TaskRun.objects.create(task=task, team=self.team, status=run_status)
        Task.objects.filter(pk=task.pk).update(status=stored)

    @parameterized.expand(
        [
            ("running_but_run_finished", TaskRun.Status.COMPLETED, "running", "idle"),
            ("queued_but_run_running", TaskRun.Status.IN_PROGRESS, "queued", "running"),
            ("null_with_open_run", TaskRun.Status.IN_PROGRESS, None, "running"),
        ]
    )
    def test_repair_fixes_a_task_whose_sync_was_lost(
        self, _name: str, run_status: str, stored: str | None, derived: str
    ) -> None:
        self._lose_sync(self.task, run_status=run_status, stored=stored)

        repaired = repair_status_mismatches()

        self.task.refresh_from_db()
        self.assertEqual(repaired, [StatusMismatch(stored_status=stored, derived_status=derived, count=1)])
        self.assertEqual((self.task.status, self.task.status_changed_by), (derived, "status_repair"))
        self.assertEqual(collect_status_mismatches(), [])

    def test_repair_records_a_status_change_with_the_repair_actor(self) -> None:
        self._lose_sync(self.task, run_status=TaskRun.Status.IN_PROGRESS, stored="queued")

        repair_status_mismatches()

        changes = TaskStatusChange.objects.for_team(self.team.id).filter(task=self.task)
        self.assertEqual(list(changes.values_list("status", "changed_by")), [("running", "status_repair")])

    def test_repair_leaves_a_matching_task_alone(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            self.task.create_run()
        changes_before = TaskStatusChange.objects.for_team(self.team.id).count()

        self.assertEqual(repair_status_mismatches(), [])

        self.assertEqual(TaskStatusChange.objects.for_team(self.team.id).count(), changes_before)

    def test_repair_does_not_count_a_task_another_writer_fixed_first(self) -> None:
        self._lose_sync(self.task, run_status=TaskRun.Status.IN_PROGRESS, stored="queued")

        with patch("products.tasks.backend.task_run_sync.sync_task_status", return_value=False):
            repaired = repair_status_mismatches()

        self.assertEqual(repaired, [])

    def test_repair_stops_at_the_cap(self) -> None:
        tasks = [self.task, self._task(), self._task()]
        for task in tasks:
            self._lose_sync(task, run_status=TaskRun.Status.IN_PROGRESS, stored="queued")

        repaired = repair_status_mismatches(max_repairs=2)

        self.assertEqual(repaired, [StatusMismatch(stored_status="queued", derived_status="running", count=2)])
        self.assertEqual(
            collect_status_mismatches(), [StatusMismatch(stored_status="queued", derived_status="running", count=1)]
        )

    def test_repair_continues_after_a_task_fails(self) -> None:
        tasks = [self.task, self._task(), self._task()]
        for task in tasks:
            self._lose_sync(task, run_status=TaskRun.Status.IN_PROGRESS, stored="queued")

        def fail_for_first(task_id: Any, *, changed_by: str) -> bool:
            if str(task_id) == str(tasks[0].id):
                raise RuntimeError("boom")
            return sync_task_status(task_id, changed_by=changed_by)

        with patch("products.tasks.backend.task_run_sync.sync_task_status", side_effect=fail_for_first):
            repaired = repair_status_mismatches()

        self.assertEqual(repaired, [StatusMismatch(stored_status="queued", derived_status="running", count=2)])
        self.assertEqual(Task.objects.filter(status="running").count(), 2)

    @parameterized.expand([("wizard", "wizard_head_branch"), ("self_driving", "self_driving_head_branch")])
    def test_create_records_the_server_head_branch(self, _name: str, argument: str) -> None:
        head_branch: dict[str, Any] = {argument: "posthog/generated-branch"}
        task = Task.create_and_run(
            team=self.team,
            title="Task",
            description="d",
            user_id=self.user.id,
            profile=USER,
            start_workflow=False,
            **head_branch,
        )

        task.refresh_from_db()
        self.assertEqual(task.head_branch, "posthog/generated-branch")
