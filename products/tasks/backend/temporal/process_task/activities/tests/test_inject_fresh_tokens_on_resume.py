import pytest
from unittest.mock import MagicMock, patch

from asgiref.sync import async_to_sync

from products.tasks.backend.services.agentsh import ENV_FILE
from products.tasks.backend.services.sandbox import ExecutionResult
from products.tasks.backend.temporal.process_task.activities.provision_sandbox import (
    InjectFreshTokensOnResumeInput,
    inject_fresh_tokens_on_resume,
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
        from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import (
            TaskProcessingContext,
        )

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

        assert sandbox.write_file.call_count == 1
