from unittest.mock import AsyncMock, Mock, patch

from django.test import TransactionTestCase, override_settings

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.models.user import User

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.client import (
    execute_task_processing_workflow,
    execute_task_processing_workflow_async,
    resume_task_in_cloud_workflow,
)


@override_settings(DEBUG=False)
class TestExecuteTaskProcessingWorkflow(TransactionTestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="test@example.com")
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Test Task",
            description="Test Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

    def _create_run(self, status: TaskRun.Status = TaskRun.Status.QUEUED) -> TaskRun:
        return TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=status,
        )

    def _assert_run_failed(self, run: TaskRun, expected_error: str) -> None:
        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.FAILED)
        self.assertEqual(run.error_message, expected_error)
        self.assertIsNotNone(run.completed_at)

    def _execute_workflow(self, executor: str, run: TaskRun, user_id: int | None) -> None:
        kwargs = {
            "task_id": str(self.task.id),
            "run_id": str(run.id),
            "team_id": self.team.id,
            "user_id": user_id,
        }
        if executor == "sync":
            execute_task_processing_workflow(**kwargs)
            return

        async_to_sync(execute_task_processing_workflow_async)(**kwargs)

    @parameterized.expand([("sync",), ("async",)])
    def test_marks_run_failed_when_temporal_start_fails(self, executor: str) -> None:
        run = self._create_run()
        client = Mock()
        client.start_workflow = AsyncMock(side_effect=RuntimeError("temporal unavailable"))

        connect_target = (
            "products.tasks.backend.temporal.client.sync_connect"
            if executor == "sync"
            else "products.tasks.backend.temporal.client.async_connect"
        )
        connect_mock = Mock(return_value=client) if executor == "sync" else AsyncMock(return_value=client)

        with (
            patch(connect_target, connect_mock),
            patch("products.tasks.backend.temporal.client.posthoganalytics.feature_enabled", return_value=False),
        ):
            self._execute_workflow(executor, run, self.user.id)

        self._assert_run_failed(run, "Failed to start task workflow: temporal unavailable")

    @parameterized.expand([("sync",), ("async",)])
    def test_does_not_overwrite_run_that_already_started(self, executor: str) -> None:
        run = self._create_run(status=TaskRun.Status.IN_PROGRESS)
        client = Mock()
        client.start_workflow = AsyncMock(side_effect=RuntimeError("temporal unavailable"))

        connect_target = (
            "products.tasks.backend.temporal.client.sync_connect"
            if executor == "sync"
            else "products.tasks.backend.temporal.client.async_connect"
        )
        connect_mock = Mock(return_value=client) if executor == "sync" else AsyncMock(return_value=client)

        with (
            patch(connect_target, connect_mock),
            patch("products.tasks.backend.temporal.client.posthoganalytics.feature_enabled", return_value=False),
        ):
            self._execute_workflow(executor, run, self.user.id)

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.IN_PROGRESS)
        self.assertIsNone(run.error_message)
        self.assertIsNone(run.completed_at)

    @parameterized.expand([("sync",), ("async",)])
    def test_captures_sandbox_event_ingest_flag_before_starting_workflow(self, executor: str) -> None:
        run = self._create_run()
        client = Mock()
        client.start_workflow = AsyncMock()

        connect_target = (
            "products.tasks.backend.temporal.client.sync_connect"
            if executor == "sync"
            else "products.tasks.backend.temporal.client.async_connect"
        )
        connect_mock = Mock(return_value=client) if executor == "sync" else AsyncMock(return_value=client)

        with (
            patch(connect_target, connect_mock),
            patch("products.tasks.backend.temporal.client.posthoganalytics.feature_enabled", return_value=True) as flag,
        ):
            self._execute_workflow(executor, run, self.user.id)

        run.refresh_from_db()
        self.assertEqual(run.state["sandbox_event_ingest_enabled"], True)
        flag.assert_called_once_with(
            "tasks-cloud-runs-sandbox-event-ingest",
            distinct_id="process_task_workflow",
            groups={"organization": str(self.organization.id)},
            group_properties={"organization": {"id": str(self.organization.id)}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )

    def test_captures_sandbox_event_ingest_flag_before_resuming_workflow(self) -> None:
        run = self._create_run()
        client = Mock()
        client.start_workflow = AsyncMock()

        with (
            patch("products.tasks.backend.temporal.client.sync_connect", return_value=client),
            patch("products.tasks.backend.temporal.client.posthoganalytics.feature_enabled", return_value=True),
        ):
            resume_task_in_cloud_workflow(str(run.id), run.workflow_id)

        run.refresh_from_db()
        self.assertEqual(run.state["sandbox_event_ingest_enabled"], True)

    @parameterized.expand([("sync",), ("async",)])
    def test_captures_sandbox_event_ingest_flag_without_clobbering_concurrent_state(self, executor: str) -> None:
        run = self._create_run()
        client = Mock()
        client.start_workflow = AsyncMock()
        connect_target = (
            "products.tasks.backend.temporal.client.sync_connect"
            if executor == "sync"
            else "products.tasks.backend.temporal.client.async_connect"
        )
        connect_mock = Mock(return_value=client) if executor == "sync" else AsyncMock(return_value=client)

        def _feature_enabled(*args: object, **kwargs: object) -> bool:
            TaskRun.update_state_atomic(str(run.id), updates={"pending_user_message_ids": ["message-1"]})
            return True

        with (
            patch(connect_target, connect_mock),
            patch(
                "products.tasks.backend.temporal.client.posthoganalytics.feature_enabled",
                side_effect=_feature_enabled,
            ),
        ):
            self._execute_workflow(executor, run, self.user.id)

        run.refresh_from_db()
        self.assertEqual(run.state["pending_user_message_ids"], ["message-1"])
        self.assertEqual(run.state["sandbox_event_ingest_enabled"], True)
