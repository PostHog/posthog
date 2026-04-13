from unittest.mock import MagicMock, patch

from django.test import TestCase

from parameterized import parameterized

from products.mcp_store.backend.facade.contracts import ActiveInstallationInfo
from products.tasks.backend.models import Task
from products.tasks.backend.temporal.process_task.utils import (
    McpServerConfig,
    get_git_identity_env_vars,
    get_sandbox_github_token,
    get_sandbox_ph_mcp_configs,
    get_user_mcp_server_configs,
)


class TestGetSandboxMcpConfigs(TestCase):
    TOKEN = "phx_test_token"
    PROJECT_ID = 42

    def _expected_headers(self, *, read_only: bool = True) -> list[dict[str, str]]:
        return [
            {"name": "Authorization", "value": f"Bearer {self.TOKEN}"},
            {"name": "x-posthog-project-id", "value": str(self.PROJECT_ID)},
            {"name": "x-posthog-mcp-version", "value": "2"},
            {"name": "x-posthog-read-only", "value": str(read_only).lower()},
        ]

    @parameterized.expand(
        [
            ("https://app.posthog.com", "https://mcp.posthog.com/mcp"),
            ("https://us.posthog.com", "https://mcp.posthog.com/mcp"),
            ("https://eu.posthog.com", "https://mcp-eu.posthog.com/mcp"),
        ]
    )
    def test_derives_mcp_config_from_site_url(self, site_url: str, expected_mcp_url: str) -> None:
        with patch("products.tasks.backend.temporal.process_task.utils.settings") as mock_settings:
            mock_settings.SANDBOX_MCP_URL = None
            mock_settings.SITE_URL = site_url
            configs = get_sandbox_ph_mcp_configs(self.TOKEN, self.PROJECT_ID)
            assert configs == [
                McpServerConfig(
                    type="http",
                    name="posthog",
                    url=expected_mcp_url,
                    headers=self._expected_headers(),
                )
            ]

    def test_explicit_sandbox_mcp_url_takes_precedence(self) -> None:
        with patch("products.tasks.backend.temporal.process_task.utils.settings") as mock_settings:
            mock_settings.SANDBOX_MCP_URL = "https://custom-mcp.example.com/mcp"
            mock_settings.SITE_URL = "https://app.posthog.com"
            configs = get_sandbox_ph_mcp_configs(self.TOKEN, self.PROJECT_ID)
            assert configs == [
                McpServerConfig(
                    type="http",
                    name="posthog",
                    url="https://custom-mcp.example.com/mcp",
                    headers=self._expected_headers(),
                )
            ]

    def test_full_scopes_preset(self) -> None:
        with patch("products.tasks.backend.temporal.process_task.utils.settings") as mock_settings:
            mock_settings.SANDBOX_MCP_URL = None
            mock_settings.SITE_URL = "https://app.posthog.com"
            configs = get_sandbox_ph_mcp_configs(self.TOKEN, self.PROJECT_ID, scopes="full")
            assert configs == [
                McpServerConfig(
                    type="http",
                    name="posthog",
                    url="https://mcp.posthog.com/mcp",
                    headers=self._expected_headers(read_only=False),
                )
            ]

    def test_custom_scopes_with_write(self) -> None:
        with patch("products.tasks.backend.temporal.process_task.utils.settings") as mock_settings:
            mock_settings.SANDBOX_MCP_URL = None
            mock_settings.SITE_URL = "https://app.posthog.com"
            configs = get_sandbox_ph_mcp_configs(
                self.TOKEN, self.PROJECT_ID, scopes=["feature_flag:read", "feature_flag:write"]
            )
            assert configs == [
                McpServerConfig(
                    type="http",
                    name="posthog",
                    url="https://mcp.posthog.com/mcp",
                    headers=self._expected_headers(read_only=False),
                )
            ]

    def test_custom_scopes_read_only(self) -> None:
        with patch("products.tasks.backend.temporal.process_task.utils.settings") as mock_settings:
            mock_settings.SANDBOX_MCP_URL = None
            mock_settings.SITE_URL = "https://app.posthog.com"
            configs = get_sandbox_ph_mcp_configs(
                self.TOKEN, self.PROJECT_ID, scopes=["feature_flag:read", "insight:read"]
            )
            assert configs == [
                McpServerConfig(
                    type="http",
                    name="posthog",
                    url="https://mcp.posthog.com/mcp",
                    headers=self._expected_headers(read_only=True),
                )
            ]

    @parameterized.expand(
        [
            ("http://localhost:8000",),
            ("https://custom.example.com",),
        ]
    )
    def test_returns_empty_list_for_unknown_hosts(self, site_url: str) -> None:
        with patch("products.tasks.backend.temporal.process_task.utils.settings") as mock_settings:
            mock_settings.SANDBOX_MCP_URL = None
            mock_settings.SITE_URL = site_url
            assert get_sandbox_ph_mcp_configs(self.TOKEN, self.PROJECT_ID) == []

    def test_returns_empty_list_when_no_site_url(self) -> None:
        with patch("products.tasks.backend.temporal.process_task.utils.settings") as mock_settings:
            mock_settings.SANDBOX_MCP_URL = None
            mock_settings.SITE_URL = ""
            assert get_sandbox_ph_mcp_configs(self.TOKEN, self.PROJECT_ID) == []


class TestMcpServerConfigToDict(TestCase):
    def test_minimal_config(self) -> None:
        config = McpServerConfig(type="http", name="posthog", url="https://mcp.posthog.com/mcp")
        assert config.to_dict() == {
            "type": "http",
            "name": "posthog",
            "url": "https://mcp.posthog.com/mcp",
            "headers": [],
        }

    def test_config_with_headers(self) -> None:
        config = McpServerConfig(
            type="http",
            name="posthog",
            url="https://mcp.example.com/mcp",
            headers=[{"name": "Authorization", "value": "Bearer token"}],
        )
        assert config.to_dict() == {
            "type": "http",
            "name": "posthog",
            "url": "https://mcp.example.com/mcp",
            "headers": [{"name": "Authorization", "value": "Bearer token"}],
        }


class TestFetchUserMcpServerConfigs(TestCase):
    TOKEN = "phx_test_token"
    TEAM_ID = 42
    USER_ID = 7
    API_BASE = "https://us.posthog.com"

    MOCK_FACADE = "products.tasks.backend.temporal.process_task.utils.get_active_installations"
    MOCK_API_URL = "products.tasks.backend.temporal.process_task.utils.get_sandbox_api_url"

    def _make_installation(self, **kwargs) -> ActiveInstallationInfo:
        defaults = {
            "id": "abc-123",
            "name": "Linear",
            "proxy_path": f"/api/environments/{self.TEAM_ID}/mcp_server_installations/abc-123/proxy/",
        }
        defaults.update(kwargs)
        return ActiveInstallationInfo(**defaults)

    @patch(MOCK_API_URL)
    @patch(MOCK_FACADE)
    def test_builds_configs_from_facade_results(self, mock_facade, mock_api_url) -> None:
        mock_api_url.return_value = self.API_BASE
        installation = self._make_installation()
        mock_facade.return_value = [installation]

        configs = get_user_mcp_server_configs(self.TOKEN, self.TEAM_ID, self.USER_ID)

        mock_facade.assert_called_once_with(self.TEAM_ID, self.USER_ID)
        assert configs == [
            McpServerConfig(
                type="http",
                name="Linear",
                url=f"{self.API_BASE}/api/environments/{self.TEAM_ID}/mcp_server_installations/abc-123/proxy/",
                headers=[{"name": "Authorization", "value": f"Bearer {self.TOKEN}"}],
            )
        ]

    @patch(MOCK_API_URL)
    @patch(MOCK_FACADE)
    def test_returns_empty_when_no_installations(self, mock_facade, mock_api_url) -> None:
        mock_api_url.return_value = self.API_BASE
        mock_facade.return_value = []

        assert get_user_mcp_server_configs(self.TOKEN, self.TEAM_ID, self.USER_ID) == []

    @patch(MOCK_API_URL)
    @patch(MOCK_FACADE)
    def test_strips_trailing_slash_from_api_url(self, mock_facade, mock_api_url) -> None:
        mock_api_url.return_value = "https://us.posthog.com/"
        mock_facade.return_value = [self._make_installation()]

        configs = get_user_mcp_server_configs(self.TOKEN, self.TEAM_ID, self.USER_ID)

        assert configs[0].url.startswith("https://us.posthog.com/api/")

    @patch(MOCK_API_URL)
    @patch(MOCK_FACADE)
    def test_multiple_installations(self, mock_facade, mock_api_url) -> None:
        mock_api_url.return_value = self.API_BASE
        mock_facade.return_value = [
            self._make_installation(
                id="abc-1", name="Linear", proxy_path="/api/environments/42/mcp_server_installations/abc-1/proxy/"
            ),
            self._make_installation(
                id="abc-2", name="Notion", proxy_path="/api/environments/42/mcp_server_installations/abc-2/proxy/"
            ),
        ]

        configs = get_user_mcp_server_configs(self.TOKEN, self.TEAM_ID, self.USER_ID)

        assert len(configs) == 2
        assert configs[0].name == "Linear"
        assert configs[1].name == "Notion"


class TestGetGitIdentityEnvVars(TestCase):
    @staticmethod
    def _make_task(origin_product: str, user: object | None = None) -> MagicMock:
        task = MagicMock(spec=Task)
        task.origin_product = origin_product
        task.created_by = user
        return task

    @staticmethod
    def _make_user(*, first_name: str = "Jane", last_name: str = "Doe", email: str = "jane@example.com") -> MagicMock:
        user = MagicMock()
        user.first_name = first_name
        user.last_name = last_name
        user.email = email
        user.get_full_name.return_value = f"{first_name} {last_name}".strip()
        return user

    def test_user_created_task_returns_user_identity(self) -> None:
        user = self._make_user(first_name="Jane", last_name="Doe", email="jane@example.com")
        task = self._make_task(Task.OriginProduct.USER_CREATED, user=user)
        result = get_git_identity_env_vars(task)
        assert result == {
            "GIT_AUTHOR_NAME": "Jane Doe",
            "GIT_AUTHOR_EMAIL": "jane@example.com",
            "GIT_COMMITTER_NAME": "Jane Doe",
            "GIT_COMMITTER_EMAIL": "jane@example.com",
        }

    def test_user_created_with_explicit_bot_mode_returns_empty(self) -> None:
        user = self._make_user()
        task = self._make_task(Task.OriginProduct.USER_CREATED, user=user)
        assert get_git_identity_env_vars(task, {"pr_authorship_mode": "bot"}) == {}

    def test_non_user_created_with_explicit_user_mode_returns_user_identity(self) -> None:
        user = self._make_user(first_name="June", last_name="Bug", email="june@example.com")
        task = self._make_task(Task.OriginProduct.ERROR_TRACKING, user=user)
        result = get_git_identity_env_vars(task, {"pr_authorship_mode": "user"})
        assert result == {
            "GIT_AUTHOR_NAME": "June Bug",
            "GIT_AUTHOR_EMAIL": "june@example.com",
            "GIT_COMMITTER_NAME": "June Bug",
            "GIT_COMMITTER_EMAIL": "june@example.com",
        }

    @parameterized.expand(
        [
            (Task.OriginProduct.SLACK,),
            (Task.OriginProduct.ERROR_TRACKING,),
            (Task.OriginProduct.SUPPORT_QUEUE,),
            (Task.OriginProduct.EVAL_CLUSTERS,),
            (Task.OriginProduct.SESSION_SUMMARIES,),
        ]
    )
    def test_non_user_created_returns_empty(self, origin_product: str) -> None:
        user = self._make_user()
        task = self._make_task(origin_product, user=user)
        assert get_git_identity_env_vars(task) == {}

    def test_user_created_without_user_returns_empty(self) -> None:
        task = self._make_task(Task.OriginProduct.USER_CREATED, user=None)
        assert get_git_identity_env_vars(task) == {}

    def test_first_name_only_fallback(self) -> None:
        user = self._make_user(first_name="Jane", last_name="", email="jane@example.com")
        task = self._make_task(Task.OriginProduct.USER_CREATED, user=user)
        result = get_git_identity_env_vars(task)
        assert result["GIT_AUTHOR_NAME"] == "Jane"

    def test_empty_name_falls_back_to_posthog_user(self) -> None:
        user = self._make_user(first_name="", last_name="", email="anon@example.com")
        user.get_full_name.return_value = ""
        task = self._make_task(Task.OriginProduct.USER_CREATED, user=user)
        result = get_git_identity_env_vars(task)
        assert result["GIT_AUTHOR_NAME"] == "PostHog User"
        assert result["GIT_AUTHOR_EMAIL"] == "anon@example.com"


class TestGetSandboxGitHubToken(TestCase):
    @patch("products.tasks.backend.temporal.process_task.utils.get_github_token")
    @patch("products.tasks.backend.temporal.process_task.utils.get_cached_github_user_token")
    def test_user_authorship_uses_cached_user_token(self, mock_cached_token, mock_get_github_token) -> None:
        mock_cached_token.return_value = "ghu_user"

        result = get_sandbox_github_token(123, run_id="run-1", state={"pr_authorship_mode": "user"})

        assert result == "ghu_user"
        mock_cached_token.assert_called_once_with("run-1")
        mock_get_github_token.assert_not_called()

    @patch("products.tasks.backend.temporal.process_task.utils.get_cached_github_user_token")
    def test_user_authorship_requires_cached_user_token(self, mock_cached_token) -> None:
        mock_cached_token.return_value = None

        with self.assertRaises(ValueError):
            get_sandbox_github_token(123, run_id="run-1", state={"pr_authorship_mode": "user"})

    @patch("products.tasks.backend.temporal.process_task.utils.get_github_token")
    def test_bot_authorship_uses_installation_token(self, mock_get_github_token) -> None:
        mock_get_github_token.return_value = "ghs_bot"

        result = get_sandbox_github_token(123, run_id="run-1", state={"pr_authorship_mode": "bot"})

        assert result == "ghs_bot"
        mock_get_github_token.assert_called_once_with(123)

    @patch("products.tasks.backend.temporal.process_task.utils.get_github_token")
    def test_no_state_falls_through_to_installation_token(self, mock_get_github_token) -> None:
        mock_get_github_token.return_value = "ghs_default"

        result = get_sandbox_github_token(123, run_id="run-1", state=None)

        assert result == "ghs_default"
        mock_get_github_token.assert_called_once_with(123)

    @patch("products.tasks.backend.temporal.process_task.utils.get_github_token")
    def test_empty_state_falls_through_to_installation_token(self, mock_get_github_token) -> None:
        mock_get_github_token.return_value = "ghs_default"

        result = get_sandbox_github_token(123, run_id="run-1", state={})

        assert result == "ghs_default"
        mock_get_github_token.assert_called_once_with(123)

    def test_no_integration_id_returns_none(self) -> None:
        result = get_sandbox_github_token(None, run_id="run-1", state={"pr_authorship_mode": "bot"})

        assert result is None
