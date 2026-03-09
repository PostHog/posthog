from unittest.mock import patch

from django.test import TestCase

from parameterized import parameterized

from products.tasks.backend.temporal.process_task.utils import get_sandbox_mcp_configs


class TestGetSandboxMcpConfigs(TestCase):
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
            configs = get_sandbox_mcp_configs()
            assert configs == [{"type": "streamable-http", "url": expected_mcp_url}]

    def test_explicit_sandbox_mcp_url_takes_precedence(self) -> None:
        with patch("products.tasks.backend.temporal.process_task.utils.settings") as mock_settings:
            mock_settings.SANDBOX_MCP_URL = "https://custom-mcp.example.com/mcp"
            mock_settings.SITE_URL = "https://app.posthog.com"
            configs = get_sandbox_mcp_configs()
            assert configs == [{"type": "streamable-http", "url": "https://custom-mcp.example.com/mcp"}]

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
            assert get_sandbox_mcp_configs() == []

    def test_returns_empty_list_when_no_site_url(self) -> None:
        with patch("products.tasks.backend.temporal.process_task.utils.settings") as mock_settings:
            mock_settings.SANDBOX_MCP_URL = None
            mock_settings.SITE_URL = ""
            assert get_sandbox_mcp_configs() == []
