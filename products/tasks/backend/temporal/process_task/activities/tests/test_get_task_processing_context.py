import pytest
from unittest.mock import patch

from django.core.exceptions import ValidationError

from asgiref.sync import async_to_sync

from posthog.models import OrganizationMembership, User
from posthog.models.user_integration import UserIntegration

from products.tasks.backend.models import SandboxEnvironment, Task
from products.tasks.backend.temporal.exceptions import TaskInvalidStateError, TaskNotFoundError
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

        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.close_old_database_connections"
        ) as close_old_database_connections_mock:
            result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert isinstance(result, TaskProcessingContext)
        assert result.task_id == str(test_task.id)
        assert result.run_id == str(task_run.id)
        assert result.team_id == test_task.team_id
        assert result.github_integration_id == test_task.github_integration_id
        assert result.repository == "posthog/posthog-js"
        assert result.create_pr is True
        close_old_database_connections_mock.assert_called_once()

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

    @pytest.mark.django_db
    def test_get_task_processing_context_resolves_user_github_integration_without_repository(
        self, activity_environment, team, user
    ):
        user_integration = UserIntegration.objects.create(
            user=user,
            kind="github",
            integration_id="12345",
            config={"installation_id": "12345"},
            sensitive_config={"user_access_token": "gho_test", "user_refresh_token": "ghr_test"},
        )
        task = Task.objects.create(
            team=team,
            created_by=user,
            title="Slack task without repository",
            description="Clone a repo later from chat",
            origin_product=Task.OriginProduct.SLACK,
        )
        task_run = task.create_run(extra_state={"interaction_origin": "slack", "pr_authorship_mode": "user"})

        result = async_to_sync(activity_environment.run)(
            get_task_processing_context,
            GetTaskProcessingContextInput(run_id=str(task_run.id)),
        )

        assert result.repository is None
        assert result.github_integration_id is None
        assert result.github_user_integration_id == str(user_integration.id)
        assert result.has_github_credentials is True

    @pytest.mark.django_db
    def test_get_task_processing_context_resolves_allowed_domains(self, activity_environment, test_task):
        sandbox_environment = SandboxEnvironment.objects.create(
            team=test_task.team,
            created_by=test_task.created_by,
            name="Restricted env",
            network_access_level=SandboxEnvironment.NetworkAccessLevel.CUSTOM,
            allowed_domains=["example.com"],
        )
        task_run = test_task.create_run(extra_state={"sandbox_environment_id": str(sandbox_environment.id)})

        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))
        result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert result.sandbox_environment_id == str(sandbox_environment.id)
        assert result.sandbox_environment_name == "Restricted env"
        assert result.allowed_domains == ["example.com"]

    @pytest.mark.django_db
    def test_get_task_processing_context_preserves_empty_restricted_domains(self, activity_environment, test_task):
        sandbox_environment = SandboxEnvironment.objects.create(
            team=test_task.team,
            created_by=test_task.created_by,
            name="Restricted empty env",
            network_access_level=SandboxEnvironment.NetworkAccessLevel.CUSTOM,
            allowed_domains=[],
        )
        task_run = test_task.create_run(extra_state={"sandbox_environment_id": str(sandbox_environment.id)})

        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))
        result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert result.sandbox_environment_id == str(sandbox_environment.id)
        assert result.allowed_domains == []

    @pytest.mark.django_db
    def test_get_task_processing_context_keeps_full_access_unrestricted(self, activity_environment, test_task):
        sandbox_environment = SandboxEnvironment.objects.create(
            team=test_task.team,
            created_by=test_task.created_by,
            name="Full access env",
            network_access_level=SandboxEnvironment.NetworkAccessLevel.FULL,
            allowed_domains=[],
        )
        task_run = test_task.create_run(extra_state={"sandbox_environment_id": str(sandbox_environment.id)})

        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))
        result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert result.sandbox_environment_id == str(sandbox_environment.id)
        assert result.allowed_domains is None

    @pytest.mark.django_db
    def test_get_task_processing_context_rejects_other_users_private_sandbox_environment(
        self, activity_environment, test_task
    ):
        other_user = User.objects.create_user(
            email="victim@example.com",
            first_name="Victim",
            password="password",
        )
        OrganizationMembership.objects.create(
            user=other_user,
            organization_id=test_task.team.organization_id,
        )
        sandbox_environment = SandboxEnvironment.objects.create(
            team=test_task.team,
            created_by=other_user,
            name="Victim's private env",
            private=True,
            environment_variables={"SECRET_KEY": "secret_value"},
        )
        task_run = test_task.create_run(extra_state={"sandbox_environment_id": str(sandbox_environment.id)})

        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))

        with pytest.raises(TaskInvalidStateError):
            async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "flag_value, expected",
        [
            (True, True),
            (False, False),
            (None, False),  # the activity coalesces None to False
        ],
    )
    def test_pr_loop_enabled_reflects_feature_flag(self, activity_environment, test_task, flag_value, expected):
        task_run = test_task.create_run()
        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))

        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            return_value=flag_value,
        ) as feature_enabled_mock:
            result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert result.pr_loop_enabled is expected
        feature_enabled_mock.assert_called_once()
        args, kwargs = feature_enabled_mock.call_args
        assert args[0] == "tasks-pr-loop"
        assert kwargs["distinct_id"] == (test_task.created_by.distinct_id or "process_task_workflow")
        org_id = str(test_task.team.organization_id)
        assert kwargs["groups"] == {"organization": org_id}
        assert kwargs["group_properties"] == {"organization": {"id": org_id}}

    @pytest.mark.django_db
    def test_get_task_processing_context_exposes_ci_prompt(self, activity_environment, test_task):
        custom_prompt = "Re-run the failed mypy checks and push a fix."
        test_task.ci_prompt = custom_prompt
        test_task.save(update_fields=["ci_prompt"])

        task_run = test_task.create_run()
        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))
        result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert result.ci_prompt == custom_prompt

    @pytest.mark.django_db
    def test_get_task_processing_context_exposes_runtime_metadata(self, activity_environment, test_task):
        task_run = test_task.create_run(
            extra_state={
                "runtime_adapter": "codex",
                "provider": "openai",
                "model": "gpt-5.3-codex",
                "reasoning_effort": "high",
            }
        )

        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))
        result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert result.runtime_adapter == "codex"
        assert result.provider == "openai"
        assert result.model == "gpt-5.3-codex"
        assert result.reasoning_effort == "high"
