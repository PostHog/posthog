import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import litellm
import pytest
import respx
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from llm_gateway.litellm_passthrough import caller_anthropic_beta, install
from llm_gateway.streaming.sse import format_sse_stream

UNKNOWN_BETA = "future-feature-2099-01-01"
SAFEGUARDS = [{"type": "tool_use_review", "classifier_context": "ctx"}]
SAFEGUARD_RESULTS = [{"type": "tool_use_review", "verdict": "allow"}]
MESSAGE = {
    "id": "msg_1",
    "type": "message",
    "role": "assistant",
    "model": "claude-opus-4-8",
    "content": [{"type": "text", "text": "hi"}],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 1, "output_tokens": 1},
}
SSE = (
    b'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_1","type":"message",'
    b'"role":"assistant","model":"claude-opus-4-8","content":[],"usage":{"input_tokens":1,"output_tokens":0}}}\n\n'
    b'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn",'
    b'"safeguard_results":[{"type":"tool_use_review","verdict":"allow"}]},"usage":{"output_tokens":1}}\n\n'
    b'event: message_stop\ndata: {"type":"message_stop"}\n\n'
)


class TestCallerAnthropicBeta:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            pytest.param([], None, id="absent"),
            pytest.param([("anthropic-beta", " , ")], None, id="blank"),
            pytest.param([("anthropic-beta", "a, b")], "a,b", id="single_line"),
            pytest.param([("anthropic-beta", "a"), ("anthropic-beta", "b,c")], "a,b,c", id="repeated_lines"),
        ],
    )
    def test_joins_values(self, raw: list[tuple[str, str]], expected: str | None) -> None:
        headers = Headers(raw=[(k.encode(), v.encode()) for k, v in raw])
        assert caller_anthropic_beta(headers) == expected


class TestLitellmWire:
    @pytest.fixture
    def upstream(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[respx.MockRouter]:
        install()
        monkeypatch.setattr(litellm, "disable_aiohttp_transport", True)
        litellm.in_memory_llm_clients_cache.flush_cache()
        with respx.mock(assert_all_called=False) as router:
            router.get(url__startswith="https://raw.githubusercontent.com").mock(return_value=httpx.Response(404))
            yield router
        litellm.in_memory_llm_clients_cache.flush_cache()

    async def test_unknown_beta_and_safeguards_reach_anthropic(self, upstream: respx.MockRouter) -> None:
        route = upstream.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(200, json={**MESSAGE, "safeguard_results": SAFEGUARD_RESULTS})
        )

        response = await litellm.anthropic_messages(
            model="anthropic/claude-opus-4-8",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=10,
            api_key="test-key",
            safeguards=SAFEGUARDS,
            extra_headers={"anthropic-beta": UNKNOWN_BETA},
        )

        sent = route.calls.last.request
        assert UNKNOWN_BETA in sent.headers["anthropic-beta"].split(",")
        assert json.loads(sent.content)["safeguards"] == SAFEGUARDS
        assert dict(response)["safeguard_results"] == SAFEGUARD_RESULTS

    async def test_stream_returns_upstream_bytes_unchanged(self, upstream: respx.MockRouter) -> None:
        upstream.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(200, content=SSE, headers={"content-type": "text/event-stream"})
        )

        stream = await litellm.anthropic_messages(
            model="anthropic/claude-opus-4-8",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=10,
            api_key="test-key",
            stream=True,
        )

        assert b"".join([chunk async for chunk in format_sse_stream(stream)]) == SSE


class TestEndpointForwarding:
    @pytest.fixture
    def body(self) -> dict[str, Any]:
        return {
            "model": "claude-opus-4-8",
            "messages": [{"role": "user", "content": "hi"}],
            "safeguards": SAFEGUARDS,
        }

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_direct_leg_forwards_beta_and_safeguards(
        self, mock_anthropic: MagicMock, authenticated_client: TestClient, body: dict[str, Any]
    ) -> None:
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=MESSAGE)
        mock_anthropic.return_value = mock_response

        response = authenticated_client.post(
            "/v1/messages",
            json=body,
            headers=[
                ("Authorization", "Bearer phx_test_key"),
                ("anthropic-beta", "context-management-2025-06-27"),
                ("anthropic-beta", UNKNOWN_BETA),
            ],
        )

        assert response.status_code == 200
        kwargs = mock_anthropic.call_args.kwargs
        assert kwargs["extra_headers"] == {"anthropic-beta": f"context-management-2025-06-27,{UNKNOWN_BETA}"}
        assert kwargs["safeguards"] == SAFEGUARDS

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_direct_leg_without_beta_sets_no_extra_headers(
        self, mock_anthropic: MagicMock, authenticated_client: TestClient, body: dict[str, Any]
    ) -> None:
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=MESSAGE)
        mock_anthropic.return_value = mock_response

        response = authenticated_client.post(
            "/v1/messages", json=body, headers={"Authorization": "Bearer phx_test_key"}
        )

        assert response.status_code == 200
        assert "extra_headers" not in mock_anthropic.call_args.kwargs

    @pytest.mark.parametrize(
        "route_patch,sender_patch",
        [
            pytest.param(
                "llm_gateway.api.anthropic.is_inference_routed_model",
                "llm_gateway.api.anthropic.send_inference_anthropic_messages",
                id="inference",
            ),
            pytest.param(
                "llm_gateway.api.anthropic.is_modal_served_model",
                "llm_gateway.api.anthropic.send_modal_anthropic_messages",
                id="modal",
            ),
        ],
    )
    def test_non_anthropic_legs_drop_safeguards(
        self, route_patch: str, sender_patch: str, authenticated_client: TestClient, body: dict[str, Any]
    ) -> None:
        with (
            patch(route_patch, return_value=True),
            patch(sender_patch, new_callable=AsyncMock, return_value=MESSAGE) as sender,
        ):
            response = authenticated_client.post(
                "/v1/messages",
                json=body,
                headers={"Authorization": "Bearer phx_test_key", "anthropic-beta": UNKNOWN_BETA},
            )

        assert response.status_code == 200
        sent = sender.call_args.args[0]
        assert "safeguards" not in sent
        assert sent["messages"] == body["messages"]

    @patch("llm_gateway.api.anthropic.get_settings")
    @patch("llm_gateway.api.anthropic.httpx.AsyncClient")
    def test_count_tokens_forwards_beta(
        self,
        mock_httpx_client_cls: MagicMock,
        mock_get_settings: MagicMock,
        authenticated_client: TestClient,
        body: dict[str, Any],
    ) -> None:
        mock_get_settings.return_value = MagicMock(anthropic_api_key="test-anthropic-key", request_timeout=300.0)
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=httpx.Response(200, json={"input_tokens": 3}))
        mock_httpx_client_cls.return_value = mock_client

        response = authenticated_client.post(
            "/v1/messages/count_tokens",
            json=body,
            headers={"Authorization": "Bearer phx_test_key", "anthropic-beta": UNKNOWN_BETA},
        )

        assert response.status_code == 200
        call = mock_client.post.call_args
        assert call.kwargs["headers"]["anthropic-beta"] == UNKNOWN_BETA
        assert call.kwargs["json"]["safeguards"] == SAFEGUARDS
