from datetime import UTC, datetime

from unittest.mock import patch

from django.test import TestCase

from parameterized import parameterized

from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.scoping import team_scope

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.logic.services.awaiting_input import (
    clear_task_run_awaiting_input,
    mark_task_run_awaiting_input,
)
from products.tasks.backend.models import Channel, Task, TaskRun
from products.tasks.backend.temporal.process_task.activities.relay_sandbox_events import _broker_permission_request

PERMISSION_REQUEST = {
    "request_id": "perm-1",
    "tool_call": {"toolCallId": "tool-1"},
    "options": [{"optionId": "allow", "kind": "allow_once", "name": "Yes"}],
}


class AwaitingInputTestCase(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Growth Team")
        self.enterContext(team_scope(self.team.id, canonical=True))
        self.user = User.objects.create_user(email="owner@example.com", first_name="Ann", password="password")
        self.organization.members.add(self.user)
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )
        self.channel = Channel.objects.unscoped().create(team=self.team, name="general", created_by=self.user)
        self.task = Task.objects.create(team=self.team, title="Ship it", created_by=self.user, channel=self.channel)

    def _run(
        self,
        *,
        status: str = TaskRun.Status.IN_PROGRESS,
        task: Task | None = None,
        created_at: datetime | None = None,
    ) -> TaskRun:
        return TaskRun.objects.create(
            team=self.team,
            task=task or self.task,
            status=status,
            # Explicit where a test has two runs of one task: "latest" breaks ties on the id,
            # which is random, so runs created in the same tick would order unpredictably.
            **({"created_at": created_at} if created_at else {}),
        )

    @parameterized.expand(
        [
            (TaskRun.Status.QUEUED, True),
            (TaskRun.Status.IN_PROGRESS, True),
            (TaskRun.Status.COMPLETED, False),
            (TaskRun.Status.FAILED, False),
            (TaskRun.Status.CANCELLED, False),
        ]
    )
    def test_only_a_live_run_is_waiting_on_anyone(self, status: str, expected: bool) -> None:
        run = self._run(status=status)
        mark_task_run_awaiting_input(run)

        self.assertEqual(run.is_awaiting_input, expected)

    def test_a_response_stops_the_run_waiting(self) -> None:
        run = self._run()
        mark_task_run_awaiting_input(run)

        clear_task_run_awaiting_input(run)

        run.refresh_from_db()
        self.assertIsNone(run.awaiting_input_at)
        self.assertFalse(run.is_awaiting_input)

    @parameterized.expand([("auto answered", True, False), ("nobody answered", False, True)])
    def test_relay_records_only_the_requests_a_person_owes(
        self, _name: str, auto_responded: bool, expected_marked: bool
    ) -> None:
        run = self._run()
        with patch(
            "products.tasks.backend.temporal.process_task.activities.relay_sandbox_events.try_auto_respond_permission_request",
            return_value=auto_responded,
        ):
            _broker_permission_request(run, PERMISSION_REQUEST)

        run.refresh_from_db()
        self.assertEqual(run.awaiting_input_at is not None, expected_marked)

    def test_the_awaiting_input_filter_lists_only_tasks_someone_still_owes(self) -> None:
        waiting_run = self._run()
        mark_task_run_awaiting_input(waiting_run)
        answered_task = Task.objects.create(team=self.team, title="Answered", created_by=self.user)
        self._run(task=answered_task)
        ended_task = Task.objects.create(team=self.team, title="Ended", created_by=self.user)
        mark_task_run_awaiting_input(self._run(task=ended_task, status=TaskRun.Status.COMPLETED))

        tasks = tasks_facade.list_tasks(self.team.id, self.user.id, filters={"awaiting_input": True})

        self.assertEqual([task.id for task in tasks], [self.task.id])

    def test_an_ask_a_newer_run_superseded_is_not_listed(self) -> None:
        mark_task_run_awaiting_input(self._run(created_at=datetime(2026, 8, 10, 9, 0, tzinfo=UTC)))
        self._run(status=TaskRun.Status.COMPLETED, created_at=datetime(2026, 8, 10, 10, 0, tzinfo=UTC))

        tasks = tasks_facade.list_tasks(self.team.id, self.user.id, filters={"awaiting_input": True})

        self.assertEqual(tasks, [])

    def test_a_replayed_ask_does_not_revive_an_answered_request(self) -> None:
        run = self._run()
        mark_task_run_awaiting_input(run, PERMISSION_REQUEST["request_id"])
        clear_task_run_awaiting_input(run, PERMISSION_REQUEST["request_id"])

        mark_task_run_awaiting_input(run, PERMISSION_REQUEST["request_id"])

        run.refresh_from_db()
        self.assertIsNone(run.awaiting_input_at)
