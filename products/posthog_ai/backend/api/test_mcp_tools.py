from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from clickhouse_driver.errors import NetworkError
from parameterized import parameterized
from rest_framework import status

from posthog.schema import CachedTeamTaxonomyQueryResponse

from posthog.event_usage import EventSource
from posthog.exceptions import ClickHouseQuerySizeExceeded
from posthog.models import Organization, Team

from ee.hogai.mcp_tool import MCPToolResult
from ee.hogai.tool_errors import MaxToolAccessDeniedError, MaxToolRetryableError, MaxToolTransientError


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

    @parameterized.expand([("empty", ""), ("syntax", "SELECT (")])
    def test_sql_validation_preserves_the_error_contract(self, _name: str, query: str) -> None:
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_tools/execute_sql/", {"args": {"query": query}}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["success"])
        self.assertEqual(
            response.json()["error"],
            {"type": "validation", "code": "invalid_input", "retry_strategy": "adjusted"},
        )

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

    def test_async_sql_polling_timeout_preserves_adjusted_recovery(self) -> None:
        query_status = {"id": "test-query-id", "complete": False}
        with (
            patch(
                "ee.hogai.context.insight.query_executor.process_query_dict",
                return_value={"query_status": query_status},
            ),
            patch("ee.hogai.context.insight.query_executor.get_query_status") as mock_status,
            patch("ee.hogai.context.insight.query_executor.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_status.return_value.model_dump.return_value = query_status
            response = self.client.post(
                f"/api/environments/{self.team.id}/mcp_tools/execute_sql/",
                {"args": {"query": "SELECT 1"}},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "content": "Tool failed: MaxToolRetryableError: Error executing query: Query hasn't completed in time."
                " It's worth trying again, maybe with a shorter time range.. You may retry with adjusted inputs.",
                "error": {"type": "timeout", "code": "query_timeout", "retry_strategy": "adjusted"},
            },
        )

    @parameterized.expand(
        [
            (
                MaxToolRetryableError("Invalid query with private input"),
                "validation",
                "invalid_input",
                "adjusted",
                "Tool failed: MaxToolRetryableError: Error executing query: Invalid query with private input."
                " You may retry with adjusted inputs.",
            ),
            (
                MaxToolTransientError("Temporarily unavailable"),
                "api_5xx",
                "service_unavailable",
                "once",
                "Tool failed: MaxToolRetryableError: Error executing query: Temporarily unavailable."
                " You may retry this operation once without changes.",
            ),
            (
                MaxToolAccessDeniedError("insight", "viewer"),
                "permission",
                "permission_denied",
                "never",
                "Tool failed: MaxToolRetryableError: Error executing query: The user does not have viewer access"
                " to access insights. Suggest the user to contact their project admin to request access.."
                " Do not automatically retry this tool call.",
            ),
            (
                ClickHouseQuerySizeExceeded(),
                "api_5xx",
                "query_limit_exceeded",
                "adjusted",
                "Tool failed: MaxToolRetryableError: Error executing query: Query size exceeded.."
                " You may retry with adjusted inputs.",
            ),
        ]
    )
    @patch("ee.hogai.tools.execute_sql.mcp_tool.ExecuteSQLMCPTool.execute", new_callable=AsyncMock)
    def test_invoke_tool_error_returns_error_response(
        self,
        cause: Exception,
        error_type: str,
        code: str,
        retry_strategy: str,
        expected_content: str,
        mock_execute: AsyncMock,
    ) -> None:
        async def execute_with_wrapped_error(_args):
            try:
                raise cause
            except Exception as error:
                raise MaxToolRetryableError(f"Error executing query: {error}") from error

        mock_execute.side_effect = execute_with_wrapped_error

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_tools/execute_sql/",
            {"args": {"query": "BAD QUERY"}},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "content": expected_content,
                "error": {"type": error_type, "code": code, "retry_strategy": retry_strategy},
            },
        )

    @parameterized.expand(
        [
            (
                RuntimeError("private internal details"),
                "internal",
                "internal_error",
                "never",
                "The tool raised an internal error. Do not automatically retry this tool call.",
            ),
            (
                NetworkError("private database host"),
                "api_5xx",
                "service_unavailable",
                "once",
                "The tool raised an internal error. You may retry this operation once without changes.",
            ),
            (
                ClickHouseQuerySizeExceeded("private query"),
                "api_5xx",
                "query_limit_exceeded",
                "adjusted",
                "The tool raised an internal error. You may retry with adjusted inputs.",
            ),
        ]
    )
    @patch("ee.hogai.tools.execute_sql.mcp_tool.ExecuteSQLMCPTool.execute", new_callable=AsyncMock)
    def test_invoke_tool_unwrapped_error_preserves_recovery_without_exposing_details(
        self,
        cause: Exception,
        error_type: str,
        code: str,
        retry_strategy: str,
        expected_content: str,
        mock_execute: AsyncMock,
    ) -> None:
        mock_execute.side_effect = cause

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_tools/execute_sql/",
            {"args": {"query": "SELECT 1"}},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "content": expected_content,
                "error": {"type": error_type, "code": code, "retry_strategy": retry_strategy},
            },
        )


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
        from django.test import override_settings

        mock_run.return_value = "Found 1 relevant documentation page(s):\n\n# Feature Flags\nURL: …\n\nDocs."

        with override_settings(INKEEP_API_KEY="test-key"):
            response = self.client.post(self.URL, {"query": "feature flags"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertIn("Feature Flags", body["content"])
        self.assertNotIn("<system_reminder>", body["content"])
        mock_run.assert_called_once()

    def test_docs_search_unavailable_when_key_missing(self):
        from django.test import override_settings

        with override_settings(INKEEP_API_KEY=""):
            response = self.client.post(self.URL, {"query": "feature flags"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    @patch("products.posthog_ai.backend.api.mcp_tools._run_inkeep_docs_search", new_callable=AsyncMock)
    def test_docs_search_unexpected_error_returns_500(self, mock_run):
        from django.test import override_settings

        mock_run.side_effect = RuntimeError("boom")

        with override_settings(INKEEP_API_KEY="test-key"):
            response = self.client.post(self.URL, {"query": "feature flags"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("internal error", response.json()["content"].lower())
