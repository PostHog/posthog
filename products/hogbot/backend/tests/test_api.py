from unittest.mock import MagicMock, patch

from django.test import TestCase

import requests as http_requests
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal
from posthog.storage import object_storage

from products.hogbot.backend import gateway, logic


class BaseHogbotAPITest(TestCase):
    databases = {"default"}
    client: APIClient
    team: Team
    user: User

    def setUp(self):
        self.settings_override = self.settings(
            OBJECT_STORAGE_ENABLED=True,
            OBJECT_STORAGE_HOGBOT_FOLDER=f"test-hogbot-{self._testMethodName}",
        )
        self.settings_override.enable()
        self.client = APIClient()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(email="test@example.com", first_name="Test", password="password")
        self.organization.members.add(self.user)
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )
        self.client.force_authenticate(self.user)

    def tearDown(self):
        self.settings_override.disable()
        super().tearDown()

    def connection_info(self, *, server_url: str = "https://demo.modal.run", connect_token: str | None = None):
        return gateway.HogbotConnectionInfo(
            workflow_id=f"hogbot-team-{self.team.pk}",
            run_id="run-1",
            phase="running",
            ready=True,
            sandbox_id="sandbox-1",
            server_url=server_url,
            connect_token=connect_token,
            error=None,
        )


class TestHogbotServerEndpoints(BaseHogbotAPITest):
    @patch("products.hogbot.backend.api.gateway.get_hogbot_connection", return_value=None)
    def test_health_accepts_personal_api_key(self, mock_connection: MagicMock):
        api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="Hogbot test",
            secure_value=hash_key_value(api_key),
            scopes=["*"],
        )
        client = APIClient()

        response = client.get(
            f"/api/projects/{self.team.pk}/hogbot/health/",
            HTTP_AUTHORIZATION=f"Bearer {api_key}",
        )

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.json(), {"error": "No active hogbot server for this team"})
        mock_connection.assert_called_once()

    @patch("posthog.storage.object_storage.tag")
    def test_append_admin_log_persists_jsonl(self, mock_tag: MagicMock):
        response = self.client.post(
            "/api/projects/@current/hogbot/admin/append_log/",
            {
                "entries": [
                    {
                        "type": "notification",
                        "timestamp": "2026-03-25T10:00:00Z",
                        "notification": {"jsonrpc": "2.0", "method": "_hogbot/status", "params": {"status": "running"}},
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        content = object_storage.read(logic.get_admin_log_key(self.team.pk), missing_ok=True)
        self.assertIsNotNone(content)
        assert content is not None
        self.assertIn("_hogbot/status", content)
        mock_tag.assert_called_once()

    def test_append_research_log_persists_jsonl(self):
        response = self.client.post(
            "/api/projects/@current/hogbot/research/sig-123/append_log/",
            {
                "entries": [
                    {
                        "type": "notification",
                        "timestamp": "2026-03-25T10:02:00Z",
                        "notification": {"jsonrpc": "2.0", "method": "_hogbot/result", "params": {"output": "done"}},
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        content = object_storage.read(logic.get_research_log_key(self.team.pk, "sig-123"), missing_ok=True)
        self.assertIsNotNone(content)
        assert content is not None
        self.assertIn("_hogbot/result", content)

    def test_admin_logs_filter_by_event_type(self):
        logic.append_log_entries(
            logic.get_admin_log_key(self.team.pk),
            self.team.pk,
            [
                {
                    "type": "notification",
                    "timestamp": "2026-03-25T10:00:00Z",
                    "notification": {"jsonrpc": "2.0", "method": "_hogbot/status", "params": {"status": "running"}},
                },
                {
                    "type": "notification",
                    "timestamp": "2026-03-25T10:01:00Z",
                    "notification": {"jsonrpc": "2.0", "method": "_hogbot/result", "params": {"output": "done"}},
                },
            ],
        )

        response = self.client.get("/api/projects/@current/hogbot/admin/logs/?event_types=_hogbot/result")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.content.decode("utf-8").strip().splitlines()
        self.assertEqual(len(payload), 1)
        self.assertIn("_hogbot/result", payload[0])

    def test_research_logs_filter_by_after_parameter(self):
        logic.append_log_entries(
            logic.get_research_log_key(self.team.pk, "sig-after"),
            self.team.pk,
            [
                {
                    "type": "notification",
                    "timestamp": "2026-03-25T10:00:00Z",
                    "notification": {"jsonrpc": "2.0", "method": "_hogbot/status", "params": {"status": "running"}},
                },
                {
                    "type": "notification",
                    "timestamp": "2026-03-25T10:05:00Z",
                    "notification": {"jsonrpc": "2.0", "method": "_hogbot/result", "params": {"output": "done"}},
                },
            ],
        )

        response = self.client.get("/api/projects/@current/hogbot/research/sig-after/logs/?after=2026-03-25T10:01:00Z")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["notification"]["method"], "_hogbot/result")

    @patch("products.hogbot.backend.api.gateway.get_hogbot_connection", return_value=None)
    def test_health_returns_503_without_connection_info(self, mock_connection: MagicMock):
        response = self.client.get("/api/projects/@current/hogbot/health/")
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        mock_connection.assert_called_once()

    @patch("products.hogbot.backend.api.http_requests.request")
    @patch("products.hogbot.backend.api.gateway.get_hogbot_connection")
    def test_health_proxies_upstream(self, mock_connection: MagicMock, mock_request: MagicMock):
        mock_connection.return_value = self.connection_info()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok", "busy": "none"}
        mock_request.return_value = mock_response

        response = self.client.get("/api/projects/@current/hogbot/health/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], "ok")

    @patch("products.hogbot.backend.api.http_requests.request")
    @patch("products.hogbot.backend.api.gateway.get_hogbot_connection")
    def test_filesystem_proxy_uses_modal_connect_token(self, mock_connection: MagicMock, mock_request: MagicMock):
        mock_connection.return_value = self.connection_info(server_url="https://demo.modal.host", connect_token="modal-token")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"entry": {"path": "/"}}
        mock_request.return_value = mock_response

        response = self.client.get("/api/projects/@current/hogbot/filesystem/stat/?path=/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(mock_request.call_args.kwargs["params"]["_modal_connect_token"], "modal-token")

    @patch("products.hogbot.backend.api.http_requests.request")
    @patch("products.hogbot.backend.api.gateway.get_hogbot_connection")
    def test_logs_proxy_streams_sse_chunks(self, mock_connection: MagicMock, mock_request: MagicMock):
        mock_connection.return_value = self.connection_info()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_content.return_value = [b"data: {\"ok\":true}\n\n"]
        mock_request.return_value = mock_response

        response = self.client.get("/api/projects/@current/hogbot/logs/?scope=admin")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "text/event-stream")
        self.assertEqual(b"".join(response.streaming_content), b"data: {\"ok\":true}\n\n")
        mock_response.close.assert_called_once()

    @patch("products.hogbot.backend.api.http_requests.request")
    @patch("products.hogbot.backend.api.gateway.get_hogbot_connection")
    def test_send_message_maps_connection_error_to_502(self, mock_connection: MagicMock, mock_request: MagicMock):
        mock_connection.return_value = self.connection_info()
        mock_request.side_effect = http_requests.ConnectionError()

        response = self.client.post("/api/projects/@current/hogbot/send_message/", {"content": "hello"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)

    @patch("products.hogbot.backend.api.http_requests.request")
    @patch("products.hogbot.backend.api.gateway.get_hogbot_connection")
    def test_send_message_maps_timeout_to_504(self, mock_connection: MagicMock, mock_request: MagicMock):
        mock_connection.return_value = self.connection_info()
        mock_request.side_effect = http_requests.Timeout()

        response = self.client.post("/api/projects/@current/hogbot/send_message/", {"content": "hello"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_504_GATEWAY_TIMEOUT)

    @patch("products.hogbot.backend.api.gateway.get_hogbot_connection")
    def test_invalid_sandbox_url_is_rejected(self, mock_connection: MagicMock):
        mock_connection.return_value = self.connection_info(server_url="https://example.com")
        response = self.client.post("/api/projects/@current/hogbot/send_message/", {"content": "hello"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("products.hogbot.backend.api.http_requests.request")
    @patch("products.hogbot.backend.api.gateway.get_or_start_hogbot")
    @patch("products.hogbot.backend.api.gateway.get_hogbot_connection", return_value=None)
    def test_send_message_starts_workflow_when_connection_missing(
        self,
        mock_connection: MagicMock,
        mock_start: MagicMock,
        mock_request: MagicMock,
    ):
        mock_start.return_value = self.connection_info(server_url="http://127.0.0.1:47821")
        mock_response = MagicMock()
        mock_response.status_code = status.HTTP_200_OK
        mock_response.json.return_value = {"response": "hello from hogbot"}
        mock_request.return_value = mock_response

        response = self.client.post("/api/projects/@current/hogbot/send_message/", {"content": "hello"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"response": "hello from hogbot"})
        mock_start.assert_called_once_with(team_id=self.team.pk, user_id=self.user.pk)

    def test_compatibility_server_endpoints_are_noops(self):
        register = self.client.post("/api/projects/@current/hogbot/server/register/", {}, format="json")
        heartbeat = self.client.post("/api/projects/@current/hogbot/server/heartbeat/", {}, format="json")
        unregister = self.client.post("/api/projects/@current/hogbot/server/unregister/", {}, format="json")

        self.assertEqual(register.status_code, status.HTTP_200_OK)
        self.assertEqual(heartbeat.status_code, status.HTTP_200_OK)
        self.assertEqual(unregister.status_code, status.HTTP_200_OK)
