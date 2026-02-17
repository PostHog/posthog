from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import Organization, Team


class TestMCPToolsListAPI(APIBaseTest):
    def test_list_returns_registered_tools(self):
        response = self.client.get(f"/api/environments/{self.team.id}/mcp_tools/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)

        tool_names = [t["name"] for t in data]
        self.assertIn("execute_sql", tool_names)

    def test_list_tools_have_required_fields(self):
        response = self.client.get(f"/api/environments/{self.team.id}/mcp_tools/")
        data = response.json()

        for tool in data:
            self.assertIn("name", tool)
            self.assertIn("scopes", tool)
            self.assertIn("input_schema", tool)
            self.assertIsInstance(tool["scopes"], list)
            self.assertIsInstance(tool["input_schema"], dict)

    def test_list_unauthenticated(self):
        self.client.logout()
        response = self.client.get(f"/api/environments/{self.team.id}/mcp_tools/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_cannot_access_other_org(self):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        response = self.client.get(f"/api/environments/{other_team.id}/mcp_tools/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_execute_sql_tool_has_query_field_in_schema(self):
        response = self.client.get(f"/api/environments/{self.team.id}/mcp_tools/")
        data = response.json()

        execute_sql = next((t for t in data if t["name"] == "execute_sql"), None)
        self.assertIsNotNone(execute_sql)
        self.assertIn("properties", execute_sql["input_schema"])
        self.assertIn("query", execute_sql["input_schema"]["properties"])
