import time
from datetime import UTC, datetime

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.schema import CachedTeamTaxonomyQueryResponse

from posthog.event_usage import EventSource
from posthog.ingress.verify.schemes import hmac_sha256_signature
from posthog.models import Organization, Team

from products.posthog_ai.backend.api.mcp_tools import PublicDocsSearchBurstThrottle

from ee.hogai.mcp_tool import MCPToolResult


class TestMCPToolsAPI(APIBaseTest):
    def test_unauthenticated_request(self):
        self.client.logout()
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_tools/execute_sql/",
            {"args": {"query": "SELECT 1"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_cannot_access_other_organization_team(self):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        response = self.client.post(
            f"/api/environments/{other_team.id}/mcp_tools/execute_sql/",
            {"args": {"query": "SELECT 1"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_invoke_tool_not_found(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_tools/nonexistent_tool/",
            {"args": {}},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("not found", data["content"])

    def test_invoke_execute_sql_with_invalid_args(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_tools/execute_sql/",
            {"args": {}},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("validation error", data["content"].lower())

    @parameterized.expand([("text_only", False), ("structured_query", True)])
    @patch("ee.hogai.tools.execute_sql.mcp_tool.ExecuteSQLMCPTool.execute", new_callable=AsyncMock)
    def test_invoke_execute_sql_success(self, _name: str, structured: bool, mock_execute: AsyncMock) -> None:
        content = "event | cnt\ntest_event | 5"
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT {variables.org}",
            "variables": {"example-variable": {"variableId": "example-variable", "code_name": "org"}},
        }
        mock_execute.return_value = (
            MCPToolResult(content=content, structured_content={"query": query}) if structured else content
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_tools/execute_sql/",
            {"args": {"query": "SELECT event, count() as cnt FROM events GROUP BY event"}},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["content"], content)
        if structured:
            self.assertEqual(data["structured_content"], {"query": query})
        else:
            self.assertNotIn("structured_content", data)
        mock_execute.assert_called_once()

    @patch("ee.hogai.utils.helpers.TeamTaxonomyQueryRunner")
    def test_invoke_read_taxonomy_attributes_query_executed_to_user_and_mcp_source(self, mock_runner_cls):
        now = datetime(2026, 1, 1, tzinfo=UTC)
        mock_runner_cls.return_value.run.return_value = CachedTeamTaxonomyQueryResponse(
            cache_key="cache_key",
            is_cached=True,
            last_refresh=now,
            next_allowed_client_refresh=now,
            results=[],
            timezone="UTC",
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_tools/read_taxonomy/",
            {"args": {"query": {"kind": "events"}}},
            format="json",
            headers={"X-PostHog-Client": "mcp"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        run_kwargs = mock_runner_cls.return_value.run.call_args.kwargs
        self.assertEqual(run_kwargs["user"], self.user)
        self.assertEqual(run_kwargs["analytics_props"], {"source": EventSource.MCP})

    @patch("ee.hogai.tools.execute_sql.mcp_tool.ExecuteSQLMCPTool.execute", new_callable=AsyncMock)
    def test_invoke_tool_error_returns_error_response(self, mock_execute):
        from ee.hogai.tool_errors import MaxToolRetryableError

        mock_execute.side_effect = MaxToolRetryableError("Query validation failed: syntax error")

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_tools/execute_sql/",
            {"args": {"query": "BAD QUERY"}},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("Tool failed", data["content"])

    @patch("ee.hogai.tools.execute_sql.mcp_tool.ExecuteSQLMCPTool.execute", new_callable=AsyncMock)
    def test_invoke_tool_unexpected_error_returns_internal_error(self, mock_execute):
        mock_execute.side_effect = RuntimeError("unexpected")

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_tools/execute_sql/",
            {"args": {"query": "SELECT 1"}},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("internal error", data["content"].lower())


class TestDocsSearchAction(APIBaseTest):
    URL: str

    def setUp(self):
        super().setUp()
        self.URL = f"/api/environments/{self.team.id}/mcp_tools/docs_search/"

    def test_unauthenticated_request(self):
        self.client.logout()
        response = self.client.post(self.URL, {"query": "feature flags"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_query_field_returns_validation_error(self):
        response = self.client.post(self.URL, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("products.posthog_ai.backend.api.mcp_tools._run_inkeep_docs_search", new_callable=AsyncMock)
    def test_docs_search_returns_formatted_content(self, mock_run):
        mock_run.return_value = "Found 1 relevant documentation page(s):\n\n# Feature Flags\nURL: …\n\nDocs."

        with override_settings(INKEEP_API_KEY="test-key"):
            response = self.client.post(self.URL, {"query": "feature flags"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertIn("Feature Flags", body["content"])
        self.assertNotIn("<system_reminder>", body["content"])
        mock_run.assert_called_once()

    def test_docs_search_unavailable_when_key_missing(self):
        with override_settings(INKEEP_API_KEY=""):
            response = self.client.post(self.URL, {"query": "feature flags"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    @patch("products.posthog_ai.backend.api.mcp_tools._run_inkeep_docs_search", new_callable=AsyncMock)
    def test_docs_search_unexpected_error_returns_500(self, mock_run):
        mock_run.side_effect = RuntimeError("boom")

        with override_settings(INKEEP_API_KEY="test-key"):
            response = self.client.post(self.URL, {"query": "feature flags"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("internal error", response.json()["content"].lower())


MCP_CLIENT_IP_KEY = "mcp-client-ip-test-key"


def _signed_mcp_client_ip_headers(ip: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    return {
        "HTTP_X_POSTHOG_MCP_CLIENT_IP": ip,
        "HTTP_X_POSTHOG_MCP_CLIENT_IP_TIMESTAMP": timestamp,
        "HTTP_X_POSTHOG_MCP_CLIENT_IP_SIGNATURE": hmac_sha256_signature(
            MCP_CLIENT_IP_KEY, f"{ip}:{timestamp}".encode()
        ),
    }


@override_settings(INKEEP_API_KEY="test-key", MCP_CLIENT_IP_SIGNING_KEYS=[MCP_CLIENT_IP_KEY])
@patch(
    "products.posthog_ai.backend.api.mcp_tools._run_inkeep_docs_search",
    new_callable=AsyncMock,
    return_value="# Feature Flags",
)
class TestPublicDocsSearch(SimpleTestCase):
    URL = "/api/public_docs_search/"

    def setUp(self):
        super().setUp()
        cache.clear()

    def test_searches_docs_without_authentication(self, mock_run):
        response = self.client.post(self.URL, {"query": "feature flags"}, content_type="application/json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"content": "# Feature Flags"})

    def test_missing_query_returns_validation_error(self, mock_run):
        response = self.client.post(self.URL, {}, content_type="application/json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_run.assert_not_called()

    @time_machine.travel(datetime(2026, 1, 1, tzinfo=UTC), tick=False)
    @patch.object(PublicDocsSearchBurstThrottle, "rate", "1/minute")
    def test_throttles_each_signed_mcp_client_ip_separately(self, mock_run):
        def search(ip: str) -> int:
            return self.client.post(
                self.URL,
                {"query": "feature flags"},
                content_type="application/json",
                REMOTE_ADDR="10.0.0.5",
                **_signed_mcp_client_ip_headers(ip),
            ).status_code

        self.assertEqual(search("203.0.113.10"), status.HTTP_200_OK)
        self.assertEqual(search("203.0.113.20"), status.HTTP_200_OK)
        self.assertEqual(search("203.0.113.10"), status.HTTP_429_TOO_MANY_REQUESTS)
