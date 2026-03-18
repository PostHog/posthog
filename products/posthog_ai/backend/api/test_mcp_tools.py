from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from rest_framework import status

from posthog.models import Organization, Team


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

    @patch("ee.hogai.tools.execute_sql.mcp_tool.ExecuteSQLMCPTool.execute", new_callable=AsyncMock)
    def test_invoke_execute_sql_success(self, mock_execute):
        mock_execute.return_value = "event | cnt\ntest_event | 5"

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_tools/execute_sql/",
            {"args": {"query": "SELECT event, count() as cnt FROM events GROUP BY event"}},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("test_event", data["content"])
        mock_execute.assert_called_once()

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
