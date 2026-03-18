import pytest

from django.core.exceptions import ValidationError

from asgiref.sync import async_to_sync

from products.tasks.backend.models import Task
from products.tasks.backend.temporal.exceptions import TaskNotFoundError
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import (
    GetTaskProcessingContextInput,
    TaskProcessingContext,
    get_task_processing_context,
)


@pytest.mark.requires_secrets
class TestGetTaskProcessingContextActivity:
    def _create_task_with_repo(self, team, user, github_integration, repo_config):
        return Task.objects.create(
            team=team,
            title="Test Task",
            description="Test task description",
            origin_product=Task.OriginProduct.USER_CREATED,
            github_integration=github_integration,
            repository=repo_config,
            created_by=user,
        )

    def _cleanup_task(self, task):
        task.soft_delete()

    @pytest.mark.django_db
    def test_get_task_processing_context_success(self, activity_environment, test_task):
        task_run = test_task.create_run()
        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))
        result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert isinstance(result, TaskProcessingContext)
        assert result.task_id == str(test_task.id)
        assert result.run_id == str(task_run.id)
        assert result.team_id == test_task.team_id
        assert result.github_integration_id == test_task.github_integration_id
        assert result.repository == "posthog/posthog-js"
        assert result.create_pr is True

    @pytest.mark.django_db
    def test_get_task_processing_context_task_not_found(self, activity_environment):
        non_existent_run_id = "550e8400-e29b-41d4-a716-446655440000"
        input_data = GetTaskProcessingContextInput(run_id=non_existent_run_id)

        with pytest.raises(TaskNotFoundError):
            async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

    @pytest.mark.django_db
    def test_get_task_processing_context_invalid_uuid(self, activity_environment):
        invalid_run_id = "not-a-uuid"
        input_data = GetTaskProcessingContextInput(run_id=invalid_run_id)

        with pytest.raises(ValidationError):
            async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

    @pytest.mark.django_db
    def test_get_task_processing_context_with_different_repository(
        self, activity_environment, team, user, github_integration
    ):
        task = self._create_task_with_repo(team, user, github_integration, "posthog/posthog-js")
        task_run = task.create_run()

        try:
            input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))
            result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

            assert result.task_id == str(task.id)
            assert result.run_id == str(task_run.id)
            assert result.team_id == task.team_id
            assert result.github_integration_id == github_integration.id
            assert result.repository == "posthog/posthog-js"
        finally:
            self._cleanup_task(task)

    @pytest.mark.django_db
    def test_get_task_processing_context_with_create_pr_false(self, activity_environment, test_task):
        task_run = test_task.create_run()
        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id), create_pr=False)
        result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert isinstance(result, TaskProcessingContext)
        assert result.create_pr is False
