import json
from collections.abc import Callable, Iterator
from typing import cast

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.http import StreamingHttpResponse
from django.test import override_settings

import httpx
from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.models import Organization, PersonalAPIKey, Team
from posthog.models.utils import generate_random_token_personal, hash_key_value

UPSTREAM_DIAGNOSTICS = "private upstream diagnostics"


def _rejecting_handler(_: httpx.Request) -> httpx.Response:
    return httpx.Response(503, text=UPSTREAM_DIAGNOSTICS)


def _unreachable_handler(_: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError(UPSTREAM_DIAGNOSTICS)


@override_settings(AI_GATEWAY_URL="https://ai-gateway.test/v1", AI_GATEWAY_API_KEY="phs_test_only")
class TestTerminalAI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enabled = self.enterContext(
            patch("products.posthog_ai.backend.presentation.terminal_ai.feature_enabled_or_false", return_value=True)
        )
        self.limited = self.enterContext(
            patch("products.posthog_ai.backend.presentation.terminal_ai.is_team_limited", return_value=False)
        )
        self.enterContext(
            patch("products.posthog_ai.backend.presentation.terminal_ai.is_privacy_mode_enabled", return_value=True)
        )
        self.url = f"/api/projects/{self.team.id}/terminal_ai/"
        self.body = {
            "model": "claude-opus-5",
            "messages": [{"role": "user", "content": "Say hello"}],
            "max_tokens": 100,
            "stream": True,
        }

    @parameterized.expand(
        [
            ("anonymous", 401),
            ("api_key", 403),
            ("other_project", 403),
            ("flag_disabled", 403),
            ("consent_denied", 403),
            ("consent_unset", 403),
            ("quota", 402),
        ]
    )
    def test_access_denied_before_gateway_call(self, scenario: str, expected_status: int) -> None:
        if scenario == "anonymous":
            self.client.logout()
        elif scenario == "api_key":
            token = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                label="Terminal test key",
                user=self.user,
                secure_value=hash_key_value(token),
                scopes=["conversation:write"],
            )
            self.client.logout()
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        elif scenario == "other_project":
            team = Team.objects.create(organization=Organization.objects.create(name="Another organization"))
            self.url = f"/api/projects/{team.id}/terminal_ai/"
        elif scenario == "flag_disabled":
            self.enabled.return_value = False
        elif scenario in ("consent_denied", "consent_unset"):
            self.organization.is_ai_data_processing_approved = False if scenario == "consent_denied" else None
            self.organization.save(update_fields=["is_ai_data_processing_approved"])
        else:
            self.limited.return_value = True
        with patch("products.posthog_ai.backend.presentation.terminal_ai._stream_generation") as stream:
            response = self.client.post(self.url, self.body, format="json")
        assert response.status_code == expected_status
        stream.assert_not_called()

    @parameterized.expand(
        [
            ("model", "unapproved-model"),
            ("max_tokens", 100000),
            ("extra_headers", {"x-api-key": "fake"}),
            ("messages", [{"role": "user", "content": "\ud800"}]),
        ]
    )
    def test_invalid_requests_do_not_reach_gateway(self, key: str, value: object) -> None:
        with patch("products.posthog_ai.backend.presentation.terminal_ai._stream_generation") as stream:
            response = self.client.post(
                self.url, json.dumps({**self.body, key: value}), content_type="application/json"
            )
        assert response.status_code == 400
        stream.assert_not_called()

    @parameterized.expand(
        [
            ("claude-opus-5", "Say hello"),
            ("claude-sonnet-5", "Say hello"),
            ("claude-sonnet-4-6", "Say hello"),
            ("claude-haiku-4-5", "你好🌍" * 60000),
        ]
    )
    def test_stream_preserves_tool_calls_and_trusted_attribution(self, model: str, content: str) -> None:
        self.body["model"] = model
        self.body["messages"] = [{"role": "user", "content": content}]
        event = b'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"tool_1","name":"bash","input":{}}}\n\n'
        requests: list[httpx.Request] = []

        def gateway(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, content=event, headers={"Content-Type": "text/event-stream"})

        client = httpx.Client(transport=httpx.MockTransport(gateway))
        with (
            patch("products.posthog_ai.backend.presentation.terminal_ai.httpx.Client", return_value=client),
            patch("products.posthog_ai.backend.presentation.terminal_ai.is_impersonated_session", return_value=True),
        ):
            response = self.client.post(
                self.url,
                json.dumps(self.body, ensure_ascii=False),
                content_type="application/json",
                HTTP_ACCEPT="text/event-stream",
            )
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
        assert json.loads(request.content)["model"] == model
        assert json.loads(request.content)["messages"] == self.body["messages"]

    @parameterized.expand([("unicode",), ("whitespace",)])
    def test_oversized_request_does_not_reach_gateway(self, scenario: str) -> None:
        if scenario == "unicode":
            self.body["messages"] = [{"role": "user", "content": "🌍" * (256 * 1024)}]
        payload = json.dumps(self.body, ensure_ascii=False)
        if scenario == "whitespace":
            payload += " " * (1024 * 1024)
        with patch("products.posthog_ai.backend.presentation.terminal_ai._stream_generation") as stream:
            response = self.client.post(self.url, payload, content_type="application/json")
        assert response.status_code == 400
        stream.assert_not_called()

    @parameterized.expand(
        [
            ("rejected", _rejecting_handler, "terminal_ai_gateway_request_failed"),
            ("unreachable", _unreachable_handler, "terminal_ai_gateway_transport_failed"),
        ]
    )
    def test_gateway_errors_stay_private_and_are_logged(
        self, _name: str, handler: Callable[[httpx.Request], httpx.Response], event: str
    ) -> None:
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch("products.posthog_ai.backend.presentation.terminal_ai.httpx.Client", return_value=client):
            with patch("products.posthog_ai.backend.presentation.terminal_ai.logger") as logger:
                response = self.client.post(self.url, self.body, format="json")
                body = b"".join(cast(StreamingHttpResponse, response))
        assert b"event: error" in body
        assert b"Try again" in body
        assert UPSTREAM_DIAGNOSTICS.encode() not in body
        assert logger.warning.call_args[0][0] == event
        assert UPSTREAM_DIAGNOSTICS not in str(logger.warning.call_args)
        assert "phs_test_only" not in str(logger.warning.call_args)

    @override_settings(SERVER_GATEWAY_INTERFACE="ASGI")
    def test_asgi_delivers_first_chunk_before_upstream_finishes(self) -> None:
        finished = False

        def stream() -> Iterator[bytes]:
            nonlocal finished
            yield b"data: first\n\n"
            finished = True

        with patch("products.posthog_ai.backend.presentation.terminal_ai._stream_generation", return_value=stream()):
            response = cast(StreamingHttpResponse, self.client.post(self.url, self.body, format="json"))
        assert response.status_code == 200

        async def consume() -> None:
            iterator = aiter(response)
            assert await anext(iterator) == b"data: first\n\n"
            assert not finished
            with self.assertRaises(StopAsyncIteration):
                await anext(iterator)
            assert finished

        async_to_sync(consume)()
