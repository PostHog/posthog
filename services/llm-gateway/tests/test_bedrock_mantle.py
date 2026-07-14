import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import litellm
import pytest

from llm_gateway.bedrock_mantle import (
    BedrockMantleMessages,
    MantleAPIError,
    MantleStreamAccumulator,
)
from llm_gateway.callbacks.base import InstrumentedCallback
from llm_gateway.rate_limiting.model_cost_overrides import MODEL_COST_OVERRIDES
from llm_gateway.streaming.sse import format_sse_stream

FABLE_COST = MODEL_COST_OVERRIDES["claude-fable-5"]


def _sse(event: dict[str, Any]) -> bytes:
    return f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode()


_STREAM_CHUNKS = [
    _sse(
        {
            "type": "message_start",
            "message": {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-fable-5",
                "usage": {
                    "input_tokens": 3,
                    "cache_read_input_tokens": 100,
                    "cache_creation_input_tokens": 10,
                    "output_tokens": 1,
                },
            },
        }
    ),
    _sse({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
    _sse({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hel"}}),
    _sse({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "lo"}}),
    _sse({"type": "content_block_stop", "index": 0}),
    _sse({"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 7}}),
    _sse({"type": "message_stop"}),
]


class _FakeStreamResponse:
    def __init__(self, status_code: int, chunks: list[bytes] | None = None, body: bytes = b"") -> None:
        self.status_code = status_code
        self._chunks = chunks or []
        self._body = body
        self.closed = False

    async def aiter_bytes(self) -> Any:
        for chunk in self._chunks:
            yield chunk

    async def aread(self) -> bytes:
        return self._body

    async def aclose(self) -> None:
        self.closed = True


def _fake_client(response: _FakeStreamResponse) -> MagicMock:
    client = MagicMock()
    client.build_request = MagicMock(return_value=MagicMock())
    client.send = AsyncMock(return_value=response)
    return client


class _CaptureCallback(InstrumentedCallback):
    callback_name = "capture"

    def __init__(self) -> None:
        super().__init__()
        self.success_kwargs: list[dict[str, Any]] = []
        self.failure_kwargs: list[dict[str, Any]] = []

    async def _on_success(
        self, kwargs: dict[str, Any], response_obj: Any, start_time: float, end_time: float, end_user_id: str | None
    ) -> None:
        self.success_kwargs.append(kwargs)

    async def _on_failure(
        self, kwargs: dict[str, Any], response_obj: Any, start_time: float, end_time: float, end_user_id: str | None
    ) -> None:
        self.failure_kwargs.append(kwargs)


def _mantle_call() -> BedrockMantleMessages:
    return BedrockMantleMessages(
        region_name="us-east-1",
        project_id="proj_test123",
        attribution_model="claude-fable-5",
    )


class TestBedrockMantleMessages:
    @pytest.mark.asyncio
    @patch("llm_gateway.bedrock_mantle.get_mantle_http_client")
    @patch("llm_gateway.bedrock_mantle._sign_bedrock_mantle_request")
    async def test_non_streaming_posts_signed_payload_with_project_header(
        self,
        mock_sign: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        mock_sign.return_value = {"Authorization": "signed", "anthropic-version": "2023-06-01"}
        message = {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hi"}],
            "usage": {"input_tokens": 3, "output_tokens": 2},
        }
        response = _FakeStreamResponse(200, body=json.dumps(message).encode())
        client = _fake_client(response)
        mock_get_client.return_value = client

        with patch.object(litellm, "callbacks", []):
            result = await _mantle_call().acreate(
                model="anthropic.claude-fable-5",
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=64,
                anthropic_beta=["beta-1", "beta-2"],
                anthropic_version="2023-06-01",
            )

        assert result == message
        signed_url = mock_sign.call_args.args[0]
        assert signed_url == "https://bedrock-mantle.us-east-1.api.aws/anthropic/v1/messages"
        # The project header must be part of the signature — dropping it lands the request on
        # the account-default project, where fable 400s on the data-retention gate.
        extra_headers = mock_sign.call_args.kwargs["extra_headers"]
        assert extra_headers["OpenAI-Project"] == "proj_test123"
        assert extra_headers["anthropic-beta"] == "beta-1,beta-2"
        signed_body = json.loads(mock_sign.call_args.args[1])
        assert signed_body["model"] == "anthropic.claude-fable-5"
        # The native surface takes the version as a header, not a body field.
        assert "anthropic_version" not in signed_body
        assert "anthropic_beta" not in signed_body
        # The same signed payload bytes are what gets sent.
        assert client.build_request.call_args.kwargs["content"] == mock_sign.call_args.args[1]
        assert client.build_request.call_args.kwargs["headers"] == mock_sign.return_value

    @pytest.mark.asyncio
    @patch("llm_gateway.bedrock_mantle.get_mantle_http_client")
    @patch("llm_gateway.bedrock_mantle._sign_bedrock_mantle_request")
    async def test_streaming_passes_raw_sse_bytes_through_unmodified(
        self,
        mock_sign: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        mock_sign.return_value = {"Authorization": "signed"}
        response = _FakeStreamResponse(200, chunks=list(_STREAM_CHUNKS))
        mock_get_client.return_value = _fake_client(response)

        with patch.object(litellm, "callbacks", []):
            stream = await _mantle_call().acreate(
                model="anthropic.claude-fable-5",
                messages=[{"role": "user", "content": "Hello"}],
                stream=True,
            )
            emitted = [chunk async for chunk in format_sse_stream(stream)]

        # Mantle speaks native Anthropic SSE: the gateway must re-emit it byte-for-byte —
        # no re-serialization and no OpenAI-style "data: [DONE]" appended.
        assert emitted == _STREAM_CHUNKS
        assert response.closed

    @pytest.mark.asyncio
    @patch("llm_gateway.bedrock_mantle.get_mantle_http_client")
    @patch("llm_gateway.bedrock_mantle._sign_bedrock_mantle_request")
    async def test_streaming_emits_callback_attribution_with_usage_and_cost(
        self,
        mock_sign: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        mock_sign.return_value = {"Authorization": "signed"}
        response = _FakeStreamResponse(200, chunks=list(_STREAM_CHUNKS))
        mock_get_client.return_value = _fake_client(response)
        capture = _CaptureCallback()

        with (
            patch.object(litellm, "callbacks", [capture]),
            patch.object(litellm, "model_cost", {"claude-fable-5": dict(FABLE_COST)}),
        ):
            stream = await _mantle_call().acreate(
                model="anthropic.claude-fable-5",
                messages=[{"role": "user", "content": "Hello"}],
                stream=True,
                metadata={"user_id": "trace-1"},
            )
            async for _ in stream:
                pass

        assert len(capture.success_kwargs) == 1
        kwargs = capture.success_kwargs[0]
        slo = kwargs["standard_logging_object"]
        assert slo["model"] == "claude-fable-5"
        assert slo["custom_llm_provider"] == "bedrock"
        assert slo["stream"] is True
        # litellm convention: prompt_tokens is the cache-inclusive total (3 + 100 + 10).
        assert slo["prompt_tokens"] == 113
        # message_delta usage is a running total — last-seen wins, not a sum.
        assert slo["completion_tokens"] == 7
        assert slo["metadata"]["usage_object"] == {
            "cache_read_input_tokens": 100,
            "cache_creation_input_tokens": 10,
        }
        expected_cost = (
            3 * FABLE_COST["input_cost_per_token"]
            + 7 * FABLE_COST["output_cost_per_token"]
            + 100 * FABLE_COST["cache_read_input_token_cost"]
            + 10 * FABLE_COST["cache_creation_input_token_cost"]
        )
        assert slo["response_cost"] == pytest.approx(expected_cost)
        assert slo["cost_breakdown"]["cache_read_cost"] == pytest.approx(
            100 * FABLE_COST["cache_read_input_token_cost"]
        )
        assert slo["response"]["content"] == [{"type": "text", "text": "Hello"}]
        assert slo["response"]["stop_reason"] == "end_turn"
        assert kwargs["litellm_params"]["metadata"] == {"user_id": "trace-1"}

    @pytest.mark.asyncio
    @patch("llm_gateway.bedrock_mantle.get_mantle_http_client")
    @patch("llm_gateway.bedrock_mantle._sign_bedrock_mantle_request")
    async def test_error_response_raises_mantle_api_error_with_status_and_type(
        self,
        mock_sign: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        mock_sign.return_value = {"Authorization": "signed"}
        error_body = {
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "data retention mode 'default' is not available for this model",
            },
        }
        response = _FakeStreamResponse(400, body=json.dumps(error_body).encode())
        mock_get_client.return_value = _fake_client(response)
        capture = _CaptureCallback()

        with patch.object(litellm, "callbacks", [capture]), pytest.raises(MantleAPIError) as exc_info:
            await _mantle_call().acreate(
                model="anthropic.claude-fable-5",
                messages=[{"role": "user", "content": "Hello"}],
            )

        # handle_llm_request's error mapping reads exactly these attributes to build the
        # client-facing error, so the upstream status/type must survive verbatim.
        assert exc_info.value.status_code == 400
        assert exc_info.value.type == "invalid_request_error"
        assert "data retention mode" in exc_info.value.message
        assert len(capture.failure_kwargs) == 1
        failure_slo = capture.failure_kwargs[0]["standard_logging_object"]
        assert failure_slo["custom_llm_provider"] == "bedrock"
        assert "data retention mode" in failure_slo["error_str"]


class TestMantleStreamAccumulator:
    def test_reconstructs_tool_use_and_running_output_tokens_across_chunk_boundaries(self) -> None:
        events = [
            {
                "type": "message_start",
                "message": {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-fable-5",
                    "usage": {"input_tokens": 5, "output_tokens": 1},
                },
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "tool_use", "id": "tu_1", "name": "get_weather"},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": '{"city": "S'},
            },
            {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": 'F"}'}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {}, "usage": {"output_tokens": 5}},
            {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 9}},
        ]
        raw = b"".join(_sse(event) for event in events)
        accumulator = MantleStreamAccumulator()
        # Split mid-line so the accumulator has to buffer partial SSE lines across feeds.
        split_at = raw.index(b"input_json_delta") + 5
        accumulator.feed(raw[:split_at])
        accumulator.feed(raw[split_at:])

        assert accumulator.usage["output_tokens"] == 9
        message = accumulator.response_message()
        assert message is not None
        assert message["stop_reason"] == "tool_use"
        assert message["content"] == [
            {"type": "tool_use", "id": "tu_1", "name": "get_weather", "input": {"city": "SF"}}
        ]

    def test_parse_failure_degrades_without_breaking_feed(self) -> None:
        accumulator = MantleStreamAccumulator()
        accumulator.feed(_sse({"type": "message_start", "message": {"usage": {"input_tokens": 2}}}))
        accumulator.feed(b"data: {not json\n\n")
        accumulator.feed(_sse({"type": "message_delta", "delta": {}, "usage": {"output_tokens": 4}}))

        # Everything captured before the malformed line is kept; later events are skipped
        # rather than raising into the byte passthrough.
        assert accumulator.saw_message_start
        assert accumulator.usage == {"input_tokens": 2}
