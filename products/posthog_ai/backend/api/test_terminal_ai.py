import json
from typing import cast

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.http import StreamingHttpResponse
from django.test import override_settings

import httpx
from parameterized import parameterized

from posthog.models import Organization, Team


@override_settings(AI_GATEWAY_URL="https://ai-gateway.test/v1", AI_GATEWAY_API_KEY="phs_test_only")
class TestTerminalAI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enabled = self.enterContext(
            patch("products.posthog_ai.backend.api.terminal_ai.feature_enabled_or_false", return_value=True)
        )
        self.limited = self.enterContext(
            patch("products.posthog_ai.backend.api.terminal_ai.is_team_limited", return_value=False)
        )
        self.enterContext(
            patch("products.posthog_ai.backend.api.terminal_ai.is_privacy_mode_enabled", return_value=True)
        )
        self.url = f"/api/projects/{self.team.id}/terminal_ai/"
        self.body = {
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "Say hello"}],
            "max_tokens": 100,
            "stream": True,
        }

    @parameterized.expand([("anonymous", 401), ("other_project", 403), ("flag_disabled", 403), ("quota", 402)])
    def test_access_denied_before_gateway_call(self, scenario: str, expected_status: int) -> None:
        if scenario == "anonymous":
            self.client.logout()
        elif scenario == "other_project":
            team = Team.objects.create(organization=Organization.objects.create(name="Another organization"))
            self.url = f"/api/projects/{team.id}/terminal_ai/"
        elif scenario == "flag_disabled":
            self.enabled.return_value = False
        else:
            self.limited.return_value = True
        with patch("products.posthog_ai.backend.api.terminal_ai._stream_generation") as stream:
            response = self.client.post(self.url, self.body, format="json")
        assert response.status_code == expected_status
        stream.assert_not_called()

    @parameterized.expand(
        [("model", "unapproved-model"), ("max_tokens", 100000), ("extra_headers", {"x-api-key": "fake"})]
    )
    def test_invalid_requests_do_not_reach_gateway(self, key: str, value: object) -> None:
        with patch("products.posthog_ai.backend.api.terminal_ai._stream_generation") as stream:
            response = self.client.post(self.url, {**self.body, key: value}, format="json")
        assert response.status_code == 400
        stream.assert_not_called()

    def test_stream_preserves_tool_calls_and_trusted_attribution(self) -> None:
        event = b'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"tool_1","name":"bash","input":{}}}\n\n'
        requests: list[httpx.Request] = []

        def gateway(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, content=event, headers={"Content-Type": "text/event-stream"})

        client = httpx.Client(transport=httpx.MockTransport(gateway))
        with (
            patch("products.posthog_ai.backend.api.terminal_ai.httpx.Client", return_value=client),
            patch("products.posthog_ai.backend.api.terminal_ai.is_impersonated_session", return_value=True),
        ):
            response = self.client.post(self.url, self.body, format="json")
            assert response.status_code == 200
            assert b"".join(cast(StreamingHttpResponse, response)) == event
        assert len(requests) == 1
        request = requests[0]
        assert str(request.url) == "https://ai-gateway.test/v1/messages"
        assert request.headers["x-api-key"] == "phs_test_only"
        assert request.headers["X-PostHog-Distinct-Id"] == self.user.distinct_id
        assert request.headers["X-PostHog-Product"] == "posthog_ai"
        assert request.headers["X-PostHog-Privacy-Mode"] == "true"
        assert request.headers["X-PostHog-Billable"] == "false"
        assert json.loads(request.headers["X-PostHog-Properties"])["team_id"] == str(self.team.id)
        assert json.loads(request.content)["messages"] == self.body["messages"]

    def test_gateway_errors_do_not_expose_upstream_details(self) -> None:
        client = httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(503, text="private upstream diagnostics"))
        )
        with patch("products.posthog_ai.backend.api.terminal_ai.httpx.Client", return_value=client):
            response = self.client.post(self.url, self.body, format="json")
            body = b"".join(cast(StreamingHttpResponse, response))
        assert b"event: error" in body
        assert b"Try again" in body
        assert b"private upstream diagnostics" not in body
