from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, Mock, patch

from django.db import OperationalError

from parameterized import param, parameterized
from psycopg.errors import QueryCanceled
from rest_framework import status
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from posthog.schema import CachedTeamTaxonomyQueryResponse

from posthog.hogql.errors import (
    ExposedHogQLError,
    NotImplementedError as HogQLNotImplementedError,
    QueryError,
    SyntaxError as HogQLSyntaxError,
    TableAccessDeniedError,
)

from posthog.errors import (
    CHQueryErrorCorruptedParquetMetadata,
    CHQueryErrorIllegalTypeOfArgument,
    CHQueryErrorQueryWasCancelled,
    CHQueryErrorS3Error,
    CHQueryErrorS3FileChangedDuringRead,
    InternalCHQueryError,
)
from posthog.event_usage import EventSource
from posthog.exceptions import (
    ClickHouseAtCapacity,
    ClickHouseClusterMemoryLimitExceeded,
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQuerySizeExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.models import Organization, Team

from products.access_control.backend.facade.user_access_control import UserAccessControlError

from ee.hogai.mcp_tool import MCPToolResult
from ee.hogai.tool_errors import MaxToolRetryableError


def _wrapped_hogql_error(cause: Exception, message: str) -> ExposedHogQLError:
    error = ExposedHogQLError(message)
    error.__cause__ = cause
    return error


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

    @parameterized.expand([("missing", "00000000-0000-4000-8000-000000000000"), ("malformed", "not-a-uuid")])
    def test_invoke_execute_sql_with_invalid_connection(self, _name: str, connection_id: str) -> None:
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_tools/execute_sql/",
            {"args": {"query": "SELECT 1", "connectionId": connection_id}},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "content": "Tool failed: MaxToolRetryableError: Invalid connectionId: no direct-query-capable data source with this id in this team, or you don't have access to it.. You may retry with adjusted inputs.",
                "error_type": "internal",
            },
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
            (
                "statement_timeout",
                None,
                "timeout",
                "Tool failed: MaxToolTransientError: Reading the taxonomy timed out. This can happen on large projects. You may retry this operation once without changes.",
            ),
            (
                "query_memory_limit",
                ClickHouseQueryMemoryLimitExceeded("private backend detail"),
                "memory_limit",
                "Tool failed: MaxToolFatalError: Reading the schema ran out of memory. This tool does not support date filters. Use execute-sql with a short, explicit date range for a targeted lookup.",
            ),
            (
                "cluster_memory_limit",
                ClickHouseClusterMemoryLimitExceeded("private backend detail"),
                "rate_limited",
                "Tool failed: MaxToolTransientError: We're under heavy load right now and couldn't finish this query. Please try again in a few minutes. You may retry this operation once without changes.",
            ),
            (
                "cancelled",
                CHQueryErrorQueryWasCancelled("private backend detail", code=394),
                None,
                "The tool raised an internal error. Do not immediately retry the tool call.",
            ),
            (
                "unknown",
                RuntimeError("private backend detail"),
                None,
                "The tool raised an internal error. Do not immediately retry the tool call.",
            ),
        ]
    )
    @patch("products.posthog_ai.backend.api.mcp_tools.capture_exception")
    @patch("ee.hogai.utils.helpers.TeamTaxonomyQueryRunner")
    def test_read_taxonomy_errors_preserve_recovery_advice(
        self,
        _name: str,
        error: Exception | None,
        error_type: str | None,
        content: str,
        mock_runner_cls: Mock,
        mock_capture: Mock,
    ) -> None:
        if error is None:
            error = OperationalError("canceling statement due to statement timeout")
            error.__cause__ = QueryCanceled()
        mock_runner_cls.return_value.run.side_effect = error

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_tools/read_taxonomy/",
            {"args": {"query": {"kind": "events"}}},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        expected = {"success": False, "content": content}
        if error_type is not None:
            expected["error_type"] = error_type
        else:
            self.assertEqual(mock_capture.call_args.args, (error,))
        self.assertEqual(response.json(), expected)
        mock_runner_cls.return_value.run.assert_called_once()

    @parameterized.expand(
        [
            ("without_code", None, {}),
            ("with_code", "unknown_identifier", {"error_code": "unknown_identifier"}),
        ]
    )
    @patch("ee.hogai.tools.execute_sql.mcp_tool.ExecuteSQLMCPTool.execute", new_callable=AsyncMock)
    def test_invoke_tool_error_returns_error_response(self, _name, error_code, expected_extra, mock_execute):
        mock_execute.side_effect = MaxToolRetryableError("Query validation failed: syntax error", error_code=error_code)

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
                "content": "Tool failed: MaxToolRetryableError: Query validation failed: syntax error. You may retry with adjusted inputs.",
                "error_type": "validation",
                **expected_extra,
            },
        )

    @parameterized.expand(
        [
            (
                ClickHouseAtCapacity("Query service is busy"),
                "rate_limited",
                "Tool failed: MaxToolTransientError: Query service is busy. You may retry this operation once without changes.",
            ),
            (
                ClickHouseClusterMemoryLimitExceeded("Cluster memory is full"),
                "rate_limited",
                "Tool failed: MaxToolTransientError: Cluster memory is full. You may retry this operation once without changes.",
            ),
            (
                PermissionDenied("Query access denied"),
                "permission",
                "Tool failed: MaxToolFatalError: Query access denied.",
            ),
            (
                UserAccessControlError("insight", "viewer"),
                "permission",
                "Tool failed: MaxToolAccessDeniedError: The user does not have viewer access to access insights. Suggest the user to contact their project admin to request access..",
            ),
            (
                ClickHouseQueryTimeOut("Query timed out"),
                "timeout",
                "Tool failed: MaxToolRetryableError: Query timed out. You may retry with adjusted inputs.",
            ),
            (
                ClickHouseQueryMemoryLimitExceeded("Query memory limit exceeded"),
                "memory_limit",
                "Tool failed: MaxToolRetryableError: Query memory limit exceeded. You may retry with adjusted inputs.",
            ),
            (
                ClickHouseEstimatedQueryExecutionTimeTooLong("Query estimate exceeded the time limit"),
                "validation",
                "Tool failed: MaxToolRetryableError: Query estimate exceeded the time limit. You may retry with adjusted inputs.",
            ),
            (
                ClickHouseQuerySizeExceeded("Query size exceeded"),
                "validation",
                "Tool failed: MaxToolRetryableError: Query size exceeded. You may retry with adjusted inputs.",
            ),
            (APIException("Query service failed"), "api_5xx", "Tool failed: MaxToolFatalError: Query service failed."),
            (
                ValidationError("Invalid query input"),
                "validation",
                "Tool failed: MaxToolRetryableError: Invalid query input. You may retry with adjusted inputs.",
            ),
            (
                HogQLSyntaxError("Unexpected SELECT"),
                "validation",
                "Tool failed: MaxToolRetryableError: Unexpected SELECT. You may retry with adjusted inputs.",
            ),
            (
                QueryError("Unknown field: missing_column"),
                "validation",
                "Tool failed: MaxToolRetryableError: Unknown field: missing_column. You may retry with adjusted inputs.",
            ),
            (
                HogQLNotImplementedError("QueryVisitor has no method visit_select_query"),
                "internal",
                "Tool failed: MaxToolRetryableError: QueryVisitor has no method visit_select_query. You may retry with adjusted inputs.",
            ),
            param(
                CHQueryErrorIllegalTypeOfArgument("Illegal argument type", code=43),
                "validation",
                "Tool failed: MaxToolRetryableError: Illegal argument type. You may retry with adjusted inputs.",
                error_code="illegal_type_of_argument",
            ),
            (
                CHQueryErrorCorruptedParquetMetadata("Warehouse file metadata is corrupt", code=1001),
                "internal",
                "Tool failed: MaxToolRetryableError: Warehouse file metadata is corrupt. You may retry with adjusted inputs.",
            ),
            param(
                CHQueryErrorS3FileChangedDuringRead("Warehouse file changed while reading", code=499),
                "api_5xx",
                "Tool failed: MaxToolTransientError: Warehouse file changed while reading. You may retry this operation once without changes.",
                error_code="s3_error",
            ),
            param(
                CHQueryErrorS3Error("Storage read failed", code=499),
                "api_5xx",
                "Tool failed: MaxToolTransientError: Code: 499.\nStorage read failed. You may retry this operation once without changes.",
                error_code="s3_error",
            ),
            param(
                InternalCHQueryError("Too many parts", code=252, code_name="caller-supplied-name"),
                "internal",
                "Tool failed: MaxToolRetryableError: Error executing query: There was an unknown error running this query: Code: 252.\nToo many parts. You may retry with adjusted inputs.",
                error_code="too_many_parts",
            ),
            (
                InternalCHQueryError("Unknown failure", code=99999, code_name="s3_error"),
                "internal",
                "Tool failed: MaxToolRetryableError: Error executing query: There was an unknown error running this query: Code: 99999.\nUnknown failure. You may retry with adjusted inputs.",
            ),
            (
                _wrapped_hogql_error(TableAccessDeniedError("restricted_table"), "Warehouse table access denied"),
                "permission",
                "Tool failed: MaxToolFatalError: Warehouse table access denied.",
            ),
            (
                _wrapped_hogql_error(
                    _wrapped_hogql_error(QueryError("Invalid query input"), "Query validation failed"),
                    "Warehouse SQL is invalid",
                ),
                "validation",
                "Tool failed: MaxToolRetryableError: Warehouse SQL is invalid. You may retry with adjusted inputs.",
            ),
            (
                _wrapped_hogql_error(ConnectionError("connection refused"), "Warehouse connection failed"),
                "internal",
                "Tool failed: MaxToolRetryableError: Warehouse connection failed. You may retry with adjusted inputs.",
            ),
            (
                ExposedHogQLError("Managed warehouse is not available"),
                "internal",
                "Tool failed: MaxToolRetryableError: Managed warehouse is not available. You may retry with adjusted inputs.",
            ),
            (
                ValueError("Invalid query result encoding"),
                "internal",
                "Tool failed: MaxToolRetryableError: Error executing query: There was an unknown error running this query: Invalid query result encoding. You may retry with adjusted inputs.",
            ),
        ]
    )
    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    def test_query_failures_preserve_recovery_advice(
        self, error: Exception, error_type: str, content: str, mock_query: Mock, *, error_code: str | None = None
    ) -> None:
        mock_query.side_effect = error

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_tools/execute_sql/",
            {"args": {"query": "SELECT 1"}},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        expected = {"success": False, "content": content, "error_type": error_type}
        if error_code:
            expected["error_code"] = error_code
        self.assertEqual(response.json(), expected)

    @parameterized.expand(
        [
            (
                "query_error",
                None,
                "Query failed",
                None,
                "Tool failed: MaxToolRetryableError: Query failed. You may retry with adjusted inputs.",
            ),
            (
                "missing_error_message",
                None,
                None,
                None,
                "Tool failed: MaxToolRetryableError: Error executing query: There was an unknown error running this query: Query failed. You may retry with adjusted inputs.",
            ),
            (
                "query_was_cancelled",
                None,
                None,
                "query_was_cancelled",
                "Tool failed: MaxToolRetryableError: Error executing query: There was an unknown error running this query: Query failed. You may retry with adjusted inputs.",
            ),
            param(
                "storage_error",
                None,
                None,
                "S3_ERROR",
                "Tool failed: MaxToolRetryableError: PostHog couldn't read from storage while running this query. "
                "Wait a few minutes, then run the query again. If the problem continues, contact support.. "
                "You may retry with adjusted inputs.",
                expected_error_code="s3_error",
            ),
            param(
                "memory_limit",
                None,
                "Query memory limit exceeded",
                "clickhouse_memory_limit_exceeded",
                "Tool failed: MaxToolRetryableError: Query memory limit exceeded. You may retry with adjusted inputs.",
                expected_error_type="memory_limit",
            ),
            param(
                "legacy_memory_message",
                None,
                "Query memory limit exceeded",
                None,
                "Tool failed: MaxToolRetryableError: Query memory limit exceeded. You may retry with adjusted inputs.",
            ),
            (
                "polling_error",
                ConnectionError("Query status unavailable"),
                None,
                None,
                "Tool failed: MaxToolRetryableError: Error executing query: There was an unknown error running this query: Query status unavailable. You may retry with adjusted inputs.",
            ),
        ]
    )
    @patch("ee.hogai.context.insight.query_executor.asyncio.sleep", new_callable=AsyncMock)
    @patch("ee.hogai.context.insight.query_executor.get_query_status")
    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    def test_async_query_failures_preserve_recovery_advice(
        self,
        _name: str,
        polling_error: Exception | None,
        error_message: str | None,
        error_code: str | None,
        content: str,
        mock_query: Mock,
        mock_status: Mock,
        _mock_sleep: AsyncMock,
        *,
        expected_error_code: str | None = None,
        expected_error_type: str = "internal",
    ) -> None:
        mock_query.return_value = {"query_status": {"id": "test-query-id", "complete": False}}
        mock_status.side_effect = polling_error
        mock_status.return_value.model_dump.return_value = {
            "id": "test-query-id",
            "complete": True,
            "error": True,
            "error_message": error_message,
            "error_code": error_code,
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_tools/execute_sql/",
            {"args": {"query": "SELECT 1"}},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        expected = {"success": False, "content": content, "error_type": expected_error_type}
        if expected_error_code:
            expected["error_code"] = expected_error_code
        self.assertEqual(response.json(), expected)

    @patch("ee.hogai.tools.execute_sql.mcp_tool.ExecuteSQLMCPTool.execute", new_callable=AsyncMock)
    def test_invoke_tool_unexpected_error_returns_internal_error(self, mock_execute):
        mock_execute.side_effect = RuntimeError("unexpected")

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
                "content": "The tool raised an internal error. Do not immediately retry the tool call.",
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
