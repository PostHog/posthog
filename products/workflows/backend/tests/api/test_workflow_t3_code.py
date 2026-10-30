from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models import User

from products.mcp_store.backend.models import MCPServerInstallation, MCPServerInstallationTool

T3_CODE_TOOLS = ("t3_project_list", "schedule_task")
UPSTREAM_CALL = "products.mcp_store.backend.facade.api.call_upstream_tool"
FLAG_CHECK = "products.workflows.backend.presentation.views.workflow_t3_code.is_hog_function_template_available"


@patch(FLAG_CHECK, return_value=True)
class TestWorkflowT3Code(APIBaseTest):
    def _connect(
        self,
        host: str,
        *,
        name: str = "",
        user: User | None = None,
        tools: tuple[str, ...] = T3_CODE_TOOLS,
        approval_state: str = "approved",
    ) -> MCPServerInstallation:
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=user or self.user,
            display_name=name,
            url=f"https://{host}/mcp",
            auth_type="api_key",
            sensitive_configuration={"api_key": "test-key"},
        )
        for tool in tools:
            MCPServerInstallationTool.objects.create(
                installation=installation,
                tool_name=tool,
                approval_state=approval_state,
                last_seen_at=timezone.now(),
            )
        return installation

    def _url(self, path: str) -> str:
        return f"/api/projects/{self.team.id}/workflow_t3_code/{path}/"

    def test_machines_are_the_members_own_t3_code_connections(self, _flag: MagicMock) -> None:
        self._connect("laptop.t3coderelay.com", name="My laptop")
        self._connect("mcp.linear.app", name="Linear", tools=("list_issues",))
        teammate = User.objects.create_and_join(self.organization, "teammate@posthog.com", "password")
        self._connect("teammate.t3coderelay.com", name="Teammate's box", user=teammate)

        response = self.client.get(self._url("machines"))

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"machines": [{"host": "laptop.t3coderelay.com", "name": "My laptop"}]}

    def test_hidden_without_the_t3_code_step_flag(self, flag: MagicMock) -> None:
        flag.return_value = False

        response = self.client.get(self._url("machines"))

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch(UPSTREAM_CALL)
    def test_projects_wait_for_the_members_approval(self, upstream: MagicMock, _flag: MagicMock) -> None:
        self._connect("laptop.t3coderelay.com", approval_state="needs_approval")
        upstream.return_value = {
            "structuredContent": {
                "projects": [
                    {
                        "id": "project-1",
                        "title": "posthog",
                        "workspaceRoot": "/code/posthog",
                        "defaultModelSelection": {"provider": "claudeAgent", "model": "claude-opus-5-5"},
                    },
                    {
                        "id": "project-2",
                        "title": "website",
                        "workspaceRoot": "/code/website",
                        "defaultModelSelection": None,
                    },
                ]
            }
        }

        asked = self.client.post(self._url("projects"), {"machine": "laptop.t3coderelay.com"})

        assert asked.status_code == status.HTTP_200_OK, asked.json()
        assert asked.json()["status"] == "needs_approval"
        upstream.assert_not_called()

        approved = self.client.post(
            self._url("projects"),
            {"machine": "laptop.t3coderelay.com", "approval_token": asked.json()["approval_token"]},
        )

        assert approved.status_code == status.HTTP_200_OK, approved.json()
        assert approved.json() == {
            "status": "ok",
            "approval_token": None,
            "projects": [
                {"id": "project-1", "title": "posthog", "has_default_model": True},
                {"id": "project-2", "title": "website", "has_default_model": False},
            ],
        }

    @patch(UPSTREAM_CALL)
    def test_creating_a_webhook_task_returns_its_url(self, upstream: MagicMock, _flag: MagicMock) -> None:
        self._connect("laptop.t3coderelay.com")
        upstream.return_value = {
            "structuredContent": {
                "scheduledTaskId": "task-1",
                "webhookUrl": "https://relay.t3.codes/v1/hooks/endpoint/hook/token",
            }
        }

        response = self.client.post(
            self._url("webhook_tasks"),
            {"machine": "laptop.t3coderelay.com", "project_id": "project-1", "title": "Fix failed payments"},
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {
            "status": "ok",
            "approval_token": None,
            "webhook_url": "https://relay.t3.codes/v1/hooks/endpoint/hook/token",
        }
        _installation, tool_name, arguments = upstream.call_args.args
        assert tool_name == "schedule_task"
        assert arguments["projectId"] == "project-1"
        assert arguments["title"] == "Fix failed payments"
        assert arguments["bindToCurrentThread"] is False
        assert arguments["schedule"] == {
            "type": "webhook",
            "dedupe": {"replayKey": "{{headers.x-posthog-delivery-id}}"},
        }
        assert "{{body.instructions}}" in arguments["prompt"]

    @patch(UPSTREAM_CALL)
    def test_a_task_without_a_public_url_asks_for_t3_connect(self, upstream: MagicMock, _flag: MagicMock) -> None:
        self._connect("laptop.t3coderelay.com")
        upstream.return_value = {"structuredContent": {"scheduledTaskId": "task-1"}}

        response = self.client.post(
            self._url("webhook_tasks"),
            {"machine": "laptop.t3coderelay.com", "project_id": "project-1", "title": "Fix failed payments"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "T3 Connect" in response.json()["detail"]

    @parameterized.expand(
        [
            ("plain text", "This MCP client was approved for read-only access."),
            (
                "orchestrator failure",
                '{"_tag":"OrchestratorMcpFailure","code":"invalid_request",'
                '"message":"This MCP client was approved for read-only access."}',
            ),
        ]
    )
    @patch(UPSTREAM_CALL)
    def test_t3_code_errors_reach_the_member(
        self, _name: str, text: str, upstream: MagicMock, _flag: MagicMock
    ) -> None:
        self._connect("laptop.t3coderelay.com")
        upstream.return_value = {"isError": True, "content": [{"type": "text", "text": text}]}

        response = self.client.post(
            self._url("webhook_tasks"),
            {"machine": "laptop.t3coderelay.com", "project_id": "project-1", "title": "Fix failed payments"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "This MCP client was approved for read-only access."
