from types import SimpleNamespace

from unittest.mock import Mock, patch

from asgiref.sync import async_to_sync
from temporalio.testing import ActivityEnvironment

from products.hogbot.backend.temporal.activities.create_hogbot_sandbox import (
    CreateHogbotSandboxInput,
    create_hogbot_sandbox,
)
from products.tasks.backend.services.sandbox import SandboxTemplate


def _execution_result(*, exit_code: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(exit_code=exit_code, stdout=stdout, stderr=stderr)


def _sandbox() -> Mock:
    sandbox = Mock()
    sandbox.id = "sb-1"
    sandbox.get_connect_credentials.return_value = SimpleNamespace(url="http://sandbox", token="token")
    sandbox.clone_repository.return_value = _execution_result()
    sandbox.execute.return_value = _execution_result()
    return sandbox


class TestCreateHogbotSandboxActivity:
    def test_create_hogbot_sandbox_uses_runtime_snapshot_without_recloning_repository(self) -> None:
        sandbox = _sandbox()
        runtime = SimpleNamespace(latest_snapshot_external_id="snap-1")
        fake_user = SimpleNamespace(id=17)

        with (
            patch(
                "products.hogbot.backend.temporal.activities.create_hogbot_sandbox.HogbotRuntime.objects.get_or_create",
                return_value=(runtime, False),
            ),
            patch(
                "products.hogbot.backend.temporal.activities.create_hogbot_sandbox.Sandbox.create",
                return_value=sandbox,
            ) as mock_create,
            patch(
                "products.hogbot.backend.temporal.activities.create_hogbot_sandbox._get_github_token",
                return_value="github-token",
            ),
            patch(
                "products.hogbot.backend.temporal.activities.create_hogbot_sandbox._get_token_user",
                return_value=fake_user,
            ),
            patch(
                "products.hogbot.backend.temporal.activities.create_hogbot_sandbox.create_oauth_access_token_for_user",
                return_value="oauth-token",
            ) as mock_access_token,
            patch(
                "products.hogbot.backend.temporal.activities.create_hogbot_sandbox.get_sandbox_api_url",
                return_value="http://posthog.test",
            ),
        ):
            result = async_to_sync(ActivityEnvironment().run)(
                create_hogbot_sandbox,
                CreateHogbotSandboxInput(
                    team_id=1,
                    user_id=17,
                    repository="PostHog/PostHog",
                    github_integration_id=7,
                ),
            )

        config = mock_create.call_args.args[0]
        assert config.snapshot_external_id == "snap-1"
        assert config.template == SandboxTemplate.HOGBOT_BASE
        assert config.environment_variables == {
            "POSTHOG_PERSONAL_API_KEY": "oauth-token",
            "POSTHOG_API_URL": "http://posthog.test",
            "POSTHOG_PROJECT_ID": "1",
            "GITHUB_TOKEN": "github-token",
        }
        mock_access_token.assert_called_once_with(fake_user, 1, scopes=["project:write", "project:read", "organization:read", "user:read"])
        sandbox.clone_repository.assert_not_called()
        sandbox.execute.assert_not_called()
        assert result.sandbox_id == "sb-1"
        assert result.sandbox_url == "http://sandbox"
        assert result.connect_token == "token"

    def test_create_hogbot_sandbox_clones_repository_when_snapshot_is_unavailable(self) -> None:
        sandbox = _sandbox()
        runtime = SimpleNamespace(latest_snapshot_external_id=None)
        fake_user = SimpleNamespace(id=21)

        with (
            patch(
                "products.hogbot.backend.temporal.activities.create_hogbot_sandbox.HogbotRuntime.objects.get_or_create",
                return_value=(runtime, False),
            ),
            patch(
                "products.hogbot.backend.temporal.activities.create_hogbot_sandbox.Sandbox.create",
                return_value=sandbox,
            ) as mock_create,
            patch(
                "products.hogbot.backend.temporal.activities.create_hogbot_sandbox._get_github_token",
                return_value="github-token",
            ),
            patch(
                "products.hogbot.backend.temporal.activities.create_hogbot_sandbox._get_token_user",
                return_value=fake_user,
            ),
            patch(
                "products.hogbot.backend.temporal.activities.create_hogbot_sandbox.create_oauth_access_token_for_user",
                return_value="oauth-token",
            ),
            patch(
                "products.hogbot.backend.temporal.activities.create_hogbot_sandbox.get_sandbox_api_url",
                return_value="http://posthog.test",
            ),
        ):
            result = async_to_sync(ActivityEnvironment().run)(
                create_hogbot_sandbox,
                CreateHogbotSandboxInput(
                    team_id=1,
                    user_id=21,
                    repository="PostHog/PostHog",
                    github_integration_id=7,
                ),
            )

        config = mock_create.call_args.args[0]
        assert config.snapshot_external_id is None
        assert config.template == SandboxTemplate.HOGBOT_BASE
        sandbox.clone_repository.assert_called_once_with("PostHog/PostHog", github_token="github-token")
        assert result.sandbox_id == "sb-1"
