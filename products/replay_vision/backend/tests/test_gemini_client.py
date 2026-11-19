import gc
import json
import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from unittest.mock import AsyncMock, patch

from django.test import override_settings

import httpx
from google.genai import (
    errors as genai_errors,
    types,
)

from posthog.llm.gateway_client import AIGatewayHostError

from products.replay_vision.backend.gemini_client import (
    GatewayNotConfiguredError,
    ReplayGemini,
    _AsyncGatewayModels,
    _with_headers,
    assemble_stream,
    gemini_files_client,
    gemini_text_models,
    replay_gemini_client,
)
from products.replay_vision.backend.temporal import pii_check
from products.replay_vision.backend.temporal.activities.upload_video_to_gemini import _write_and_upload
from products.replay_vision.backend.temporal.errors import FailureKind
from products.replay_vision.backend.temporal.gemini import classify_gemini_error

_GATEWAY = {"AI_GATEWAY_URL": "https://ai-gateway.example/v1", "AI_GATEWAY_API_KEY": "phs_gateway"}
_OK = {"candidates": [{"content": {"role": "model", "parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}


def _sse(*chunks: dict[str, Any]) -> bytes:
    return b"".join(b"data: " + json.dumps(chunk).encode() + b"\r\n\r\n" for chunk in chunks)


def _ok(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith(":streamGenerateContent"):
        return httpx.Response(200, content=_sse(_OK), headers={"content-type": "text/event-stream"})
    return httpx.Response(200, json=_OK)


def _gateway_client(properties: dict[str, Any] | None = None) -> ReplayGemini:
    with override_settings(**_GATEWAY):
        client = replay_gemini_client(properties=properties)
    assert isinstance(client.models, _AsyncGatewayModels)
    return client


def _wired_gateway_client(
    properties: dict[str, Any], respond: Callable[[httpx.Request], httpx.Response] = _ok
) -> tuple[ReplayGemini, list[httpx.Request]]:
    client = _gateway_client(properties)
    return client, _wire(client, respond)


def _wire(client: ReplayGemini, respond: Callable[[httpx.Request], httpx.Response] = _ok) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return respond(request)

    # Swaps only the transport, so a client the SDK has closed still fails the call.
    api_client = client.raw._api_client
    assert api_client._httpx_client is not None and api_client._async_httpx_client is not None
    api_client._httpx_client._transport = httpx.MockTransport(handler)
    api_client._async_httpx_client._transport = httpx.MockTransport(handler)
    return seen


class TestReplayGeminiClient:
    @pytest.mark.parametrize(
        "build",
        [
            lambda: replay_gemini_client(),
            lambda: gemini_text_models(timeout_ms=1000),
            gemini_files_client,
        ],
    )
    def test_an_unconfigured_gateway_fails_instead_of_calling_google(self, build: Callable[[], Any]) -> None:
        with (
            override_settings(AI_GATEWAY_URL="", AI_GATEWAY_API_KEY=""),
            patch("posthog.llm.gateway_client.genai.Client") as sdk_client,
            pytest.raises(GatewayNotConfiguredError),
        ):
            build()
        sdk_client.assert_not_called()

    def test_per_call_capture_kwargs_become_request_headers(self) -> None:
        client, seen = _wired_gateway_client({"feature": "scanner", "team_id": 42})

        asyncio.run(
            client.models.generate_content(
                model="models/gemini-test",
                contents=[types.Part.from_bytes(data=b"mp4", mime_type="video/mp4"), "hi"],
                config=types.GenerateContentConfig(temperature=0.2),
                posthog_distinct_id="user-1",
                posthog_trace_id="trace-1",
                posthog_properties={"$ai_span_name": "core", "feature": "override"},
            )
        )

        request = seen[0]
        assert str(request.url).startswith("https://ai-gateway.example/v1beta/models/gemini-test:streamGenerateContent")
        assert request.headers["x-posthog-trace-id"] == "trace-1"
        assert request.headers["x-posthog-distinct-id"] == "user-1"
        assert request.headers["x-posthog-privacy-mode"] == "true"
        assert request.headers["x-posthog-span-name"] == "core"
        assert json.loads(request.headers["x-posthog-properties"]) == {
            "feature": "override",
            "team_id": "42",
            "ai_product": "replay_vision",
        }
        body = json.loads(request.content)
        assert body["contents"][0]["parts"][0]["inlineData"]["mimeType"] == "video/mp4"
        assert "httpOptions" not in body and "http_options" not in body

    @pytest.mark.parametrize(
        "code, kind",
        [
            (401, FailureKind.INFRA_TRANSIENT),
            (402, FailureKind.INFRA_TRANSIENT),
            (403, FailureKind.INFRA_TRANSIENT),
            (408, FailureKind.INFRA_TRANSIENT),
            (409, FailureKind.INFRA_TRANSIENT),
            (429, FailureKind.INFRA_TRANSIENT),
            (400, FailureKind.INTERNAL_ERROR),
            (404, FailureKind.INTERNAL_ERROR),
            (413, FailureKind.INTERNAL_ERROR),
            (502, FailureKind.PROVIDER_TRANSIENT),
        ],
    )
    def test_the_gateways_own_refusal_is_ours_and_retries_only_when_it_can_clear(
        self, code: int, kind: FailureKind
    ) -> None:
        body = {
            "error": {
                "code": code,
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "x", "domain": "posthog.com"}
                ],
            }
        }
        client, _ = _wired_gateway_client({}, respond=lambda _: httpx.Response(code, json=body))

        with pytest.raises(genai_errors.APIError) as exc_info:
            asyncio.run(client.models.generate_content(model="gemini-test", contents="hi"))

        assert classify_gemini_error(exc_info.value) == kind

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
            asyncio.run(client.models.generate_content(model="gemini-test", contents="hi"))

        kind = classify_gemini_error(exc_info.value)
        assert kind == FailureKind.PROVIDER_REJECTED
        assert kind is not None and not kind.is_retryable

    def test_request_headers_keep_the_callers_other_http_options(self) -> None:
        config = types.GenerateContentConfig(http_options=types.HttpOptions(timeout=5000, headers={"a": "1"}))
        merged = _with_headers(config, {"b": "2"})
        assert merged is not None and merged.http_options is not None
        assert merged.http_options.timeout == 5000
        assert merged.http_options.headers == {"a": "1", "b": "2"}


def test_pii_rewrite_uses_the_gateway() -> None:
    with (
        override_settings(**_GATEWAY),
        patch("posthog.llm.gateway_client.genai.Client") as gateway_client,
    ):
        sdk = gateway_client.return_value
        sdk.aio.models.generate_content_stream = AsyncMock(side_effect=RuntimeError("stop"))
        sdk.aio.aclose = AsyncMock()
        with pytest.raises(RuntimeError):
            asyncio.run(pii_check.rewrite_without_pii(team_id=1, question="q", text={"a": "b"}, trace_id="t"))

    request_headers = sdk.aio.models.generate_content_stream.call_args.kwargs["config"].http_options.headers
    assert json.loads(request_headers["X-PostHog-Properties"])["feature"] == "pii_rewrite"
    assert request_headers["X-PostHog-Span-Name"] == "pii_rewrite"
    sdk.close.assert_called_once()
    sdk.aio.aclose.assert_awaited_once()


def test_text_models_send_the_timeout_and_capture_headers() -> None:
    with override_settings(**_GATEWAY), patch("posthog.llm.gateway_client.genai.Client") as gateway_client:
        gemini_text_models(timeout_ms=1000).generate_content(
            model="m",
            contents="c",
            posthog_trace_id="t",
            posthog_properties={"feature": "prompt_question", "team_id": 42},
        )

    assert gateway_client.call_args.kwargs["http_options"].timeout == 1000
    headers = gateway_client.return_value.models.generate_content.call_args.kwargs["config"].http_options.headers
    assert headers["X-PostHog-Trace-Id"] == "t"
    assert json.loads(headers["X-PostHog-Properties"]) == {
        "feature": "prompt_question",
        "team_id": "42",
        "ai_product": "replay_vision",
    }


def test_text_models_keep_their_client_open_between_calls() -> None:
    with override_settings(**_GATEWAY):
        models = gemini_text_models(timeout_ms=1000)
    gc.collect()
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok(request)

    http_client = models._client._api_client._httpx_client
    assert http_client is not None
    http_client._transport = httpx.MockTransport(respond)

    assert models.generate_content(model="gemini-test", contents="hi").text == "ok"
    assert models.generate_content(model="gemini-test", contents="again").text == "ok"
    assert len(seen) == 2


def _chunk(*parts: types.Part, finish: types.FinishReason | None = None) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)), finish_reason=finish)]
    )


class TestAssembleStream:
    def test_chunks_fold_into_one_response_in_order(self) -> None:
        call = types.Part(function_call=types.FunctionCall(name="get_events", args={"n": 1}), thought_signature=b"sig")
        usage = types.GenerateContentResponseUsageMetadata(prompt_token_count=3, candidates_token_count=2)
        last = _chunk(types.Part(text="lo"), finish=types.FinishReason.STOP).model_copy(
            update={"usage_metadata": usage}
        )

        response = assemble_stream(
            [_chunk(types.Part(text="think", thought=True)), _chunk(call), _chunk(types.Part(text="Hel")), last]
        )

        assert response.candidates is not None and response.candidates[0].content is not None
        parts = response.candidates[0].content.parts
        assert parts is not None
        assert [p.text for p in parts] == ["think", None, "Hel", "lo"]
        assert parts[1].thought_signature == b"sig"
        assert response.text == "Hello"
        assert response.function_calls is not None and response.function_calls[0].name == "get_events"
        assert response.candidates[0].finish_reason == types.FinishReason.STOP
        assert response.usage_metadata is not None and response.usage_metadata.candidates_token_count == 2

    def test_a_blocked_prompt_keeps_its_feedback(self) -> None:
        blocked = types.GenerateContentResponse(
            prompt_feedback=types.GenerateContentResponsePromptFeedback(block_reason=types.BlockedReason.SAFETY)
        )

        response = assemble_stream([blocked])

        assert not response.candidates
        assert response.prompt_feedback is not None
        assert response.prompt_feedback.block_reason == types.BlockedReason.SAFETY

    def test_an_empty_stream_raises_a_transient_error(self) -> None:
        with pytest.raises(genai_errors.ServerError) as exc_info:
            assemble_stream([])

        assert classify_gemini_error(exc_info.value) == FailureKind.PROVIDER_TRANSIENT


class TestGatewayFilesAndCaches:
    def test_aclose_closes_both_transports(self) -> None:
        client, _ = _wired_gateway_client({})
        api_client = client.raw._api_client
        asyncio.run(client.aclose())
        assert api_client._httpx_client is not None and api_client._httpx_client.is_closed
        assert api_client._async_httpx_client is not None and api_client._async_httpx_client.is_closed

    def test_every_call_is_tagged_replay_vision_with_the_gateway_key(self) -> None:
        def respond(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith(":streamGenerateContent"):
                return _ok(request)
            if path == "/upload/v1beta/files" and "upload_id" not in request.url.params:
                upload_url = "https://ai-gateway.example/upload/v1beta/files?upload_id=u1&upload_protocol=resumable"
                return httpx.Response(200, json={}, headers={"x-goog-upload-url": upload_url})
            if path == "/upload/v1beta/files":
                file = {"name": "files/abc", "state": "PROCESSING"}
                return httpx.Response(200, json={"file": file}, headers={"x-goog-upload-status": "final"})
            if path.startswith("/v1beta/cachedContents"):
                return httpx.Response(200, json={"name": "cachedContents/c1"} if request.method == "POST" else {})
            return httpx.Response(200, json={"name": "files/abc", "state": "ACTIVE"} if request.method == "GET" else {})

        client, seen = _wired_gateway_client({"feature": "scanner"}, respond)

        async def calls() -> None:
            await client.models.generate_content(model="gemini-test", contents="hi")
            await client.raw.aio.caches.create(
                model="gemini-test", config=types.CreateCachedContentConfig(contents=[types.Part(text="video")])
            )
            await client.raw.aio.caches.delete(name="cachedContents/c1")

        asyncio.run(calls())
        uploaded = _write_and_upload(client.raw, b"mp4-bytes", "video/mp4", "wf-1")
        client.raw.files.get(name="files/abc")
        client.raw.files.delete(name="files/abc")

        assert uploaded.name == "files/abc"
        assert [(r.method, r.url.path, r.headers.get("x-goog-upload-command")) for r in seen] == [
            ("POST", "/v1beta/models/gemini-test:streamGenerateContent", None),
            ("POST", "/v1beta/cachedContents", None),
            ("DELETE", "/v1beta/cachedContents/c1", None),
            ("POST", "/upload/v1beta/files", "start"),
            ("POST", "/upload/v1beta/files", "upload, finalize"),
            ("GET", "/v1beta/files/abc", None),
            ("DELETE", "/v1beta/files/abc", None),
        ]
        assert seen[4].read() == b"mp4-bytes"
        for request in seen:
            assert request.headers["x-posthog-product"] == "replay_vision", request.url
            assert request.headers["x-goog-api-key"] == "phs_gateway", request.url

    def test_upload_chunks_never_leave_the_gateway_host(self) -> None:
        def respond(request: httpx.Request) -> httpx.Response:
            upload_url = "https://generativelanguage.googleapis.com/upload/v1beta/files?upload_id=u1"
            return httpx.Response(200, json={}, headers={"x-goog-upload-url": upload_url})

        client, seen = _wired_gateway_client({}, respond)

        with pytest.raises(AIGatewayHostError, match="generativelanguage.googleapis.com"):
            _write_and_upload(client.raw, b"mp4-bytes", "video/mp4", "wf-1")

        assert [request.url.host for request in seen] == ["ai-gateway.example"]

    def test_a_redirect_off_the_gateway_host_is_not_followed(self) -> None:
        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                302, headers={"location": "https://generativelanguage.googleapis.com/v1beta/files/abc"}
            )

        client, seen = _wired_gateway_client({}, respond)

        with pytest.raises(AIGatewayHostError):
            client.raw.files.get(name="files/abc")

        assert [request.url.host for request in seen] == ["ai-gateway.example"]

    def test_a_gateway_refusal_on_an_upload_chunk_is_ours(self) -> None:
        refusal = {
            "error": {
                "code": 403,
                "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "domain": "posthog.com"}],
            }
        }

        def respond(request: httpx.Request) -> httpx.Response:
            if "upload_id" not in request.url.params:
                upload_url = "https://ai-gateway.example/upload/v1beta/files?upload_id=u1"
                return httpx.Response(200, json={}, headers={"x-goog-upload-url": upload_url})
            return httpx.Response(403, json=refusal)

        client, _ = _wired_gateway_client({}, respond)

        with patch("google.genai._api_client.time.sleep"), pytest.raises(genai_errors.ClientError) as exc_info:
            _write_and_upload(client.raw, b"mp4-bytes", "video/mp4", "wf-1")

        assert classify_gemini_error(exc_info.value) == FailureKind.INFRA_TRANSIENT

    def test_an_in_band_error_frame_raises(self) -> None:
        frame = {"error": {"code": 503, "message": "gateway shutting down", "status": "UNAVAILABLE"}}

        def respond(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=_sse(frame), headers={"content-type": "text/event-stream"})

        client, _ = _wired_gateway_client({}, respond)

        with pytest.raises(genai_errors.ServerError) as exc_info:
            asyncio.run(client.models.generate_content(model="gemini-test", contents="hi"))

        assert classify_gemini_error(exc_info.value) == FailureKind.PROVIDER_TRANSIENT
