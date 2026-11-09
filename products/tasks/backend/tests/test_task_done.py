from dataclasses import replace
from datetime import timedelta
from typing import Literal

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone as django_timezone

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models import Organization, Team
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.tasks.backend.logic.services.workflow_dispatch import materialize_due_scheduled_task_runs
from products.tasks.backend.models import Task, TaskRun, TaskStatusChange
from products.tasks.backend.task_done import TaskDoneError, record_pull_request_outcome
from products.tasks.backend.task_profiles import USER
from products.tasks.backend.task_run_sync import DoneMode, done_mode, sync_task_status, transition

PAYLOAD = "products.tasks.backend.task_run_sync.posthoganalytics.get_feature_flag_payload"
PR_ONE = "https://github.com/posthog/posthog/pull/1"
PR_TWO = "https://github.com/posthog/posthog/pull/2"


class TestTaskDone(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Org")
        self.team = Team.objects.create(organization=self.organization, name="Team")
        self.user = User.objects.create(email="done@example.com")
        OrganizationMembership.objects.create(organization=self.organization, user=self.user)
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Task",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
            profile=USER.key,
        )

    def _set_status(self, status: str, reason: str | None = None) -> None:
        Task.objects.filter(pk=self.task.pk).update(status=status, status_reason=reason)
        self.task.refresh_from_db()

    def _mode(self, mode: str | None):
        return patch(PAYLOAD, return_value=None if mode is None else {USER.key: mode})

    @parameterized.expand(
        [
            ("dict_payload", {"user": "enforce"}, DoneMode.ENFORCE),
            ("json_payload", '{"user": "shadow"}', DoneMode.SHADOW),
            ("other_profile_only", {"signals": "enforce"}, DoneMode.OFF),
            ("unknown_value", {"user": "maybe"}, DoneMode.OFF),
            ("unresolved", None, None),
        ]
    )
    def test_done_mode_reads_the_profile_from_the_payload(
        self, _name: str, payload: object, expected: str | None
    ) -> None:
        with patch(PAYLOAD, return_value=payload):
            self.assertEqual(done_mode(USER.key, self.team.id), expected)

    def test_done_mode_is_cached_per_team_and_profile(self) -> None:
        with patch(PAYLOAD, return_value={"user": "enforce"}) as payload:
            done_mode(USER.key, self.team.id)
            self.assertEqual(done_mode(USER.key, self.team.id), DoneMode.ENFORCE)

        self.assertEqual(payload.call_count, 1)

    @parameterized.expand(
        [
            ("idle_to_done", Task.Status.IDLE, Task.Status.DONE, Task.StatusReason.CLOSED, True),
            ("done_is_final", Task.Status.DONE, Task.Status.QUEUED, None, False),
            ("idle_cannot_run_without_queue", Task.Status.IDLE, Task.Status.RUNNING, None, False),
        ]
    )
    def test_transition_follows_the_table(
        self, _name: str, current: str, to: str, reason: str | None, moved: bool
    ) -> None:
        self._set_status(current)

        self.assertEqual(transition(self.task.id, to, reason=reason, actor="test"), moved)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, to if moved else current)

    def test_transition_refuses_a_reason_that_does_not_fit(self) -> None:
        self._set_status(Task.Status.IDLE)

        with self.assertRaises(ValueError):
            transition(self.task.id, Task.Status.DONE, reason=Task.StatusReason.TURN_CLOSED, actor="test")

    @parameterized.expand(
        [
            ("enforce", "enforce", "done"),
            ("shadow", "shadow", "done"),
            ("unresolved", None, "done"),
            ("off", "off", "queued"),
        ]
    )
    def test_run_sync_leaves_done_alone_unless_explicitly_off(
        self, _name: str, mode: str | None, expected: str
    ) -> None:
        self._set_status(Task.Status.DONE, Task.StatusReason.FINISHED)
        TaskRun.objects.create(task=self.task, team=self.team, status=TaskRun.Status.QUEUED)

        with self._mode(mode):
            sync_task_status(self.task.id)

        self.task.refresh_from_db()
        self.assertEqual(self.task.status, expected)

    @parameterized.expand(
        [
            ("enforce_marks_done", "enforce", "done", "task_run"),
            ("shadow_only_records", "shadow", "idle", "shadow:task_run"),
            ("off_does_nothing", "off", "idle", None),
        ]
    )
    def test_turn_close_finishes_done_on_turn_close_profiles(
        self, _name: str, mode: str, status: str, done_changed_by: str | None
    ) -> None:
        self._set_status(Task.Status.RUNNING)
        TaskRun.objects.create(task=self.task, team=self.team, status=TaskRun.Status.COMPLETED)

        with (
            self._mode(mode),
            patch(
                "products.tasks.backend.task_run_sync.find_task_profile",
                return_value=replace(USER, done_on_turn_close=True),
            ),
        ):
            sync_task_status(self.task.id)

        self.task.refresh_from_db()
        self.assertEqual(self.task.status, status)
        done_change = (
            TaskStatusChange.objects.for_team(self.team.id)
            .filter(task=self.task, status=Task.Status.DONE)
            .values_list("changed_by", flat=True)
            .first()
        )
        self.assertEqual(done_change, done_changed_by)

    @parameterized.expand([("enforce", "enforce", True), ("unresolved", None, True), ("off", "off", False)])
    def test_new_runs_on_a_done_task_are_refused_unless_explicitly_off(
        self, _name: str, mode: str | None, refused: bool
    ) -> None:
        self._set_status(Task.Status.DONE, Task.StatusReason.CLOSED)

        with self._mode(mode):
            if refused:
                with self.assertRaises(TaskDoneError):
                    self.task.create_run()
            else:
                self.task.create_run()

        self.assertEqual(self.task.runs.exists(), not refused)

    def test_scheduled_run_on_a_done_task_is_canceled(self) -> None:
        run = self.task.create_run(scheduled_at=django_timezone.now() - timedelta(minutes=1))
        self._set_status(Task.Status.DONE, Task.StatusReason.CLOSED)

        with self._mode("enforce"):
            self.assertEqual(materialize_due_scheduled_task_runs(10), 0)

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.CANCELLED)

    @parameterized.expand(
        [
            ("one_of_two_merged", [(PR_ONE, "merged")], "idle", "turn_closed"),
            ("both_merged", [(PR_ONE, "merged"), (PR_TWO, "merged")], "done", "finished"),
            ("both_closed", [(PR_ONE, "closed"), (PR_TWO, "closed")], "done", "closed"),
            ("merged_and_closed", [(PR_ONE, "merged"), (PR_TWO, "closed")], "done", "finished"),
            (
                "reopened_before_the_other_closed",
                [(PR_ONE, "closed"), (PR_ONE, "open"), (PR_TWO, "closed")],
                "idle",
                "turn_closed",
            ),
        ]
    )
    def test_pull_request_outcomes_finish_the_task_once_every_pr_is_done(
        self, _name: str, events: list[tuple[str, Literal["merged", "closed", "open"]]], status: str, reason: str
    ) -> None:
        Task.objects.filter(pk=self.task.pk).update(
            status=Task.Status.IDLE, status_reason=Task.StatusReason.TURN_CLOSED, pr_urls=[PR_ONE, PR_TWO]
        )

        with self._mode("enforce"):
            for url, state in events:
                record_pull_request_outcome(self.task.id, url, state=state)

        self.task.refresh_from_db()
        self.assertEqual((self.task.status, self.task.status_reason), (status, reason))

    @parameterized.expand([("once", 1), ("repeated", 3)])
    def test_shadow_done_is_recorded_once(self, _name: str, calls: int) -> None:
        Task.objects.filter(pk=self.task.pk).update(
            status=Task.Status.IDLE, status_reason=Task.StatusReason.TURN_CLOSED, pr_urls=[PR_ONE]
        )

        with self._mode("shadow"):
            for _ in range(calls):
                record_pull_request_outcome(self.task.id, PR_ONE, state="merged")

        shadow_rows = TaskStatusChange.objects.for_team(self.team.id).filter(
            task=self.task, status=Task.Status.DONE, changed_by__startswith="shadow:"
        )
        self.assertEqual(shadow_rows.count(), 1)

    @parameterized.expand(
        [
            ("closes_idle_task", "enforce", Task.Status.IDLE, 200, "done"),
            ("already_done", "enforce", Task.Status.DONE, 200, "done"),
            ("not_enabled", "off", Task.Status.IDLE, 400, "idle"),
            ("running_task", "enforce", Task.Status.RUNNING, 409, "running"),
        ]
    )
    def test_close_endpoint(self, _name: str, mode: str, current: str, code: int, status: str) -> None:
        self._set_status(current)
        client = APIClient()
        client.force_login(self.user)

        with self._mode(mode):
            response = client.post(f"/api/projects/{self.team.id}/tasks/{self.task.id}/close/")

        self.assertEqual(response.status_code, code)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, status)
