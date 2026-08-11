from django.test import TestCase

from parameterized import parameterized

from posthog.models import Organization, Team

from products.tasks.backend.facade.api import _task_run_detail_to_dto
from products.tasks.backend.logic.services.awaiting_input import clear_run_awaiting_input, track_permission_state
from products.tasks.backend.models import Task, TaskRun


def _request_event(request_id: str) -> dict:
    return {
        "type": "notification",
        "notification": {
            "method": "_posthog/permission_request",
            "params": {
                "requestId": request_id,
                "toolCall": {"toolCallId": f"tool-{request_id}"},
                "options": [{"optionId": "allow", "kind": "allow_once", "name": "Yes"}],
            },
        },
    }


def _resolved_event(request_id: str) -> dict:
    return {
        "type": "notification",
        "notification": {
            "method": "_posthog/permission_resolved",
            "params": {"requestId": request_id, "optionId": "allow"},
        },
    }


class TestRunAwaitingInput(TestCase):
    def setUp(self) -> None:
        super().setUp()
        organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=organization, name="Test Team")
        self.task = Task.objects.create(team=self.team, title="Test Task", description="Test Description")
        self.task_run: TaskRun = self.task.create_run()

    def _track(self, event: dict) -> None:
        track_permission_state(str(self.task_run.id), event)
        self.task_run.refresh_from_db()

    @parameterized.expand(
        [
            ("answered", "req-1", None),
            # A stale answer must not clear a question the agent has since asked.
            ("answered_a_different_request", "req-other", "req-1"),
        ]
    )
    def test_resolving_a_request(self, _name: str, resolved_id: str, expected: str | None) -> None:
        self._track(_request_event("req-1"))
        self.assertEqual(self.task_run.awaiting_input_request_id, "req-1")

        self._track(_resolved_event(resolved_id))
        self.assertEqual(self.task_run.awaiting_input_request_id, expected)

    def test_a_later_request_replaces_the_one_before_it(self) -> None:
        self._track(_request_event("req-1"))
        self._track(_request_event("req-2"))
        self.assertEqual(self.task_run.awaiting_input_request_id, "req-2")

    def test_clearing_drops_whatever_the_run_was_waiting_on(self) -> None:
        self._track(_request_event("req-1"))

        clear_run_awaiting_input(str(self.task_run.id))
        self.task_run.refresh_from_db()
        self.assertIsNone(self.task_run.awaiting_input_request_id)

    @parameterized.expand(
        [
            (TaskRun.Status.IN_PROGRESS, True),
            (TaskRun.Status.QUEUED, True),
            # A run that has ended is not waiting on anyone, whatever it last asked.
            (TaskRun.Status.COMPLETED, False),
            (TaskRun.Status.FAILED, False),
            (TaskRun.Status.CANCELLED, False),
        ]
    )
    def test_reported_awaiting_input_by_run_status(self, status: str, expected: bool) -> None:
        self.task_run.status = status
        self.task_run.awaiting_input_request_id = "req-1"
        self.task_run.save(update_fields=["status", "awaiting_input_request_id"])

        self.assertEqual(_task_run_detail_to_dto(self.task_run).awaiting_input, expected)
