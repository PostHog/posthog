import asyncio
from typing import cast

from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.logic.services.workflow_dispatch import (
    WorkflowDispatchOptions,
    build_create_payload,
    create_dispatch,
    parse_create_payload,
    reschedule,
)
from products.tasks.backend.management.commands.run_task_workflow_dispatcher import Command, _user_can_dispatch
from products.tasks.backend.metrics import WORKFLOW_DISPATCH_ATTEMPT_TOTAL
from products.tasks.backend.temporal.process_task.workflow import PendingFollowup


class TestWorkflowDispatchPayload(SimpleTestCase):
    @patch("products.tasks.backend.logic.services.workflow_dispatch.transaction.get_connection")
    @patch("products.tasks.backend.logic.services.workflow_dispatch.TaskWorkflowDispatch.objects")
    def test_duplicate_create_dispatch_reuses_durable_intent(self, objects: Mock, get_connection: Mock) -> None:
        get_connection.return_value.in_atomic_block = True
        task_run = Mock(team_id=1)
        existing = Mock()
        queryset = objects.for_team.return_value
        queryset.get_or_create.return_value = (existing, False)

        result = create_dispatch(task_run, "create", {"version": 1}, "workflow-id")

        self.assertIs(result, existing)
        queryset.get_or_create.assert_called_once()
        queryset.update_or_create.assert_not_called()

    def test_create_payload_round_trip_preserves_followup_without_secrets(self) -> None:
        options = WorkflowDispatchOptions(
            user_id=42,
            create_pr=False,
            posthog_mcp_scopes="full",
            slack_thread_context={"channel_id": "C1"},
            prewarmed=True,
            initial_message=PendingFollowup(
                message="continue",
                artifact_ids=["artifact-1"],
                actor_user_id=42,
                message_id="message-1",
            ),
        )

        payload = build_create_payload(options)

        self.assertEqual(parse_create_payload(payload), options)
        self.assertNotIn("imported_mcp_servers", payload)

    def test_unknown_payload_version_is_rejected(self) -> None:
        payload = build_create_payload(WorkflowDispatchOptions())
        payload["version"] = 2

        with self.assertRaisesRegex(ValueError, "Unsupported workflow dispatch payload version"):
            parse_create_payload(payload)

    @patch("products.tasks.backend.logic.services.workflow_dispatch.TaskWorkflowDispatch.objects")
    @patch("products.tasks.backend.logic.services.workflow_dispatch.random.uniform", return_value=1.0)
    def test_reschedule_clamps_exponential_backoff(self, uniform: Mock, objects: Mock) -> None:
        objects.unscoped.return_value.get.return_value.attempt_count = 10_000

        reschedule("dispatch-id", "instance-id", "error")

        uniform.assert_called_once_with(1.0, 256.0)


class TestWorkflowDispatchPermissions(SimpleTestCase):
    @patch("products.tasks.backend.management.commands.run_task_workflow_dispatcher.UserPermissions")
    @patch("products.tasks.backend.management.commands.run_task_workflow_dispatcher.User.objects")
    def test_user_requires_current_effective_team_access(self, users: Mock, permissions: Mock) -> None:
        user = users.filter.return_value.first.return_value
        permissions.return_value.current_team.effective_membership_level = None
        run = Mock(task=Mock(team=Mock()))

        self.assertFalse(_user_can_dispatch(run, WorkflowDispatchOptions(user_id=42)))
        users.filter.assert_called_once_with(id=42, is_active=True)
        permissions.assert_called_once_with(user=user, team=run.task.team)

    @patch("products.tasks.backend.management.commands.run_task_workflow_dispatcher.User.objects")
    def test_trusted_system_dispatch_skips_user_lookup(self, users: Mock) -> None:
        run = Mock(task=Mock(team=Mock()))

        self.assertTrue(_user_can_dispatch(run, WorkflowDispatchOptions(skip_user_check=True)))
        users.filter.assert_not_called()


class TestDispatcherCompletionCallback(SimpleTestCase):
    @parameterized.expand(
        [
            ("failure", RuntimeError("connection reset"), 1),
            ("success", None, 0),
        ]
    )
    def test_completion_records_failure_outcome_only_on_exception(
        self, name: str, exception: Exception | None, expected_delta: int
    ) -> None:
        task_mock = Mock()
        task_mock.cancelled.return_value = False
        task_mock.exception.return_value = exception
        task = cast(asyncio.Task[None], task_mock)
        dispatch = Mock(id=f"dispatch-{name}", task_run_id="run-1", dispatch_kind="create")
        in_flight = {task}
        in_flight_ids = {dispatch.id}

        def failed_total() -> float:
            return WORKFLOW_DISPATCH_ATTEMPT_TOTAL.labels(kind="create", outcome="failed")._value.get()

        before = failed_total()
        Command._on_dispatch_done(in_flight, in_flight_ids, dispatch, task)

        self.assertEqual(failed_total() - before, expected_delta)
        self.assertNotIn(task, in_flight)
        self.assertNotIn(dispatch.id, in_flight_ids)
