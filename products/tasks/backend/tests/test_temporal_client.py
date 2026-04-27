from unittest.mock import AsyncMock, Mock, patch

from django.test import TransactionTestCase, override_settings

from asgiref.sync import async_to_sync

from posthog.models import Organization, Team
from posthog.models.user import User

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.client import (
    execute_task_processing_workflow,
    execute_task_processing_workflow_async,
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

    def test_marks_run_failed_when_user_id_is_missing(self) -> None:
        run = self._create_run()

        execute_task_processing_workflow(
            task_id=str(self.task.id),
            run_id=str(run.id),
            team_id=self.team.id,
            user_id=None,
        )

        self._assert_run_failed(run, "Failed to start task workflow: missing user id")

    @patch("products.tasks.backend.temporal.client.posthoganalytics.feature_enabled", return_value=False)
    def test_marks_run_failed_when_tasks_feature_is_disabled(self, mock_feature_enabled: Mock) -> None:
        run = self._create_run()

        execute_task_processing_workflow(
            task_id=str(self.task.id),
            run_id=str(run.id),
            team_id=self.team.id,
            user_id=self.user.id,
        )

        self._assert_run_failed(run, "Failed to start task workflow: tasks feature is disabled")
        mock_feature_enabled.assert_called_once()

    @patch("products.tasks.backend.temporal.client.sync_connect")
    @patch("products.tasks.backend.temporal.client.posthoganalytics.feature_enabled", return_value=True)
    def test_marks_run_failed_when_temporal_start_fails(
        self,
        mock_feature_enabled: Mock,
        mock_sync_connect: Mock,
    ) -> None:
        run = self._create_run()
        client = Mock()
        client.start_workflow = AsyncMock(side_effect=RuntimeError("temporal unavailable"))
        mock_sync_connect.return_value = client

        execute_task_processing_workflow(
            task_id=str(self.task.id),
            run_id=str(run.id),
            team_id=self.team.id,
            user_id=self.user.id,
        )

        self._assert_run_failed(run, "Failed to start task workflow: temporal unavailable")
        mock_feature_enabled.assert_called_once()

    @patch("products.tasks.backend.temporal.client.sync_connect")
    @patch("products.tasks.backend.temporal.client.posthoganalytics.feature_enabled", return_value=True)
    def test_does_not_overwrite_run_that_already_started(
        self,
        mock_feature_enabled: Mock,
        mock_sync_connect: Mock,
    ) -> None:
        run = self._create_run(status=TaskRun.Status.IN_PROGRESS)
        client = Mock()
        client.start_workflow = AsyncMock(side_effect=RuntimeError("temporal unavailable"))
        mock_sync_connect.return_value = client

        execute_task_processing_workflow(
            task_id=str(self.task.id),
            run_id=str(run.id),
            team_id=self.team.id,
            user_id=self.user.id,
        )

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.IN_PROGRESS)
        self.assertIsNone(run.error_message)
        self.assertIsNone(run.completed_at)
        mock_feature_enabled.assert_called_once()

    @patch("products.tasks.backend.temporal.client.posthoganalytics.feature_enabled", return_value=False)
    def test_async_marks_run_failed_when_tasks_feature_is_disabled(self, mock_feature_enabled: Mock) -> None:
        run = self._create_run()

        async_to_sync(execute_task_processing_workflow_async)(
            task_id=str(self.task.id),
            run_id=str(run.id),
            team_id=self.team.id,
            user_id=self.user.id,
        )

        self._assert_run_failed(run, "Failed to start task workflow: tasks feature is disabled")
        mock_feature_enabled.assert_called_once()
