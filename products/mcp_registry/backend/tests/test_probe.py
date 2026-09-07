import json

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

import requests
from parameterized import parameterized

from products.mcp_registry.backend.models import MCPRegistryServer, MCPRegistryTool
from products.mcp_registry.backend.probe import ProbeOutcome, apply_probe_outcome, shallow_probe


def _response(status_code: int, body: dict | None = None, text: str = "", headers: dict | None = None) -> Mock:
    response = Mock(spec=requests.Response)
    response.status_code = status_code
    response.text = json.dumps(body) if body is not None else text
    response.headers = headers or {}
    return response


_INIT_RESULT = {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "demo"}, "capabilities": {}}}


class TestShallowProbe(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "oauth_challenge",
                _response(401, text="unauthorized", headers={"WWW-Authenticate": 'Bearer realm="mcp"'}),
                "alive_auth",
                "oauth",
            ),
            ("api_key_hint", _response(401, text="missing api key"), "alive_auth", "api_key"),
            ("auth_unclassified", _response(403, text="forbidden"), "alive_auth", "unknown"),
            ("redirect_refused", _response(302, text="", headers={"Location": "https://x"}), "not_mcp", "unknown"),
            ("html_page", _response(200, text="<html>hello</html>"), "not_mcp", "unknown"),
            ("server_error", _response(503, text="oops"), "dead", "unknown"),
            (
                "protocol_error",
                _response(200, body={"jsonrpc": "2.0", "id": 1, "error": {"code": -32600}}),
                "alive_protocol",
                "unknown",
            ),
        ]
    )
    @patch("products.mcp_registry.backend.probe.pinned_request")
    def test_classification(
        self, _name: str, response: Mock, expected_liveness: str, expected_auth: str, mock_request: Mock
    ) -> None:
        mock_request.return_value = response

        outcome = shallow_probe("https://demo.example.com/mcp")

        assert outcome.liveness == expected_liveness
        assert outcome.auth_method == expected_auth

    @patch("products.mcp_registry.backend.probe.pinned_request")
    def test_connection_failure_is_dead_not_raised(self, mock_request: Mock) -> None:
        mock_request.side_effect = requests.ConnectionError("refused")

        outcome = shallow_probe("https://demo.example.com/mcp")

        assert outcome.liveness == "dead"
        assert "refused" in outcome.detail

    @patch("products.mcp_registry.backend.probe.pinned_request")
    def test_open_server_captures_tools_over_sse(self, mock_request: Mock) -> None:
        tools_body = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "tools": [
                    {"name": "create_issue", "description": "Create an issue", "inputSchema": {"type": "object"}},
                    {"name": "", "description": "nameless, dropped"},
                ]
            },
        }
        sse_frame = f"event: message\ndata: {json.dumps(tools_body)}\n\n"
        mock_request.side_effect = [
            _response(200, body=_INIT_RESULT, headers={"mcp-session-id": "session-1"}),
            _response(202),
            _response(200, text=sse_frame),
        ]

        outcome = shallow_probe("https://demo.example.com/mcp")

        assert outcome.liveness == "alive_open"
        assert outcome.auth_method == "none"
        assert [tool["name"] for tool in outcome.tools] == ["create_issue"]
        # The session handle from initialize must be echoed on the follow-up calls.
        assert mock_request.call_args.kwargs["headers"]["mcp-session-id"] == "session-1"


class TestApplyProbeOutcome(BaseTest):
    def test_transient_failure_keeps_previously_detected_auth_method(self) -> None:
        server = MCPRegistryServer.objects.create(
            display_name="Demo", canonical_url="https://demo.example.com/mcp", auth_method="oauth"
        )

        apply_probe_outcome(server, ProbeOutcome(liveness="dead", auth_method="unknown", detail="timeout"))

        server.refresh_from_db()
        assert server.liveness == "dead"
        assert server.auth_method == "oauth"
        assert server.last_probed_at is not None

    def test_probed_tools_upgrade_analytics_rows_to_tools_list(self) -> None:
        server = MCPRegistryServer.objects.create(display_name="Demo", canonical_url="https://demo.example.com/mcp")
        outcome = ProbeOutcome(
            liveness="alive_open",
            auth_method="none",
            tools=[{"name": "create_issue", "description": "Create an issue", "input_schema": {"type": "object"}}],
        )

        apply_probe_outcome(server, outcome)

        tool = MCPRegistryTool.objects.get(server=server, name="create_issue")
        assert tool.source == "tools_list"
        assert tool.input_schema == {"type": "object"}
