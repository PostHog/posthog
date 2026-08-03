from unittest.mock import patch

from django.test import TestCase

from parameterized import parameterized
from temporalio.service import RPCError, RPCStatusCode

from posthog.models import Organization, Team

from products.tasks.backend.logic.services.orchestration import (
    MAX_ORCHESTRATION_RESUME_ATTEMPTS,
    ORCHESTRATION_RESUME_STATE_KEY,
    PENDING_ORCHESTRATION_WAKES_STATE_KEY,
    notify_parent_of_child_event,
    resume_parent_with_pending_wakes,
)
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.execute_sandbox.workflow import FOLLOWUP_SOURCE_CHILD


class TestNotifyParentOfChildEvent(TestCase):
    team: Team

    @classmethod
    def setUpTestData(cls) -> None:
        organization = Organization.objects.create(name="Orchestration test")
        cls.team = Team.objects.create(organization=organization, name="Test team")

    def _task(self, title: str) -> Task:
        return Task.objects.create(
            team=self.team,
            title=title,
            description="Test task",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

    def _runs(self, status: str, *, error_message: str | None = None) -> tuple[TaskRun, TaskRun]:
        parent_task = self._task("Parent task")
        parent_run = parent_task.create_run(mode="background")
        parent_run.status = TaskRun.Status.IN_PROGRESS
        parent_run.save(update_fields=["status"])

        child_task = self._task("Child task")
        child_run = child_task.create_run(
            mode="background",
            extra_state={"parent_task_id": str(parent_task.id), "parent_run_id": str(parent_run.id), "wake_on": []},
        )
        child_run.status = status
        child_run.error_message = error_message
        child_run.output = {"pr_url": "https://github.com/PostHog/posthog/pull/123"}
        child_run.save(update_fields=["status", "error_message", "output"])
        return parent_run, child_run

    @parameterized.expand(
        [
            (TaskRun.Status.COMPLETED, None),
            (TaskRun.Status.FAILED, "Tests failed"),
            (TaskRun.Status.CANCELLED, None),
        ]
    )
    @patch("products.tasks.backend.logic.services.orchestration.signal_task_followup_message")
    def test_signals_live_parent_with_server_built_message(self, status, error_message, mock_signal) -> None:
        parent_run, child_run = self._runs(status, error_message=error_message)

        notify_parent_of_child_event(child_run, "terminal")

        message = mock_signal.call_args.args[1]
        self.assertIn(f"Status: {status}", message)
        self.assertIn("Child task", message)
        self.assertIn("https://github.com/PostHog/posthog/pull/123", message)
        if error_message:
            self.assertIn(error_message, message)
        mock_signal.assert_called_once_with(
            parent_run.workflow_id,
            message,
            [],
            source=FOLLOWUP_SOURCE_CHILD,
        )

    @patch(
        "products.tasks.backend.logic.services.orchestration.signal_task_followup_message",
        side_effect=RPCError("workflow gone", RPCStatusCode.NOT_FOUND, b""),
    )
    @patch("products.tasks.backend.logic.services.orchestration._schedule_cold_resume")
    def test_queues_wake_when_parent_workflow_is_cold(self, mock_schedule, mock_signal) -> None:
        parent_run, child_run = self._runs(TaskRun.Status.COMPLETED)

        notify_parent_of_child_event(child_run, "terminal")

        parent_run.refresh_from_db()
        queued = parent_run.state[PENDING_ORCHESTRATION_WAKES_STATE_KEY]
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["child_run_id"], str(child_run.id))
        self.assertEqual(queued[0]["source"], FOLLOWUP_SOURCE_CHILD)
        mock_signal.assert_called_once()
        mock_schedule.assert_called_once_with(str(parent_run.id))

    @patch("products.tasks.backend.logic.services.orchestration.signal_task_followup_message")
    def test_run_without_parent_state_is_ignored(self, mock_signal) -> None:
        child_task = self._task("Independent task")
        child_run = child_task.create_run(mode="background")
        child_run.status = TaskRun.Status.COMPLETED
        child_run.save(update_fields=["status"])

        notify_parent_of_child_event(child_run, "terminal")

        mock_signal.assert_not_called()

    @patch("products.tasks.backend.logic.services.orchestration.signal_task_followup_message")
    @patch("products.tasks.backend.logic.services.orchestration.resume_task_run_in_cloud")
    def test_cold_resume_drains_a_burst_once(self, mock_resume, mock_signal) -> None:
        parent_run, child_run = self._runs(TaskRun.Status.COMPLETED)
        second_child = self._task("Second child").create_run(
            mode="background",
            extra_state={"parent_task_id": str(parent_run.task_id), "parent_run_id": str(parent_run.id)},
        )
        second_child.status = TaskRun.Status.COMPLETED
        second_child.save(update_fields=["status"])
        with patch("products.tasks.backend.logic.services.orchestration._schedule_cold_resume"):
            parent_run.status = TaskRun.Status.COMPLETED
            parent_run.save(update_fields=["status"])
            notify_parent_of_child_event(child_run, "terminal")
            notify_parent_of_child_event(second_child, "terminal")
        mock_resume.return_value = ("resumed", None, None)

        self.assertTrue(resume_parent_with_pending_wakes(str(parent_run.id)))

        mock_resume.assert_called_once()
        self.assertIn("Child task", mock_signal.call_args.args[1])
        self.assertIn("Second child", mock_signal.call_args.args[1])
        parent_run.refresh_from_db()
        self.assertNotIn(PENDING_ORCHESTRATION_WAKES_STATE_KEY, parent_run.state)

    @patch("products.tasks.backend.logic.services.orchestration._schedule_cold_resume")
    @patch("products.tasks.backend.logic.services.orchestration.signal_task_followup_message")
    @patch("products.tasks.backend.logic.services.orchestration.resume_task_run_in_cloud")
    def test_wake_arriving_during_resume_is_scheduled_for_delivery(
        self, mock_resume, mock_signal, mock_schedule
    ) -> None:
        parent_run, child_run = self._runs(TaskRun.Status.COMPLETED)
        parent_run.status = TaskRun.Status.COMPLETED
        parent_run.save(update_fields=["status"])
        with patch("products.tasks.backend.logic.services.orchestration._schedule_cold_resume"):
            notify_parent_of_child_event(child_run, "terminal")

        def enqueue_during_resume(*args):
            TaskRun.mutate_state_atomic(
                parent_run.id,
                lambda state: state[PENDING_ORCHESTRATION_WAKES_STATE_KEY].append(
                    {"message": "late wake", "event": "terminal", "child_run_id": "late"}
                ),
            )
            return "resumed", None, None

        mock_resume.side_effect = enqueue_during_resume
        self.assertTrue(resume_parent_with_pending_wakes(str(parent_run.id)))

        parent_run.refresh_from_db()
        self.assertEqual(parent_run.state[PENDING_ORCHESTRATION_WAKES_STATE_KEY][0]["message"], "late wake")
        self.assertFalse(parent_run.state[ORCHESTRATION_RESUME_STATE_KEY]["in_flight"])
        mock_signal.assert_called_once()
        mock_schedule.assert_called_once_with(str(parent_run.id))

    @patch("products.tasks.backend.logic.services.orchestration._notify_resume_exhausted")
    @patch(
        "products.tasks.backend.logic.services.orchestration.resume_task_run_in_cloud",
        return_value=("workflow_failed", None, None),
    )
    def test_resume_failure_caps_and_notifies(self, mock_resume, mock_notify) -> None:
        parent_run, child_run = self._runs(TaskRun.Status.COMPLETED)
        parent_run.status = TaskRun.Status.COMPLETED
        parent_run.save(update_fields=["status"])
        with patch("products.tasks.backend.logic.services.orchestration._schedule_cold_resume"):
            notify_parent_of_child_event(child_run, "terminal")

        for _ in range(MAX_ORCHESTRATION_RESUME_ATTEMPTS):
            with self.assertRaises(RuntimeError):
                resume_parent_with_pending_wakes(str(parent_run.id))

        self.assertFalse(resume_parent_with_pending_wakes(str(parent_run.id)))
        self.assertEqual(mock_resume.call_count, MAX_ORCHESTRATION_RESUME_ATTEMPTS)
        mock_notify.assert_called()
        parent_run.refresh_from_db()
        self.assertEqual(len(parent_run.state[PENDING_ORCHESTRATION_WAKES_STATE_KEY]), 1)
