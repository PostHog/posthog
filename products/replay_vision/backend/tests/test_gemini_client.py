import gc
import json
import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

import httpx
from google.genai import (
    errors as genai_errors,
    types,
)

from products.replay_vision.backend.gemini_client import (
    GATEWAY_FLAG,
    GatewayGeminiClient,
    _send_before,
    _with_headers,
    assemble_stream,
    replay_gateway_client,
)
from products.replay_vision.backend.temporal import pii_check
from products.replay_vision.backend.temporal.errors import FailureKind
from products.replay_vision.backend.temporal.gemini import classify_gemini_error, describe_gemini_error

_GATEWAY = {
    "AI_GATEWAY_URL": "https://ai-gateway.example/v1",
    "AI_GATEWAY_API_KEY": "phs_shared",
    "REPLAY_VISION_AI_GATEWAY_API_KEY": "phs_replay_vision",
    "REPLAY_VISION_GEMINI_API_KEY": "replay-vision-google-key",
}
_OK = {"candidates": [{"content": {"role": "model", "parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}
_FLAG = "products.replay_vision.backend.gemini_client.feature_enabled_or_false"


@pytest.fixture(autouse=True)
def flag_on() -> Any:
    with patch(_FLAG, return_value=True) as flag:
        yield flag


def _sse(*chunks: dict[str, Any]) -> bytes:
    return b"".join(b"data: " + json.dumps(chunk).encode() + b"\r\n\r\n" for chunk in chunks)


def _ok(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith(":streamGenerateContent"):
        return httpx.Response(200, content=_sse(_OK), headers={"content-type": "text/event-stream"})
    return httpx.Response(200, json=_OK)


def _gateway_client(properties: dict[str, Any] | None = None) -> GatewayGeminiClient:
    with override_settings(**_GATEWAY):
        client = replay_gateway_client(42, properties=properties)
    assert isinstance(client, GatewayGeminiClient)
    return client


def _wired_gateway_client(
    properties: dict[str, Any], respond: Callable[[httpx.Request], httpx.Response] = _ok
) -> tuple[GatewayGeminiClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return respond(request)

    client = _gateway_client(properties)
    # Swaps only the transport, so a client the SDK has closed still fails the call.
    api_client = client._client._api_client
    api_client._httpx_client._transport = httpx.MockTransport(handler)
    api_client._async_httpx_client._transport = httpx.MockTransport(handler)
    return client, seen


class TestReplayGatewayClient:
    @pytest.mark.parametrize(
        "unset", ["REPLAY_VISION_AI_GATEWAY_API_KEY", "REPLAY_VISION_GEMINI_API_KEY"], ids=["gateway-key", "google-key"]
    )
    def test_a_missing_key_stays_direct_without_the_flag(self, flag_on: MagicMock, unset: str) -> None:
        with (
            override_settings(**{**_GATEWAY, unset: ""}),
            patch("posthog.llm.gateway_client.genai.Client") as gateway_client,
            patch("posthog.llm.gateway_client.logger") as gateway_logger,
        ):
            assert replay_gateway_client(42) is None
        flag_on.assert_not_called()
        gateway_client.assert_not_called()
        gateway_logger.warning.assert_not_called()

    def test_flag_off_stays_direct(self, flag_on: MagicMock) -> None:
        flag_on.return_value = False
        with override_settings(**_GATEWAY), patch("posthog.llm.gateway_client.genai.Client") as gateway_client:
            assert replay_gateway_client(42) is None
        gateway_client.assert_not_called()

    def test_flag_is_evaluated_locally_per_project_without_events(self, flag_on: MagicMock) -> None:
        _gateway_client()
        flag_on.assert_called_once_with(
            GATEWAY_FLAG,
            "team-42",
            groups={"project": "42"},
            group_properties={"project": {"id": "42"}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )

    def test_replay_vision_calls_use_its_own_key_never_the_shared_one(self) -> None:
        with override_settings(**_GATEWAY), patch("posthog.llm.gateway_client.genai.Client") as gateway_client:
            assert replay_gateway_client(42) is not None
        assert gateway_client.call_args.kwargs["api_key"] == "phs_replay_vision"

    def test_per_call_capture_kwargs_become_request_headers(self) -> None:
        client, seen = _wired_gateway_client({"feature": "scanner", "team_id": 42})

        asyncio.run(
            client.aio.models.generate_content(
                model="models/gemini-test",
                contents=[types.Part.from_bytes(data=b"mp4", mime_type="video/mp4"), "hi"],
                config=types.GenerateContentConfig(temperature=0.2),
                posthog_distinct_id="user-1",
                posthog_trace_id="trace-1",
                posthog_properties={"$ai_span_name": "core", "feature": "override"},
                posthog_groups={"project": "42"},
            )
        )

        request = seen[0]
        assert str(request.url).startswith("https://ai-gateway.example/v1beta/models/gemini-test:streamGenerateContent")
        assert request.headers["x-goog-api-key"] == "phs_replay_vision"
        assert request.headers["x-posthog-trace-id"] == "trace-1"
        assert request.headers["x-posthog-distinct-id"] == "user-1"
        assert request.headers["x-posthog-privacy-mode"] == "true"
        assert json.loads(request.headers["x-posthog-properties"]) == {
            "feature": "override",
            "team_id": "42",
            "span_name": "core",
            "ai_product": "replay_vision",
        }
        body = json.loads(request.content)
        assert body["contents"][0]["parts"][0]["inlineData"]["mimeType"] == "video/mp4"
        assert "httpOptions" not in body and "http_options" not in body

    def test_the_sdk_client_outlives_the_wrapper(self) -> None:
        async def call_after_collection() -> list[httpx.Request]:
            # Built inside a running loop, as the scan activity does: only there does the SDK close its async transport.
            client, seen = _wired_gateway_client({"feature": "scanner"})
            aio = client.aio
            del client
            gc.collect()
            await asyncio.sleep(0)
            await aio.models.generate_content(model="gemini-test", contents="hi")
            await aio.aclose()
            return seen

        assert len(asyncio.run(call_after_collection())) == 1

    @pytest.mark.parametrize("code", [400, 401, 402, 403, 404])
    def test_the_gateways_own_refusal_is_ours_and_retryable(self, code: int) -> None:
        body = {
            "error": {
                "code": code,
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "x", "domain": "posthog.com"}
                ],
            }
        }
        client, _ = _wired_gateway_client({}, respond=lambda _: httpx.Response(code, json=body))

        with pytest.raises(genai_errors.ClientError) as exc_info:
            asyncio.run(client.aio.models.generate_content(model="gemini-test", contents="hi"))

        assert classify_gemini_error(exc_info.value) == FailureKind.INFRA_TRANSIENT
        assert describe_gemini_error(exc_info.value).startswith("PostHog's AI gateway returned HTTP")

    @pytest.mark.parametrize("code", [400, 401, 403, 404])
    def test_a_refusal_google_wrote_stays_a_rejection(self, code: int) -> None:
        body = {
            "error": {
                "code": code,
                "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "domain": "googleapis.com"}],
            }
        }
        client, _ = _wired_gateway_client({}, respond=lambda _: httpx.Response(code, json=body))

        with pytest.raises(genai_errors.ClientError) as exc_info:
            asyncio.run(client.aio.models.generate_content(model="gemini-test", contents="hi"))

        kind = classify_gemini_error(exc_info.value)
        assert kind == FailureKind.PROVIDER_REJECTED
        assert kind is not None and not kind.is_retryable
        assert describe_gemini_error(exc_info.value).startswith("The AI provider returned HTTP")

    def test_request_headers_keep_the_callers_other_http_options(self) -> None:
        config = types.GenerateContentConfig(http_options=types.HttpOptions(timeout=5000, headers={"a": "1"}))
        merged = _with_headers(config, {"b": "2"})
        assert merged is not None and merged.http_options is not None
        assert merged.http_options.timeout == 5000
        assert merged.http_options.headers == {"a": "1", "b": "2"}


def test_pii_rewrite_uses_the_gateway_when_configured_and_closes_it() -> None:
    with (
        override_settings(**_GATEWAY),
        patch("posthog.llm.gateway_client.genai.Client") as gateway_client,
        patch.object(pii_check.genai, "AsyncClient") as direct_client,
    ):
        sdk = gateway_client.return_value
        sdk.aio.models.generate_content_stream = AsyncMock(side_effect=RuntimeError("stop"))
        sdk.aio.aclose = AsyncMock()
        with pytest.raises(RuntimeError):
            asyncio.run(pii_check.rewrite_without_pii(team_id=1, question="q", text={"a": "b"}, trace_id="t"))

    direct_client.assert_not_called()
    request_headers = sdk.aio.models.generate_content_stream.call_args.kwargs["config"].http_options.headers
    labels = json.loads(request_headers["X-PostHog-Properties"])
    assert (labels["feature"], labels["span_name"]) == ("pii_rewrite", "pii_rewrite")
    sdk.close.assert_called_once()
    sdk.aio.aclose.assert_awaited_once()


def test_a_stream_assembles_into_the_buffered_response() -> None:
    chunks: list[dict[str, Any]] = [
        {"candidates": [{"content": {"role": "model", "parts": [{"text": "Hel"}]}}]},
        {"candidates": [{"content": {"role": "model", "parts": [{"text": "lo"}]}}]},
        {
            "candidates": [{"content": {"role": "model", "parts": [{"text": ""}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2},
        },
    ]

    client, _ = _wired_gateway_client(
        {"feature": "scanner"},
        respond=lambda _: httpx.Response(200, content=_sse(*chunks), headers={"content-type": "text/event-stream"}),
    )

    response = asyncio.run(client.aio.models.generate_content(model="gemini-test", contents="hi"))

    assert response.text == "Hello"
    assert response.candidates is not None
    assert response.candidates[0].finish_reason == types.FinishReason.STOP
    assert response.usage_metadata is not None and response.usage_metadata.candidates_token_count == 2
    content = response.candidates[0].content
    assert content is not None and content.parts is not None and len(content.parts) == 1


def _chunk(*parts: types.Part, finish: types.FinishReason | None = None) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)), finish_reason=finish)]
    )


class TestAssembleStream:
    def test_function_calls_and_thought_signatures_survive_unmerged(self) -> None:
        call = types.Part(function_call=types.FunctionCall(name="get_events", args={"n": 1}), thought_signature=b"sig")
        response = assemble_stream(
            [
                _chunk(types.Part(text="plan", thought=True)),
                _chunk(types.Part(text="ning", thought=True)),
                _chunk(call),
                _chunk(types.Part(text="done", thought_signature=b"sig2"), finish=types.FinishReason.STOP),
            ]
        )

        assert response.candidates is not None and response.candidates[0].content is not None
        parts = response.candidates[0].content.parts
        assert parts is not None
        assert [p.text for p in parts] == ["planning", None, "done"]
        assert parts[0].thought is True
        assert parts[1].function_call is not None and parts[1].thought_signature == b"sig"
        assert parts[2].thought_signature == b"sig2"
        assert response.function_calls is not None and response.function_calls[0].name == "get_events"
        assert response.candidates[0].finish_reason == types.FinishReason.STOP

    def test_a_signed_text_part_is_never_merged(self) -> None:
        response = assemble_stream(
            [
                _chunk(types.Part(text="a")),
                _chunk(types.Part(text="b", thought_signature=b"sig")),
                _chunk(types.Part(text="c"), finish=types.FinishReason.STOP),
            ]
        )

        assert response.candidates is not None and response.candidates[0].content is not None
        parts = response.candidates[0].content.parts
        assert parts is not None
        assert [(p.text, p.thought_signature) for p in parts] == [("a", None), ("b", b"sig"), ("c", None)]

    def test_thought_text_does_not_merge_into_answer_text(self) -> None:
        response = assemble_stream(
            [
                _chunk(types.Part(text="think", thought=True)),
                _chunk(types.Part(text="answer"), finish=types.FinishReason.STOP),
            ]
        )

        assert response.candidates is not None and response.candidates[0].content is not None
        parts = response.candidates[0].content.parts
        assert parts is not None and len(parts) == 2
        assert response.text == "answer"

    def test_a_blocked_prompt_keeps_its_feedback(self) -> None:
        blocked = types.GenerateContentResponse(
            prompt_feedback=types.GenerateContentResponsePromptFeedback(block_reason=types.BlockedReason.SAFETY)
        )

        response = assemble_stream([blocked])

        assert not response.candidates
        assert response.prompt_feedback is not None
        assert response.prompt_feedback.block_reason == types.BlockedReason.SAFETY

    @pytest.mark.parametrize(
        "chunks",
        [
            [],
            [_chunk(types.Part(text='{"verdict": "ye'))],
            [
                types.GenerateContentResponse(
                    usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=3)
                )
            ],
        ],
        ids=["empty", "cut-after-text", "usage-only"],
    )
    def test_a_stream_without_a_finish_reason_raises_a_transient_error(
        self, chunks: list[types.GenerateContentResponse]
    ) -> None:
        with pytest.raises(genai_errors.ServerError) as exc_info:
            assemble_stream(chunks)

        assert exc_info.value.code == 503
        assert classify_gemini_error(exc_info.value) == FailureKind.PROVIDER_TRANSIENT


_ERROR_FRAME = {"error": {"code": 503, "message": "upstream idle", "status": "UNAVAILABLE"}}
_PARTIAL = {"candidates": [{"content": {"role": "model", "parts": [{"text": '{"verdict": "ye'}]}}]}


@pytest.mark.parametrize(
    "body",
    [_sse(_PARTIAL, _ERROR_FRAME), _sse(_ERROR_FRAME), _sse(_PARTIAL)],
    ids=["partial-then-error", "error-only", "clean-close-mid-answer"],
)
def test_a_cut_gateway_stream_raises(body: bytes) -> None:
    client, _ = _wired_gateway_client(
        {"feature": "scanner"},
        respond=lambda _: httpx.Response(200, content=body, headers={"content-type": "text/event-stream"}),
    )

    with pytest.raises(genai_errors.ServerError):
        asyncio.run(client.aio.models.generate_content(model="gemini-test", contents="hi"))


class TestGatewayFilesAndCaches:
    def test_aclose_closes_both_transports(self) -> None:
        client, _ = _wired_gateway_client({})
        api_client = client._client._api_client
        asyncio.run(client.aclose())
        assert api_client._httpx_client.is_closed
        assert api_client._async_httpx_client.is_closed

    def test_file_get_reads_through_the_gateway(self) -> None:
        file_json = {
            "name": "files/abc",
            "state": "ACTIVE",
            "uri": "https://generativelanguage.googleapis.com/v1beta/files/abc",
        }
        client, seen = _wired_gateway_client({}, respond=lambda _: httpx.Response(200, json=file_json))
        got = client.files.get(name="files/abc")
        assert got.state is not None and got.state.name == "ACTIVE"
        assert seen[-1].url.path == "/v1beta/files/abc"
        assert seen[-1].headers["x-goog-api-key"] == "phs_replay_vision"

    def test_upload_posts_the_raw_file_to_the_gateway_upload_route(self) -> None:
        client = _gateway_client()
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"file": {"name": "files/abc", "state": "PROCESSING"}})

        real_client = httpx.Client
        client_kwargs: dict[str, Any] = {}

        def wired(**kw: Any) -> httpx.Client:
            client_kwargs.update(kw)
            return real_client(transport=httpx.MockTransport(handler), **kw)

        with patch("products.replay_vision.backend.gemini_client.httpx.Client", wired):
            uploaded = client.upload_file(b"mp4-bytes", mime_type="video/mp4", display_name="wf-1")

        assert uploaded.name == "files/abc"
        request = seen[0]
        assert request.url == "https://ai-gateway.example/v1beta/files:upload"
        assert request.read() == b"mp4-bytes"
        assert request.headers["x-goog-api-key"] == "phs_replay_vision"
        assert request.headers["content-type"] == "video/mp4"
        assert request.headers["content-length"] == str(len(b"mp4-bytes"))
        assert "transfer-encoding" not in request.headers
        assert request.headers["x-goog-upload-display-name"] == "wf-1"
        assert client_kwargs["trust_env"] is False
        timeout = client_kwargs["timeout"]
        assert timeout.connect == 10.0 and timeout.read == 60.0 and timeout.write == 60.0

    def test_upload_and_processing_wait_fit_the_activity_timeout(self) -> None:
        from products.replay_vision.backend import gemini_client
        from products.replay_vision.backend.temporal.activities import upload_video_to_gemini

        t = gemini_client._UPLOAD_TIMEOUT
        assert t.connect is not None and t.write is not None and t.read is not None
        upload = t.connect + gemini_client._UPLOAD_SEND_DEADLINE_S + t.write + t.read
        wait = upload_video_to_gemini._MAX_PROCESSING_WAIT_SECONDS + upload_video_to_gemini._POLL_MAX_SECONDS
        assert upload + wait < 600

    def test_upload_stops_sending_at_its_deadline(self) -> None:
        clock = iter([0.0, 1.0, 1000.0])
        with patch("products.replay_vision.backend.gemini_client.time.monotonic", lambda: next(clock)):
            chunks = _send_before(b"x" * (3 << 20), deadline=180.0)
            assert len(next(chunks)) == 1 << 20
            assert len(next(chunks)) == 1 << 20
            with pytest.raises(httpx.WriteTimeout):
                next(chunks)
        assert classify_gemini_error(httpx.WriteTimeout("deadline")) == FailureKind.PROVIDER_TRANSIENT

    def test_upload_sends_through_its_deadline(self) -> None:
        client = _gateway_client()
        real_client = httpx.Client

        def handler(request: httpx.Request) -> httpx.Response:
            request.read()
            return httpx.Response(200, json={"file": {"name": "files/abc"}})

        clock = iter([0.0, 1.0, 1000.0])
        with (
            patch(
                "products.replay_vision.backend.gemini_client.httpx.Client",
                lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
            ),
            patch("products.replay_vision.backend.gemini_client.time.monotonic", lambda: next(clock)),
            pytest.raises(httpx.WriteTimeout) as exc_info,
        ):
            client.upload_file(b"x" * (2 << 20), mime_type="video/mp4", display_name="wf-1")
        assert classify_gemini_error(exc_info.value) == FailureKind.PROVIDER_TRANSIENT

    def test_upload_raises_the_gateways_status(self) -> None:
        client = _gateway_client()
        real_client = httpx.Client
        transport = httpx.MockTransport(lambda _: httpx.Response(402, json={"error": {"code": 402}}))
        with (
            patch(
                "products.replay_vision.backend.gemini_client.httpx.Client",
                lambda **kw: real_client(transport=transport, **kw),
            ),
            pytest.raises(genai_errors.ClientError) as exc_info,
        ):
            client.upload_file(b"x", mime_type="video/mp4", display_name="wf-1")
        assert exc_info.value.code == 402
