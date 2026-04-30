import pytest
from unittest.mock import MagicMock, patch

from asgiref.sync import async_to_sync

from posthog.models import OrganizationMembership, User

from products.tasks.backend.models import SandboxEnvironment
from products.tasks.backend.services.agentsh import ENV_FILE
from products.tasks.backend.services.sandbox import ExecutionResult
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.provision_sandbox import (
    InjectFreshTokensOnResumeInput,
    PrepareSandboxForRepositoryInput,
    _build_environment_variables,
    inject_fresh_tokens_on_resume,
    prepare_sandbox_for_repository,
)


@pytest.mark.django_db
class TestInjectFreshTokensOnResumeActivity:
    @pytest.fixture
    def sandbox(self):
        fake = MagicMock()
        fake.execute.return_value = ExecutionResult(stdout="", stderr="", exit_code=0)
        fake.write_file.return_value = ExecutionResult(stdout="", stderr="", exit_code=0)
        return fake

    def test_refreshes_git_remote_url_and_env_file(self, activity_environment, task_context, test_task, sandbox):
        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.provision_sandbox.Sandbox.get_by_id",
                return_value=sandbox,
            ),
            patch(
                "products.tasks.backend.temporal.process_task.activities.provision_sandbox.get_sandbox_github_token",
                return_value="ghs_new",
            ),
            patch(
                "products.tasks.backend.temporal.process_task.activities.provision_sandbox.create_oauth_access_token",
                return_value="oauth_new",
            ),
        ):
            async_to_sync(activity_environment.run)(
                inject_fresh_tokens_on_resume,
                InjectFreshTokensOnResumeInput(
                    context=task_context,
                    sandbox_id="sandbox-abc",
                    repository=task_context.repository,
                ),
            )

        assert sandbox.execute.call_count == 1
        remote_command = sandbox.execute.call_args[0][0]
        assert "git remote set-url origin" in remote_command
        assert "x-access-token:ghs_new" in remote_command
        assert task_context.repository in remote_command

        assert sandbox.write_file.call_count == 1
        path, payload = sandbox.write_file.call_args[0]
        assert path == ENV_FILE
        decoded = payload.decode()
        # Null-separated `env -0` format.
        assert "\x00" in decoded
        assert "GITHUB_TOKEN=ghs_new" in decoded
        assert "GH_TOKEN=ghs_new" in decoded
        assert "POSTHOG_PERSONAL_API_KEY=oauth_new" in decoded

    def test_skips_git_remote_when_github_integration_missing(self, activity_environment, test_task, sandbox):
        context = TaskProcessingContext(
            task_id=str(test_task.id),
            run_id="run-id",
            team_id=test_task.team_id,
            team_uuid=str(test_task.team.uuid),
            organization_id=str(test_task.team.organization_id),
            github_integration_id=None,
            repository=test_task.repository,
            distinct_id="distinct",
        )

        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.provision_sandbox.Sandbox.get_by_id",
                return_value=sandbox,
            ),
            patch(
                "products.tasks.backend.temporal.process_task.activities.provision_sandbox.create_oauth_access_token",
                return_value="oauth_new",
            ),
        ):
            async_to_sync(activity_environment.run)(
                inject_fresh_tokens_on_resume,
                InjectFreshTokensOnResumeInput(
                    context=context,
                    sandbox_id="sandbox-abc",
                    repository=context.repository,
                ),
            )

        sandbox.execute.assert_not_called()
        # OAuth env is still written so POSTHOG_PERSONAL_API_KEY refreshes.
        assert sandbox.write_file.call_count == 1
        _, payload = sandbox.write_file.call_args[0]
        decoded = payload.decode()
        assert "POSTHOG_PERSONAL_API_KEY=oauth_new" in decoded
        assert "GITHUB_TOKEN" not in decoded

    def test_logs_warning_when_remote_url_update_fails(self, activity_environment, task_context, test_task, sandbox):
        sandbox.execute.return_value = ExecutionResult(stdout="", stderr="fatal: not a git repository", exit_code=128)

        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.provision_sandbox.Sandbox.get_by_id",
                return_value=sandbox,
            ),
            patch(
                "products.tasks.backend.temporal.process_task.activities.provision_sandbox.get_sandbox_github_token",
                return_value="ghs_new",
            ),
            patch(
                "products.tasks.backend.temporal.process_task.activities.provision_sandbox.create_oauth_access_token",
                return_value="oauth_new",
            ),
        ):
            # Should not raise — warnings are non-fatal.
            async_to_sync(activity_environment.run)(
                inject_fresh_tokens_on_resume,
                InjectFreshTokensOnResumeInput(
                    context=task_context,
                    sandbox_id="sandbox-abc",
                    repository=task_context.repository,
                ),
            )

        assert sandbox.execute.call_count == 1
        assert sandbox.write_file.call_count == 1

    def test_prepare_sandbox_injects_user_github_token_without_repository(self, activity_environment, team, user):
        from products.tasks.backend.models import Task

        task = Task.objects.create(
            team=team,
            created_by=user,
            title="Repo-less Slack task",
            description="Clone later from chat",
            origin_product=Task.OriginProduct.SLACK,
        )
        task_run = task.create_run(extra_state={"interaction_origin": "slack", "pr_authorship_mode": "user"})
        context = TaskProcessingContext(
            task_id=str(task.id),
            run_id=str(task_run.id),
            team_id=task.team_id,
            team_uuid=str(task.team.uuid),
            organization_id=str(task.team.organization_id),
            github_integration_id=None,
            github_user_integration_id="user-integration-id",
            repository=None,
            distinct_id=user.distinct_id or "test-distinct-id",
            task_created_by_id=user.id,
            state=task_run.state,
        )

        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.provision_sandbox.get_sandbox_github_token",
                return_value="gho_user",
            ) as get_sandbox_github_token_mock,
            patch(
                "products.tasks.backend.temporal.process_task.activities.provision_sandbox.create_oauth_access_token",
                return_value="oauth_new",
            ),
        ):
            prepared = async_to_sync(activity_environment.run)(
                prepare_sandbox_for_repository,
                PrepareSandboxForRepositoryInput(context=context),
            )

        get_sandbox_github_token_mock.assert_called_once()
        assert get_sandbox_github_token_mock.call_args.kwargs["repository"] is None
        assert prepared.repository is None
        assert prepared.github_token == "gho_user"
        assert prepared.environment_variables["GITHUB_TOKEN"] == "gho_user"
        assert prepared.environment_variables["GH_TOKEN"] == "gho_user"
        assert prepared.environment_variables["POSTHOG_PERSONAL_API_KEY"] == "oauth_new"

    def test_prepare_sandbox_injects_team_github_token_without_repository(
        self, activity_environment, team, user, github_integration
    ):
        from products.tasks.backend.models import Task

        task = Task.objects.create(
            team=team,
            created_by=user,
            title="Repo-less Slack task",
            description="Clone later from chat",
            origin_product=Task.OriginProduct.SLACK,
            github_integration=github_integration,
        )
        task_run = task.create_run(extra_state={"interaction_origin": "slack", "pr_authorship_mode": "bot"})
        context = TaskProcessingContext(
            task_id=str(task.id),
            run_id=str(task_run.id),
            team_id=task.team_id,
            team_uuid=str(task.team.uuid),
            organization_id=str(task.team.organization_id),
            github_integration_id=github_integration.id,
            github_user_integration_id=None,
            repository=None,
            distinct_id=user.distinct_id or "test-distinct-id",
            task_created_by_id=user.id,
            state=task_run.state,
        )

        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.provision_sandbox.get_sandbox_github_token",
                return_value="ghs_team",
            ) as get_sandbox_github_token_mock,
            patch(
                "products.tasks.backend.temporal.process_task.activities.provision_sandbox.create_oauth_access_token",
                return_value="oauth_new",
            ),
        ):
            prepared = async_to_sync(activity_environment.run)(
                prepare_sandbox_for_repository,
                PrepareSandboxForRepositoryInput(context=context),
            )

        get_sandbox_github_token_mock.assert_called_once()
        assert get_sandbox_github_token_mock.call_args.kwargs["repository"] is None
        assert prepared.repository is None
        assert prepared.github_token == "ghs_team"
        assert prepared.environment_variables["GITHUB_TOKEN"] == "ghs_team"
        assert prepared.environment_variables["GH_TOKEN"] == "ghs_team"
        assert prepared.environment_variables["POSTHOG_PERSONAL_API_KEY"] == "oauth_new"

    def test_build_environment_variables_ignores_other_users_private_sandbox_environment(
        self, task_context, test_task, test_task_run
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
        state = {"sandbox_environment_id": str(sandbox_environment.id)}
        test_task_run.state = state
        test_task_run.save(update_fields=["state"])
        task_context.state = state

        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.provision_sandbox.get_sandbox_api_url",
                return_value="https://sandbox.example.com",
            ),
            patch(
                "products.tasks.backend.temporal.process_task.activities.provision_sandbox.get_sandbox_jwt_public_key",
                return_value="jwt-public-key",
            ),
            patch(
                "products.tasks.backend.temporal.process_task.activities.provision_sandbox.get_git_identity_env_vars",
                return_value={},
            ),
        ):
            environment_variables = _build_environment_variables(task_context, test_task, "", "oauth_new")

        assert environment_variables["POSTHOG_PERSONAL_API_KEY"] == "oauth_new"
        assert environment_variables["POSTHOG_API_URL"] == "https://sandbox.example.com"
        assert "SECRET_KEY" not in environment_variables
