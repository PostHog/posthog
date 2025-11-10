import pytest

from django.core.exceptions import ValidationError

from asgiref.sync import async_to_sync

from products.tasks.backend.models import Task
from products.tasks.backend.temporal.exceptions import TaskInvalidStateError, TaskNotFoundError
from products.tasks.backend.temporal.process_task.activities.get_task_details import TaskDetails, get_task_details


class TestGetTaskDetailsActivity:
    def _create_task_with_repo(self, ateam, auser, github_integration, repo_config):
        return Task.objects.create(
            team=ateam,
            title="Test Task",
            description="Test task description",
            origin_product=Task.OriginProduct.USER_CREATED,
            position=0,
            github_integration=github_integration,
            repository_config=repo_config,
            created_by=auser,
        )

    def _cleanup_task(self, task):
        task.delete()

    @pytest.mark.django_db
    def test_get_task_details_success(self, activity_environment, test_task):
        result = async_to_sync(activity_environment.run)(get_task_details, str(test_task.id))

        assert isinstance(result, TaskDetails)
        assert result.task_id == str(test_task.id)
        assert result.team_id == test_task.team_id
        assert result.github_integration_id == test_task.github_integration_id
        assert result.repository == "posthog/posthog-js"

    @pytest.mark.django_db
    def test_get_task_details_task_not_found(self, activity_environment):
        non_existent_task_id = "550e8400-e29b-41d4-a716-446655440000"

        with pytest.raises(TaskNotFoundError):
            async_to_sync(activity_environment.run)(get_task_details, non_existent_task_id)

    @pytest.mark.django_db
    def test_get_task_details_invalid_uuid(self, activity_environment):
        invalid_task_id = "not-a-uuid"

        with pytest.raises(ValidationError):
            async_to_sync(activity_environment.run)(get_task_details, invalid_task_id)

    @pytest.mark.django_db
    def test_get_task_details_with_different_repository(self, activity_environment, ateam, auser, github_integration):
        task = self._create_task_with_repo(
            ateam, auser, github_integration, {"organization": "posthog", "repository": "posthog-js"}
        )

        try:
            result = async_to_sync(activity_environment.run)(get_task_details, str(task.id))

            assert result.task_id == str(task.id)
            assert result.team_id == task.team_id
            assert result.github_integration_id == github_integration.id
            assert result.repository == "posthog/posthog-js"
        finally:
            self._cleanup_task(task)

    @pytest.mark.django_db
    def test_get_task_details_with_missing_repository(self, activity_environment, ateam, auser, github_integration):
        task = self._create_task_with_repo(
            ateam,
            auser,
            github_integration,
            {"organization": "test-org"},
        )

        try:
            with pytest.raises(TaskInvalidStateError):
                async_to_sync(activity_environment.run)(get_task_details, str(task.id))
        finally:
            self._cleanup_task(task)
