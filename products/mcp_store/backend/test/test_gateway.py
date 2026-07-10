import json
import time
import uuid
from datetime import timedelta

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

import httpx
from parameterized import parameterized
from rest_framework import status

from posthog.models import User

from products.mcp_store.backend.models import MCPServerInstallation, MCPServerInstallationTool
from products.mcp_store.backend.oauth import TokenRefreshError, refresh_installation_token_single_flight
from products.mcp_store.backend.tasks.tasks import maintain_shared_installations


def _initialize_response(session_id: str | None = "session-1") -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    headers = {"content-type": "application/json"}
    if session_id:
        headers["mcp-session-id"] = session_id
    response.headers = headers
    response.text = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}})
    return response


def _accepted_response() -> MagicMock:
    response = MagicMock()
    response.status_code = 202
    response.headers = {"content-type": "application/json"}
    response.text = ""
    return response


def _call_response(result: dict) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.headers = {"content-type": "application/json"}
    response.text = json.dumps({"jsonrpc": "2.0", "id": 3, "result": result})
    return response


class GatewayTestBase(APIBaseTest):
    def setUp(self):
        super().setUp()
        for target in (
            "products.mcp_store.backend.client.is_url_allowed",
            "products.mcp_store.backend.tools.is_url_allowed",
            "products.mcp_store.backend.proxy.is_url_allowed",
        ):
            patcher = patch(target, return_value=(True, None))
            patcher.start()
            self.addCleanup(patcher.stop)

    def _installation(self, **kwargs) -> MCPServerInstallation:
        defaults = {
            "team": self.team,
            "user": self.user,
            "display_name": "Linear",
            "url": f"https://mcp-{uuid.uuid4().hex[:8]}.example.com/mcp",
            "auth_type": "api_key",
            "sensitive_configuration": {"api_key": "sk-test"},
        }
        defaults.update(kwargs)
        return MCPServerInstallation.objects.create(**defaults)

    def _tool(self, installation, name, approval_state="approved", **kwargs) -> MCPServerInstallationTool:
        defaults = {
            "installation": installation,
            "tool_name": name,
            "approval_state": approval_state,
            "last_seen_at": timezone.now(),
        }
        defaults.update(kwargs)
        return MCPServerInstallationTool.objects.create(**defaults)

    def _mock_upstream_call(self, mock_client_cls, result: dict) -> MagicMock:
        mock_client = MagicMock()
        mock_client.post.side_effect = [_initialize_response(), _accepted_response(), _call_response(result)]
        mock_client_cls.return_value.__enter__.return_value = mock_client
        return mock_client

    def _tools_url(self) -> str:
        return f"/api/projects/{self.team.id}/mcp_gateway/tools/"

    def _call_url(self) -> str:
        return f"/api/projects/{self.team.id}/mcp_gateway/call/"


class TestGatewayToolsEndpoint(GatewayTestBase):
    def test_lists_namespaced_tools_with_server_metadata(self):
        other_user = User.objects.create_and_join(self.organization, "owner@posthog.com", "password")
        shared = self._installation(user=other_user, scope="shared", display_name="Notion")
        personal = self._installation(display_name="Linear")
        self._tool(shared, "search_pages", description="Search Notion pages")
        self._tool(personal, "create_issue", approval_state="needs_approval")

        response = self.client.get(self._tools_url())

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 2
        by_name = {item["name"]: item for item in body["results"]}
        assert set(by_name) == {"notion/search_pages", "linear/create_issue"}
        assert by_name["notion/search_pages"]["server"] == {
            "slug": "notion",
            "display_name": "Notion",
            "installation_id": str(shared.id),
            "scope": "shared",
        }
        assert by_name["linear/create_issue"]["approval_state"] == "needs_approval"
        assert by_name["linear/create_issue"]["tool_name"] == "create_issue"

    def test_personal_installation_shadows_shared_for_same_url(self):
        other_user = User.objects.create_and_join(self.organization, "owner@posthog.com", "password")
        url = "https://mcp.linear.app/mcp"
        shared = self._installation(user=other_user, scope="shared", url=url)
        personal = self._installation(url=url)
        self._tool(shared, "create_issue")
        self._tool(personal, "create_issue")

        response = self.client.get(self._tools_url())

        body = response.json()
        assert body["count"] == 1
        assert body["results"][0]["server"]["installation_id"] == str(personal.id)
        assert body["results"][0]["server"]["scope"] == "personal"

    def test_slug_collisions_get_deterministic_suffixes(self):
        first = self._installation(display_name="Linear")
        second = self._installation(display_name="Linear")
        MCPServerInstallation.objects.filter(id=first.id).update(created_at=timezone.now() - timedelta(days=1))
        self._tool(first, "a")
        self._tool(second, "a")

        response = self.client.get(self._tools_url())

        by_slug = {item["server"]["slug"]: item["server"]["installation_id"] for item in response.json()["results"]}
        assert by_slug == {"linear": str(first.id), "linear-2": str(second.id)}

    def test_excludes_hidden_tools_and_unavailable_installations(self):
        installation = self._installation()
        self._tool(installation, "approved_tool")
        self._tool(installation, "pending_tool", approval_state="needs_approval")
        self._tool(installation, "banned_tool", approval_state="do_not_use")
        self._tool(installation, "gone_tool", removed_at=timezone.now())
        disabled = self._installation(display_name="Disabled", is_enabled=False)
        self._tool(disabled, "unreachable_tool")
        stranger = User.objects.create_and_join(self.organization, "stranger@posthog.com", "password")
        others_personal = self._installation(user=stranger, display_name="Private")
        self._tool(others_personal, "private_tool")

        response = self.client.get(self._tools_url())

        names = {item["name"] for item in response.json()["results"]}
        assert names == {"linear/approved_tool", "linear/pending_tool"}

    @parameterized.expand(
        [
            ("search_matches_name", {"search": "create"}, ["linear/create_issue"]),
            ("search_ranks_name_before_description", {"search": "issue"}, ["linear/create_issue", "linear/list_teams"]),
            ("exact_name", {"name": "linear/list_teams"}, ["linear/list_teams"]),
            ("exact_name_miss", {"name": "linear/ghost"}, []),
        ]
    )
    def test_search_and_name_filters(self, _name, params, expected_names):
        installation = self._installation()
        self._tool(installation, "create_issue", description="Create a new issue")
        self._tool(installation, "list_teams", description="List teams that contain issues")

        response = self.client.get(self._tools_url(), params)

        assert [item["name"] for item in response.json()["results"]] == expected_names

    def test_pagination_slices_results_and_keeps_total_count(self):
        installation = self._installation()
        for index in range(3):
            self._tool(installation, f"tool_{index}")

        response = self.client.get(self._tools_url(), {"limit": 1, "offset": 1})

        body = response.json()
        assert body["count"] == 3
        assert [item["name"] for item in body["results"]] == ["linear/tool_1"]


class TestGatewayCallEndpoint(GatewayTestBase):
    @patch("products.mcp_store.backend.client.httpx.Client")
    def test_call_executes_approved_tool_upstream(self, mock_client_cls):
        installation = self._installation()
        self._tool(installation, "create_issue")
        mock_client = self._mock_upstream_call(
            mock_client_cls, {"content": [{"type": "text", "text": "created"}], "isError": False}
        )

        response = self.client.post(
            self._call_url(),
            data={"tool": "linear/create_issue", "arguments": {"title": "Bug"}},
            format="json",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["content"] == [{"type": "text", "text": "created"}]
        assert body["is_error"] is False
        assert body["server_slug"] == "linear"
        assert body["tool_name"] == "create_issue"
        assert isinstance(body["duration_ms"], int)
        call_request = json.loads(mock_client.post.call_args_list[2].kwargs["content"])
        assert call_request["method"] == "tools/call"
        assert call_request["params"] == {"name": "create_issue", "arguments": {"title": "Bug"}}
        assert mock_client.post.call_args_list[2].kwargs["headers"]["Authorization"] == "Bearer sk-test"

    @patch("products.mcp_store.backend.client.httpx.Client")
    def test_call_returns_tool_error_result_as_200(self, mock_client_cls):
        installation = self._installation()
        self._tool(installation, "create_issue")
        self._mock_upstream_call(mock_client_cls, {"content": [{"type": "text", "text": "boom"}], "isError": True})

        response = self.client.post(self._call_url(), data={"tool": "linear/create_issue"}, format="json")

        assert response.status_code == 200
        assert response.json()["is_error"] is True

    @parameterized.expand(
        [
            ("needs_approval", "needs_approval", None, 403, "tool_needs_approval"),
            ("do_not_use", "do_not_use", None, 403, "tool_blocked"),
            ("unknown_tool", "approved", "linear/ghost", 404, "tool_not_found"),
            ("unknown_server", "approved", "ghost/create_issue", 404, "tool_not_found"),
            ("unnamespaced_name", "approved", "create_issue", 404, "tool_not_found"),
            ("removed_tool", "approved", None, 404, "tool_not_found"),
        ]
    )
    @patch("products.mcp_store.backend.client.httpx.Client")
    def test_call_error_mapping_short_circuits_upstream(
        self, case, approval_state, override_tool, expected_status, expected_code, mock_client_cls
    ):
        installation = self._installation()
        removed_at = timezone.now() if case == "removed_tool" else None
        self._tool(installation, "create_issue", approval_state=approval_state, removed_at=removed_at)

        response = self.client.post(
            self._call_url(),
            data={"tool": override_tool or "linear/create_issue"},
            format="json",
        )

        assert response.status_code == expected_status
        body = response.json()
        assert body["code"] == expected_code
        if expected_code == "tool_needs_approval":
            assert body["approval_url"].endswith(f"/project/{self.team.id}/settings/mcp-servers")
        mock_client_cls.assert_not_called()

    @parameterized.expand(
        [
            ("connect_error", httpx.ConnectError("refused"), "unreachable"),
            ("timeout", httpx.TimeoutException("slow"), "timeout"),
        ]
    )
    @patch("products.mcp_store.backend.client.httpx.Client")
    def test_call_upstream_failures_map_to_502(self, _name, side_effect, expected_error_type, mock_client_cls):
        installation = self._installation()
        self._tool(installation, "create_issue")
        mock_client = MagicMock()
        mock_client.post.side_effect = side_effect
        mock_client_cls.return_value.__enter__.return_value = mock_client

        response = self.client.post(self._call_url(), data={"tool": "linear/create_issue"}, format="json")

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        body = response.json()
        assert body["code"] == "upstream_error"
        assert body["error_type"] == expected_error_type

    @patch("products.mcp_store.backend.client.httpx.Client")
    def test_call_cannot_reach_another_users_personal_installation(self, mock_client_cls):
        stranger = User.objects.create_and_join(self.organization, "stranger@posthog.com", "password")
        installation = self._installation(user=stranger, display_name="Private")
        self._tool(installation, "secret_tool")

        response = self.client.post(self._call_url(), data={"tool": "private/secret_tool"}, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_client_cls.assert_not_called()

    def test_call_requires_tool_field(self):
        response = self.client.post(self._call_url(), data={"arguments": {}}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestGatewayAnalytics(GatewayTestBase):
    @patch("products.mcp_store.backend.analytics.report_user_action")
    @patch("products.mcp_store.backend.client.httpx.Client")
    def test_gateway_call_emits_metadata_only_event(self, mock_client_cls, mock_report):
        installation = self._installation()
        self._tool(installation, "create_issue")
        self._mock_upstream_call(
            mock_client_cls, {"content": [{"type": "text", "text": "top-secret-result"}], "isError": False}
        )

        response = self.client.post(
            self._call_url(),
            data={"tool": "linear/create_issue", "arguments": {"title": "top-secret-arg"}, "consumer": "tasks"},
            format="json",
        )

        assert response.status_code == 200
        mock_report.assert_called_once()
        args, kwargs = mock_report.call_args
        assert args[1] == "$mcp_tool_call"
        properties = args[2]
        assert properties["$mcp_source"] == "gateway"
        assert properties["$mcp_tool_name"] == "linear/create_issue"
        assert properties["$mcp_gateway_server"] == "linear"
        assert properties["$mcp_gateway_installation_id"] == str(installation.id)
        assert properties["$mcp_scope"] == "personal"
        assert properties["$mcp_consumer"] == "tasks"
        assert properties["$mcp_is_error"] is False
        serialized = json.dumps(properties)
        assert "top-secret-arg" not in serialized
        assert "top-secret-result" not in serialized

    @patch("products.mcp_store.backend.analytics.report_user_action")
    def test_gateway_blocked_call_emits_error_event(self, mock_report):
        installation = self._installation()
        self._tool(installation, "create_issue", approval_state="needs_approval")

        self.client.post(self._call_url(), data={"tool": "linear/create_issue"}, format="json")

        properties = mock_report.call_args[0][2]
        assert properties["$mcp_is_error"] is True
        assert properties["$mcp_error_type"] == "needs_approval"

    @patch("products.mcp_store.backend.analytics.report_user_action")
    @patch("products.mcp_store.backend.proxy.httpx.Client")
    def test_store_proxy_tools_call_emits_event(self, mock_client_cls, mock_report):
        installation = self._installation()
        self._tool(installation, "create_issue")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.content = b'{"jsonrpc":"2.0","id":1,"result":{}}'
        mock_client = MagicMock()
        mock_client.build_request.return_value = MagicMock()
        mock_client.send.return_value = mock_response
        mock_client_cls.return_value = mock_client

        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/{installation.id}/proxy/",
            data={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "create_issue"}},
            format="json",
            headers={"x-posthog-mcp-consumer": "posthog-code"},
        )

        assert response.status_code == 200
        tool_call_events = [call for call in mock_report.call_args_list if call.args[1] == "$mcp_tool_call"]
        assert len(tool_call_events) == 1
        properties = tool_call_events[0].args[2]
        assert properties["$mcp_source"] == "store_proxy"
        assert properties["$mcp_tool_name"] == "linear/create_issue"
        assert properties["$mcp_consumer"] == "posthog-code"

    @patch("products.mcp_store.backend.analytics.report_user_action")
    @patch("products.mcp_store.backend.proxy.httpx.Client")
    def test_store_proxy_non_tool_methods_do_not_emit(self, mock_client_cls, mock_report):
        installation = self._installation()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.content = b'{"jsonrpc":"2.0","id":1,"result":{}}'
        mock_client = MagicMock()
        mock_client.build_request.return_value = MagicMock()
        mock_client.send.return_value = mock_response
        mock_client_cls.return_value = mock_client

        self.client.post(
            f"/api/environments/{self.team.id}/mcp_server_installations/{installation.id}/proxy/",
            data={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            format="json",
        )

        assert all(call.args[1] != "$mcp_tool_call" for call in mock_report.call_args_list)


class TestSingleFlightTokenRefresh(BaseTest):
    def _oauth_installation(self, sensitive) -> MCPServerInstallation:
        return MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name="OAuth Server",
            url="https://mcp.example.com/mcp",
            auth_type="oauth",
            oauth_metadata={"token_endpoint": "https://auth.example.com/token"},
            sensitive_configuration=sensitive,
        )

    def _fresh_sensitive(self) -> dict:
        return {
            "access_token": "fresh-token",
            "refresh_token": "rt",
            "token_retrieved_at": int(time.time()),
            "expires_in": 3600,
            "dcr_client_id": "client-123",
        }

    def _stale_sensitive(self) -> dict:
        return {
            "access_token": "stale-token",
            "refresh_token": "rt",
            "token_retrieved_at": int(time.time()) - 7200,
            "expires_in": 3600,
            "dcr_client_id": "client-123",
        }

    @patch("products.mcp_store.backend.oauth.refresh_oauth_token")
    def test_holder_refreshes_when_row_still_expiring(self, mock_refresh):
        mock_refresh.return_value = {"access_token": "new-token", "expires_in": 3600}
        installation = self._oauth_installation(self._stale_sensitive())

        result = refresh_installation_token_single_flight(installation)

        mock_refresh.assert_called_once()
        assert result["access_token"] == "new-token"

    @patch("products.mcp_store.backend.oauth.refresh_oauth_token")
    def test_holder_skips_refresh_when_another_holder_already_refreshed(self, mock_refresh):
        installation = self._oauth_installation(self._fresh_sensitive())
        # Simulate a stale in-memory copy: the DB row was refreshed by a concurrent holder.
        installation.sensitive_configuration = self._stale_sensitive()

        result = refresh_installation_token_single_flight(installation)

        mock_refresh.assert_not_called()
        assert result["access_token"] == "fresh-token"

    @parameterized.expand(
        [
            ("db_row_fresh", True),
            ("db_row_still_stale", False),
        ]
    )
    @patch("products.mcp_store.backend.oauth.refresh_oauth_token")
    @patch("products.mcp_store.backend.oauth.get_client")
    def test_lock_wait_timeout_falls_back_to_db_state(self, _name, db_fresh, mock_get_client, mock_refresh):
        lock = MagicMock()
        lock.acquire.return_value = False
        mock_get_client.return_value.lock.return_value = lock
        installation = self._oauth_installation(self._fresh_sensitive() if db_fresh else self._stale_sensitive())
        installation.sensitive_configuration = self._stale_sensitive()

        if db_fresh:
            result = refresh_installation_token_single_flight(installation)
            assert result["access_token"] == "fresh-token"
        else:
            with self.assertRaises(TokenRefreshError):
                refresh_installation_token_single_flight(installation)
        mock_refresh.assert_not_called()


class TestMaintainSharedInstallations(BaseTest):
    def _installation(self, *, scope, auth_type="oauth", sensitive=None, tool_seen_at=None) -> MCPServerInstallation:
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name="Server",
            url=f"https://mcp-{uuid.uuid4().hex[:8]}.example.com/mcp",
            auth_type=auth_type,
            scope=scope,
            sensitive_configuration=sensitive or {},
        )
        if tool_seen_at is not None:
            MCPServerInstallationTool.objects.create(
                installation=installation,
                tool_name="tool",
                approval_state="approved",
                last_seen_at=tool_seen_at,
            )
        return installation

    @patch("products.mcp_store.backend.tasks.tasks.sync_installation_tools")
    @patch("products.mcp_store.backend.tasks.tasks.refresh_installation_token_single_flight")
    def test_only_expiring_shared_tokens_and_stale_catalogs_are_touched(self, mock_refresh, mock_sync):
        expiring = {
            "access_token": "t",
            "refresh_token": "rt",
            "token_retrieved_at": int(time.time()) - 7200,
            "expires_in": 3600,
        }
        stale_shared = self._installation(scope="shared", sensitive=expiring)
        fresh_shared = self._installation(
            scope="shared", auth_type="api_key", sensitive={"api_key": "sk"}, tool_seen_at=timezone.now()
        )
        personal = self._installation(scope="personal", sensitive=expiring)

        maintain_shared_installations()

        refreshed_ids = {call.args[0].id for call in mock_refresh.call_args_list}
        synced_ids = {call.args[0].id for call in mock_sync.call_args_list}
        assert refreshed_ids == {stale_shared.id}
        assert synced_ids == {stale_shared.id}
        assert personal.id not in refreshed_ids | synced_ids
        assert fresh_shared.id not in refreshed_ids | synced_ids
