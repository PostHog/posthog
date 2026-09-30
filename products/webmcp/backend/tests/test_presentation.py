from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal

from products.webmcp.backend.tests.test_logic import create_webmcp_app, mcp_response


@patch("products.webmcp.backend.logic.mcp_server.requests.post")
class TestWebMCPViewSet(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # The CIMD lookup refreshes the document from posthog.com, which a test must not reach.
        patcher = patch(
            "products.webmcp.backend.logic.tokens.get_or_create_cimd_application", return_value=create_webmcp_app()
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        region_patcher = patch("products.webmcp.backend.logic.mcp_server.get_instance_region", return_value="US")
        region_patcher.start()
        self.addCleanup(region_patcher.stop)

    def test_exec_forwards_the_command_and_returns_the_tool_result(self, mock_post: MagicMock) -> None:
        mock_post.return_value = mcp_response(
            200,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"content": [{"type": "text", "text": "insight-get"}], "isError": False},
            },
        )

        response = self.client.post(f"/api/projects/{self.team.id}/webmcp/exec/", {"command": "search insights"})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"content": [{"type": "text", "text": "insight-get"}], "is_error": False}
        body = mock_post.call_args.kwargs["json"]
        assert (body["method"], body["params"]["arguments"]) == ("tools/call", {"command": "search insights"})

    def test_exec_reports_an_mcp_error_as_bad_gateway(self, mock_post: MagicMock) -> None:
        mock_post.return_value = mcp_response(
            400, {"jsonrpc": "2.0", "id": 1, "error": {"code": -32020, "message": "Header mismatch"}}
        )

        response = self.client.post(f"/api/projects/{self.team.id}/webmcp/exec/", {"command": "tools"})

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.json()["detail"] == "Header mismatch"

    def test_exec_rejects_an_impersonated_session(self, mock_post: MagicMock) -> None:
        with patch("products.webmcp.backend.presentation.views.is_impersonated_session", return_value=True):
            response = self.client.post(f"/api/projects/{self.team.id}/webmcp/exec/", {"command": "tools"})

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_post.assert_not_called()

    def test_exec_rejects_a_personal_api_key(self, mock_post: MagicMock) -> None:
        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Test", user=self.user, secure_value=hash_key_value(key_value), scopes=["*"]
        )
        self.client.logout()

        response = self.client.post(
            f"/api/projects/{self.team.id}/webmcp/exec/",
            {"command": "tools"},
            headers={"authorization": f"Bearer {key_value}"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_post.assert_not_called()
