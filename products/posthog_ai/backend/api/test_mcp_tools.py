from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from clickhouse_driver.errors import NetworkError, SocketTimeoutError
from parameterized import parameterized
from rest_framework import status
from rest_framework.exceptions import APIException

from posthog.schema import CachedTeamTaxonomyQueryResponse

from posthog.event_usage import EventSource
from posthog.exceptions import (
    ClickHouseAtCapacity,
    ClickHouseClusterMemoryLimitExceeded,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.models import Organization, Team

from ee.hogai.mcp_tool import MCPToolResult
from ee.hogai.tool_errors import MaxToolAccessDeniedError, MaxToolRetryableError, MaxToolTransientError


class TestMCPToolsAPI(APIBaseTest):
    @parameterized.expand(
        [
            (tool_name, operation, args, error, outcome)
            for tool_name, operation, args in [
                ("execute_sql", "mcp_execute_sql", {"query": "SELECT 1"}),
                ("read_taxonomy", "mcp_read_data_schema", {"query": {"kind": "events"}}),
            ]
            for error, outcome in [
                (None, "success"),
                (MaxToolRetryableError("private invalid input"), "success"),
                (RuntimeError("private failure detail"), "failure"),
            ]
        ]
    )
    @patch("posthog.slo.events.posthoganalytics.capture")
    def test_query_tool_service_slo_records_paired_outcomes(
        self, tool_name: str, operation: str, args: dict, error: Exception | None, outcome: str, capture
    ) -> None:
        tool_class = (
            "ee.hogai.tools.execute_sql.mcp_tool.ExecuteSQLMCPTool"
            if tool_name == "execute_sql"
            else "ee.hogai.tools.read_taxonomy.mcp_tool.ReadTaxonomyMCPTool"
        )
        with patch(f"{tool_class}.execute", new_callable=AsyncMock, return_value="rows", side_effect=error):
            response = self.client.post(
                f"/api/environments/{self.team.id}/mcp_tools/{tool_name}/", {"args": args}, format="json"
            )

        self.assertEqual(response.status_code, 200)
        events = [call.kwargs for call in capture.call_args_list if call.kwargs.get("event", "").startswith("slo_")]
        self.assertEqual([event["event"] for event in events], ["slo_operation_started", "slo_operation_completed"])
        started, completed = [event["properties"] for event in events]
        self.assertEqual(started["correlation_id"], completed["correlation_id"])
        self.assertEqual(started["operation"], operation)
        self.assertEqual(completed["operation"], operation)
        self.assertEqual(completed["team_id"], self.team.id)
        self.assertEqual(completed["outcome"], outcome)
        self.assertEqual(completed["tool_success"], error is None)
        self.assertNotIn("private", str(events))
        self.assertNotIn("SELECT", str(events))

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

    @parameterized.expand(
        [
            (MaxToolRetryableError("Invalid query with private input"), "validation", "invalid_input", "adjusted"),
            (MaxToolTransientError("Temporarily unavailable"), "api_5xx", "service_unavailable", "once"),
            (MaxToolAccessDeniedError("insight", "viewer"), "permission", "permission_denied", "never"),
            (ClickHouseAtCapacity(), "rate_limited", "query_capacity_exceeded", "once"),
            (ClickHouseClusterMemoryLimitExceeded(), "rate_limited", "query_capacity_exceeded", "once"),
            (ClickHouseQueryTimeOut(), "timeout", "query_timeout", "adjusted"),
            (ClickHouseQueryMemoryLimitExceeded(), "api_5xx", "query_memory_limit_exceeded", "adjusted"),
            (SocketTimeoutError("private host"), "timeout", "query_timeout", "once"),
            (NetworkError("private host"), "api_5xx", "service_unavailable", "once"),
            (APIException("Serialized query failure"), "api_5xx", "service_unavailable", "never"),
            (RuntimeError("private query text"), "internal", "internal_error", "never"),
        ]
    )
    @patch("ee.hogai.tools.execute_sql.mcp_tool.ExecuteSQLMCPTool.execute", new_callable=AsyncMock)
    def test_invoke_tool_error_returns_error_response(
        self, cause: Exception, error_type: str, code: str, retry_strategy: str, mock_execute: AsyncMock
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
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("Tool failed", data["content"])
        self.assertEqual(data["error"], {"type": error_type, "code": code, "retry_strategy": retry_strategy})
        self.assertNotIn("private", str(data["error"]))
        if retry_strategy == "once":
            self.assertIn("retry this operation once without changes", data["content"])
            self.assertNotIn("retry with adjusted inputs", data["content"])
        elif retry_strategy == "never":
            self.assertNotIn("retry with adjusted inputs", data["content"])

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
        self.assertEqual(data["error"], {"type": "internal", "code": "internal_error", "retry_strategy": "never"})


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
