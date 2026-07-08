from unittest.mock import MagicMock, patch

from django.test import TestCase

from parameterized import parameterized

from products.mcp_store.backend.facade.contracts import ActiveInstallationInfo
from products.tasks.backend.constants import (
    DEFAULT_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATH,
    DEFAULT_SANDBOX_WORKING_DIR,
    SNAPSHOT_KIND_DIRECTORY,
)
from products.tasks.backend.models import Task
from products.tasks.backend.temporal.process_task.utils import (
    GitHubCredentialSource,
    McpServerConfig,
    RunState,
    get_git_identity_env_vars,
    get_github_credential_source,
    get_sandbox_github_token,
    get_sandbox_ph_mcp_configs,
    get_user_mcp_server_configs,
    is_caller_token_run,
)


class TestRunStateSnapshotPaths(TestCase):
    @parameterized.expand(
        [
            (
                "new_directory_snapshot",
                {"snapshot_kind": SNAPSHOT_KIND_DIRECTORY},
                DEFAULT_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATH,
            ),
            (
                "stored_directory_snapshot_path",
                {"snapshot_kind": SNAPSHOT_KIND_DIRECTORY, "snapshot_mount_path": DEFAULT_SANDBOX_WORKING_DIR},
                DEFAULT_SANDBOX_WORKING_DIR,
            ),
            # A disallowed stored path invalidates the snapshot (None) — it must NOT be remapped
            # to the default: the snapshot's content layout only fits the path it was captured
            # from. "/tmp" is the legacy default whose re-mount killed the sandbox.
            (
                "legacy_tmp_directory_snapshot",
                {"snapshot_kind": SNAPSHOT_KIND_DIRECTORY, "snapshot_mount_path": "/tmp"},
                None,
            ),
            (
                "unsupported_directory_snapshot_path",
                {"snapshot_kind": SNAPSHOT_KIND_DIRECTORY, "snapshot_mount_path": "/tmp/agent-env"},
                None,
            ),
            ("filesystem_snapshot", {"snapshot_kind": "filesystem"}, None),
        ]
    )
    def test_resume_snapshot_mount_path(self, _name: str, state: dict[str, str], expected_path: str | None) -> None:
        assert RunState.model_validate(state).resume_snapshot_mount_path() == expected_path

    @parameterized.expand(
        [
            (
                "directory_workspace_path",
                {"snapshot_kind": SNAPSHOT_KIND_DIRECTORY, "snapshot_mount_path": DEFAULT_SANDBOX_WORKING_DIR},
                True,
            ),
            ("directory_no_path", {"snapshot_kind": SNAPSHOT_KIND_DIRECTORY}, True),
            (
                "directory_legacy_tmp_path",
                {"snapshot_kind": SNAPSHOT_KIND_DIRECTORY, "snapshot_mount_path": "/tmp"},
                False,
            ),
            ("filesystem", {"snapshot_kind": "filesystem"}, True),
            ("no_kind", {}, True),
        ]
    )
    def test_resume_snapshot_is_usable(self, _name: str, state: dict[str, str], expected: bool) -> None:
        assert RunState.model_validate(state).resume_snapshot_is_usable() is expected

    @parameterized.expand(
        [
            (
                "directory_full_triple",
                {
                    "snapshot_external_id": "im-dir",
                    "snapshot_kind": SNAPSHOT_KIND_DIRECTORY,
                    "snapshot_mount_path": DEFAULT_SANDBOX_WORKING_DIR,
                },
                {
                    "snapshot_external_id": "im-dir",
                    "snapshot_kind": SNAPSHOT_KIND_DIRECTORY,
                    "snapshot_mount_path": DEFAULT_SANDBOX_WORKING_DIR,
                },
            ),
            (
                "filesystem_no_mount_path",
                {"snapshot_external_id": "im-fs", "snapshot_kind": "filesystem"},
                {"snapshot_external_id": "im-fs", "snapshot_kind": "filesystem"},
            ),
            (
                "legacy_no_kind",
                {"snapshot_external_id": "im-old"},
                {"snapshot_external_id": "im-old", "snapshot_kind": "filesystem"},
            ),
            (
                "unusable_directory",
                {
                    "snapshot_external_id": "im-dir",
                    "snapshot_kind": SNAPSHOT_KIND_DIRECTORY,
                    "snapshot_mount_path": "/tmp",
                },
                {},
            ),
            ("no_snapshot", {}, {}),
        ]
    )
    def test_resume_snapshot_carry_state(self, _name: str, state: dict[str, str], expected: dict[str, str]) -> None:
        assert RunState.model_validate(state).resume_snapshot_carry_state() == expected


class TestGetSandboxMcpConfigs(TestCase):
    TOKEN = "phx_test_token"
    PROJECT_ID = 42

    def _expected_headers(self, *, read_only: bool = True, consumer: str = "posthog-code") -> list[dict[str, str]]:
        return [
            {"name": "Authorization", "value": f"Bearer {self.TOKEN}"},
            {"name": "x-posthog-project-id", "value": str(self.PROJECT_ID)},
            {"name": "x-posthog-mcp-version", "value": "2"},
            {"name": "x-posthog-read-only", "value": str(read_only).lower()},
            {"name": "x-posthog-mcp-consumer", "value": consumer},
        ]

    @parameterized.expand(
        [
            ("https://app.posthog.com", "https://mcp.posthog.com/mcp"),
            ("https://us.posthog.com", "https://mcp.posthog.com/mcp"),
            ("https://eu.posthog.com", "https://mcp-eu.posthog.com/mcp"),
            ("https://app.dev.posthog.dev", "https://mcp.dev.posthog.dev/mcp"),
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
        [("https://custom.example.com",)],
    )
    def test_returns_empty_list_for_unknown_hosts(self, site_url: str) -> None:
        with patch("products.tasks.backend.temporal.process_task.utils.settings") as mock_settings:
            mock_settings.SANDBOX_MCP_URL = None
            mock_settings.SITE_URL = site_url
            assert get_sandbox_ph_mcp_configs(self.TOKEN, self.PROJECT_ID) == []

    @parameterized.expand(
        [
            ("http://localhost:8000",),
            ("http://127.0.0.1:8001",),
        ]
    )
    def test_localhost_site_url_uses_host_docker_internal_mcp(self, site_url: str) -> None:
        with patch("products.tasks.backend.temporal.process_task.utils.settings") as mock_settings:
            mock_settings.SANDBOX_MCP_URL = None
            mock_settings.SITE_URL = site_url
            configs = get_sandbox_ph_mcp_configs(self.TOKEN, self.PROJECT_ID)
            assert configs == [
                McpServerConfig(
                    type="http",
                    name="posthog",
                    url="http://host.docker.internal:8787/mcp",
                    headers=self._expected_headers(),
                )
            ]

    def test_returns_empty_list_when_no_site_url(self) -> None:
        with patch("products.tasks.backend.temporal.process_task.utils.settings") as mock_settings:
            mock_settings.SANDBOX_MCP_URL = None
            mock_settings.SITE_URL = ""
            assert get_sandbox_ph_mcp_configs(self.TOKEN, self.PROJECT_ID) == []

    def test_task_id_adds_attribution_header(self) -> None:
        with patch("products.tasks.backend.temporal.process_task.utils.settings") as mock_settings:
            mock_settings.SANDBOX_MCP_URL = None
            mock_settings.SITE_URL = "https://app.posthog.com"
            configs = get_sandbox_ph_mcp_configs(self.TOKEN, self.PROJECT_ID, task_id="task-uuid-123")
            assert configs[0].headers == [
                *self._expected_headers(),
                {"name": "X-PostHog-Task-Id", "value": "task-uuid-123"},
            ]

    def test_no_task_id_omits_attribution_header(self) -> None:
        with patch("products.tasks.backend.temporal.process_task.utils.settings") as mock_settings:
            mock_settings.SANDBOX_MCP_URL = None
            mock_settings.SITE_URL = "https://app.posthog.com"
            configs = get_sandbox_ph_mcp_configs(self.TOKEN, self.PROJECT_ID)
            assert all(h["name"] != "X-PostHog-Task-Id" for h in configs[0].headers)

    @parameterized.expand(
        [
            (None, "posthog-code"),
            ("", "posthog-code"),
            ("posthog-code", "posthog-code"),
            ("some-other-origin", "posthog-code"),
            ("slack", "slack"),
            ("posthog_ai", "posthog_ai"),
        ]
    )
    def test_consumer_header_reflects_interaction_origin(
        self, interaction_origin: str | None, expected_consumer: str
    ) -> None:
        with patch("products.tasks.backend.temporal.process_task.utils.settings") as mock_settings:
            mock_settings.SANDBOX_MCP_URL = None
            mock_settings.SITE_URL = "https://app.posthog.com"
            configs = get_sandbox_ph_mcp_configs(self.TOKEN, self.PROJECT_ID, interaction_origin=interaction_origin)
            assert configs == [
                McpServerConfig(
                    type="http",
                    name="posthog",
                    url="https://mcp.posthog.com/mcp",
                    headers=self._expected_headers(consumer=expected_consumer),
                )
            ]


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

    def _expected_user_headers(self, *, consumer: str = "posthog-code") -> list[dict[str, str]]:
        return [
            {"name": "Authorization", "value": f"Bearer {self.TOKEN}"},
            {"name": "x-posthog-mcp-consumer", "value": consumer},
        ]

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
                headers=self._expected_user_headers(),
            )
        ]

    @parameterized.expand(
        [
            ("slack", "slack"),
            ("posthog_ai", "posthog_ai"),
            ("posthog_code", "posthog-code"),
            (None, "posthog-code"),
        ]
    )
    @patch(MOCK_API_URL)
    @patch(MOCK_FACADE)
    def test_consumer_header_reflects_interaction_origin(
        self, interaction_origin: str | None, expected_consumer: str, mock_facade, mock_api_url
    ) -> None:
        mock_api_url.return_value = self.API_BASE
        mock_facade.return_value = [self._make_installation()]

        configs = get_user_mcp_server_configs(
            self.TOKEN, self.TEAM_ID, self.USER_ID, interaction_origin=interaction_origin
        )

        assert configs[0].headers == self._expected_user_headers(consumer=expected_consumer)

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
            (Task.OriginProduct.ERROR_TRACKING,),
            (Task.OriginProduct.SUPPORT_QUEUE,),
            (Task.OriginProduct.HOGDESK,),
            (Task.OriginProduct.EVAL_CLUSTERS,),
            (Task.OriginProduct.SESSION_SUMMARIES,),
        ]
    )
    def test_non_user_created_returns_empty(self, origin_product: str) -> None:
        user = self._make_user()
        task = self._make_task(origin_product, user=user)
        assert get_git_identity_env_vars(task) == {}

    def test_slack_task_returns_user_identity(self) -> None:
        user = self._make_user(first_name="Slack", last_name="User", email="slack@example.com")
        task = self._make_task(Task.OriginProduct.SLACK, user=user)
        result = get_git_identity_env_vars(task)
        assert result == {
            "GIT_AUTHOR_NAME": "Slack User",
            "GIT_AUTHOR_EMAIL": "slack@example.com",
            "GIT_COMMITTER_NAME": "Slack User",
            "GIT_COMMITTER_EMAIL": "slack@example.com",
        }

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


class TestGetGithubToken(TestCase):
    def test_raises_credential_unavailable_for_dead_installation_instead_of_stale_token(self):
        from posthog.models import Integration, Organization, Team

        from products.tasks.backend.exceptions import CredentialUnavailableError
        from products.tasks.backend.temporal.process_task.utils import get_github_token

        org = Organization.objects.create(name="o")
        team = Team.objects.create(organization=org, name="t")
        integration = Integration.objects.create(
            team=team,
            kind="github",
            config={"installation_id": "INSTALL", "installation_unavailable_since": 1700000000},
            sensitive_config={"access_token": "ghs_stale"},
        )

        with self.assertRaises(CredentialUnavailableError):
            get_github_token(integration.id)


class TestGetSandboxGitHubToken(TestCase):
    @parameterized.expand(
        [
            ("cached_token_wins", "ghu_cached", True, "ghu_user", None, "ghu_cached"),
            ("identity_token", None, True, "ghu_user", None, "ghu_user"),
            ("missing_identity_falls_back_to_team_token", None, False, None, "missing", "ghs_team"),
            ("identity_reauthorization_falls_back_to_team_token", None, True, None, "reauthorization", "ghs_team"),
            ("identity_without_token_falls_back_to_team_token", None, True, None, "empty_token", "ghs_team"),
        ]
    )
    @patch("products.tasks.backend.temporal.process_task.sandbox_credentials.resolve_coordinated_user_token")
    @patch("products.tasks.backend.temporal.process_task.utils.get_cached_github_user_token")
    @patch("products.tasks.backend.temporal.process_task.utils.get_user_github_integration")
    @patch("products.tasks.backend.temporal.process_task.utils.get_github_token")
    def test_user_authorship_token_resolution(
        self,
        _case_name: str,
        cached_token: str | None,
        has_identity: bool,
        identity_token: str | None,
        error_case: str | None,
        expected_token: str | None,
        mock_get_github_token: MagicMock,
        mock_get_identity: MagicMock,
        mock_cached: MagicMock,
        mock_resolve: MagicMock,
    ) -> None:
        from posthog.models.user_integration import ReauthorizationRequired

        mock_cached.return_value = cached_token
        creator = MagicMock(name="creator")
        identity = MagicMock()
        if error_case == "reauthorization":
            mock_resolve.side_effect = ReauthorizationRequired("reauthorize GitHub")
        else:
            mock_resolve.return_value = identity_token
        mock_get_identity.return_value = identity if has_identity else None

        mock_get_github_token.return_value = expected_token
        result = get_sandbox_github_token(
            123,
            run_id="run-1",
            state={"pr_authorship_mode": "user"},
            created_by=creator,
        )
        assert result == expected_token

        mock_cached.assert_called_once_with("run-1")
        if cached_token:
            mock_get_identity.assert_not_called()
            mock_resolve.assert_not_called()
        else:
            mock_get_identity.assert_called_once_with(
                creator,
                github_user_integration_id=None,
                repository=None,
                allow_refresh=True,
            )
            if has_identity:
                mock_resolve.assert_called_once_with(identity)
        if error_case in ("missing", "reauthorization", "empty_token"):
            mock_get_github_token.assert_called_once_with(123)
        else:
            mock_get_github_token.assert_not_called()

    @parameterized.expand(
        [
            ("reauthorization",),
            ("empty_token",),
        ]
    )
    @patch("products.tasks.backend.temporal.process_task.sandbox_credentials.resolve_coordinated_user_token")
    @patch("products.tasks.backend.temporal.process_task.utils.get_cached_github_user_token")
    @patch("products.tasks.backend.temporal.process_task.utils.get_user_github_integration")
    def test_user_authorship_requires_reauthorization_without_team_fallback(
        self,
        error_case: str,
        mock_get_identity: MagicMock,
        mock_cached: MagicMock,
        mock_resolve: MagicMock,
    ) -> None:
        from posthog.models.user_integration import ReauthorizationRequired

        mock_cached.return_value = None
        mock_get_identity.return_value = MagicMock()
        if error_case == "reauthorization":
            mock_resolve.side_effect = ReauthorizationRequired("reauthorize GitHub")
        else:
            mock_resolve.return_value = None

        with self.assertRaises(ReauthorizationRequired):
            get_sandbox_github_token(
                None,
                run_id="run-1",
                state={"pr_authorship_mode": "user"},
                created_by=MagicMock(name="creator"),
            )

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

    @patch("products.tasks.backend.temporal.process_task.utils.get_github_token")
    @patch("products.tasks.backend.temporal.process_task.utils.get_user_github_integration")
    @patch("products.tasks.backend.temporal.process_task.utils.get_cached_github_user_token")
    def test_caller_token_run_never_substitutes_server_integration(
        self, mock_cached: MagicMock, mock_get_identity: MagicMock, mock_get_github_token: MagicMock
    ) -> None:
        mock_cached.return_value = None  # caller-supplied token has expired from the cache

        result = get_sandbox_github_token(
            123,
            run_id="run-1",
            state={"pr_authorship_mode": "user", "github_credential_source": "caller_token"},
            created_by=MagicMock(name="creator"),
        )

        assert result is None
        mock_get_identity.assert_not_called()
        mock_get_github_token.assert_not_called()


class TestGitHubCredentialSourceHelpers(TestCase):
    def test_get_github_credential_source_reads_marker(self) -> None:
        assert (
            get_github_credential_source({"github_credential_source": "caller_token"})
            == GitHubCredentialSource.CALLER_TOKEN
        )
        assert (
            get_github_credential_source({"github_credential_source": "server_integration"})
            == GitHubCredentialSource.SERVER_INTEGRATION
        )
        assert get_github_credential_source({}) is None
        assert get_github_credential_source(None) is None

    def test_marker_is_authoritative_over_cache(self) -> None:
        with patch("products.tasks.backend.temporal.process_task.utils.get_cached_github_user_token") as mock_cached:
            assert is_caller_token_run("run-1", {"github_credential_source": "caller_token"}) is True
            assert is_caller_token_run("run-1", {"github_credential_source": "server_integration"}) is False
            # Marker decides regardless of cache state — never falls through.
            mock_cached.assert_not_called()

    @parameterized.expand([("ghu_caller", True), (None, False)])
    def test_unmarked_run_falls_back_to_cache(self, cached: str | None, expected: bool) -> None:
        with patch(
            "products.tasks.backend.temporal.process_task.utils.get_cached_github_user_token", return_value=cached
        ):
            assert is_caller_token_run("run-1", {}) is expected

    def test_bot_authorship_falls_back_to_user_install_token_when_team_integration_missing(self) -> None:
        from posthog.models import Organization, Team
        from posthog.models.user import User
        from posthog.models.user_integration import UserIntegration

        organization = Organization.objects.create(name="bot-fallback-org")
        Team.objects.create(organization=organization, name="bot-fallback-team")
        user = User.objects.create(email="bot-fallback@test.com")
        user_integration = UserIntegration.objects.create(
            user=user,
            kind=UserIntegration.IntegrationKind.GITHUB,
            integration_id="install-1",
            config={},
            sensitive_config={"access_token": "ghs_user_install"},
        )

        result = get_sandbox_github_token(
            None,
            run_id="run-1",
            state={"pr_authorship_mode": "bot"},
            github_user_integration_id=str(user_integration.id),
        )

        assert result == "ghs_user_install"

    def test_bot_authorship_prefers_team_integration_over_user_install_token(self) -> None:
        from posthog.models import Integration, Organization, Team
        from posthog.models.user import User
        from posthog.models.user_integration import UserIntegration

        organization = Organization.objects.create(name="bot-precedence-org")
        team = Team.objects.create(organization=organization, name="bot-precedence-team")
        team_integration = Integration.objects.create(
            team=team,
            kind="github",
            integration_id="team-install",
            config={},
            sensitive_config={"access_token": "ghs_team"},
        )
        user = User.objects.create(email="bot-precedence@test.com")
        user_integration = UserIntegration.objects.create(
            user=user,
            kind=UserIntegration.IntegrationKind.GITHUB,
            integration_id="user-install",
            config={},
            sensitive_config={"access_token": "ghs_user_install"},
        )

        result = get_sandbox_github_token(
            team_integration.id,
            run_id="run-1",
            state={"pr_authorship_mode": "bot"},
            github_user_integration_id=str(user_integration.id),
        )

        assert result == "ghs_team"
