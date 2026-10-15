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
    _with_headers,
    assemble_stream,
    replay_gateway_client,
)
from products.replay_vision.backend.temporal import pii_check
from products.replay_vision.backend.temporal.errors import FailureKind
from products.replay_vision.backend.temporal.gemini import classify_gemini_error

_GATEWAY = {
    "AI_GATEWAY_URL": "https://ai-gateway.example/v1",
    "AI_GATEWAY_API_KEY": "phs_gateway",
    "REPLAY_VISION_GEMINI_API_KEY": "replay-vision-google-key",
}
_OK = {"candidates": [{"content": {"role": "model", "parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}
_FLAG = "products.replay_vision.backend.gemini_client.feature_enabled_or_false"


_ORG = "0190e1a2-0000-7000-8000-000000000042"


@pytest.fixture(autouse=True)
def flag_on() -> Any:
    with patch(_FLAG, return_value=True) as flag:
        yield flag


@pytest.fixture(autouse=True)
def team_org() -> Any:
    with patch("products.replay_vision.backend.gemini_client.Team") as team:
        team.objects.values_list.return_value.aget = AsyncMock(return_value=_ORG)
        yield team


def _sse(*chunks: dict[str, Any]) -> bytes:
    return b"".join(b"data: " + json.dumps(chunk).encode() + b"\r\n\r\n" for chunk in chunks)


def _ok(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith(":streamGenerateContent"):
        return httpx.Response(200, content=_sse(_OK), headers={"content-type": "text/event-stream"})
    return httpx.Response(200, json=_OK)


async def _agateway_client(properties: dict[str, Any] | None = None) -> GatewayGeminiClient:
    with override_settings(**_GATEWAY):
        client = await replay_gateway_client(42, properties=properties)
    assert isinstance(client, GatewayGeminiClient)
    return client


def _gateway_client(properties: dict[str, Any] | None = None) -> GatewayGeminiClient:
    return asyncio.run(_agateway_client(properties))


def _wired_gateway_client(
    properties: dict[str, Any], respond: Callable[[httpx.Request], httpx.Response] = _ok
) -> tuple[GatewayGeminiClient, list[httpx.Request]]:
    client = _gateway_client(properties)
    return client, _wire(client, respond)


def _wire(client: GatewayGeminiClient, respond: Callable[[httpx.Request], httpx.Response] = _ok) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return respond(request)

    # Swaps only the transport, so a client the SDK has closed still fails the call.
    api_client = client._client._api_client
    api_client._httpx_client._transport = httpx.MockTransport(handler)
    api_client._async_httpx_client._transport = httpx.MockTransport(handler)
    return seen


class TestReplayGatewayClient:
    def test_flag_off_stays_direct(self, flag_on: MagicMock) -> None:
        flag_on.return_value = False
        with override_settings(**_GATEWAY), patch("posthog.llm.gateway_client.genai.Client") as gateway_client:
            assert asyncio.run(replay_gateway_client(42)) is None
        gateway_client.assert_not_called()

    def test_gateway_mode_needs_the_direct_key_cleanup_deletes_with(self) -> None:
        settings = {**_GATEWAY, "REPLAY_VISION_GEMINI_API_KEY": ""}
        with override_settings(**settings), patch("posthog.llm.gateway_client.genai.Client") as gateway_client:
            assert asyncio.run(replay_gateway_client(42)) is None
        gateway_client.assert_not_called()

    def test_flag_is_evaluated_locally_per_org_without_events(self, flag_on: MagicMock, team_org: MagicMock) -> None:
        _gateway_client()
        team_org.objects.values_list.return_value.aget.assert_awaited_once_with(id=42)
        flag_on.assert_called_once_with(
            GATEWAY_FLAG,
            "team-42",
            groups={"organization": _ORG, "project": "42"},
            group_properties={"organization": {"id": _ORG}, "project": {"id": "42"}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )

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

    def test_request_headers_keep_the_callers_other_http_options(self) -> None:
        config = types.GenerateContentConfig(http_options=types.HttpOptions(timeout=5000, headers={"a": "1"}))
        merged = _with_headers(config, {"b": "2"})
        assert merged is not None and merged.http_options is not None
        assert merged.http_options.timeout == 5000
        assert merged.http_options.headers == {"a": "1", "b": "2"}


def test_pii_rewrite_uses_the_gateway_when_configured() -> None:
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
    assert json.loads(request_headers["X-PostHog-Properties"])["feature"] == "pii_rewrite"
    assert request_headers["X-PostHog-Span-Name"] == "pii_rewrite"
    sdk.close.assert_called_once()
    sdk.aio.aclose.assert_awaited_once()


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


class TestGatewayFilesAndCaches:
    def test_aclose_closes_both_transports(self) -> None:
        client, _ = _wired_gateway_client({})
        api_client = client._client._api_client
        asyncio.run(client.aclose())
        assert api_client._httpx_client.is_closed
        assert api_client._async_httpx_client.is_closed

    def test_every_call_is_tagged_replay_vision_with_the_gateway_key(self) -> None:
        def respond(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith(":streamGenerateContent"):
                return _ok(request)
            if path == "/v1beta/files:upload":
                return httpx.Response(200, json={"file": {"name": "files/abc"}})
            if path.startswith("/v1beta/cachedContents"):
                return httpx.Response(200, json={"name": "cachedContents/c1"} if request.method == "POST" else {})
            return httpx.Response(200, json={"name": "files/abc", "state": "ACTIVE"} if request.method == "GET" else {})

        client, seen = _wired_gateway_client({"feature": "scanner"}, respond)
        real_client = httpx.Client

        def record(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return respond(request)

        async def calls() -> None:
            await client.aio.models.generate_content(model="gemini-test", contents="hi")
            await client.aio.caches.create(
                model="gemini-test", config=types.CreateCachedContentConfig(contents=[types.Part(text="video")])
            )
            await client.aio.caches.delete(name="cachedContents/c1")

        asyncio.run(calls())
        client.files.get(name="files/abc")
        client.files.delete(name="files/abc")
        with patch(
            "products.replay_vision.backend.gemini_client.httpx.Client",
            lambda **kw: real_client(transport=httpx.MockTransport(record), **kw),
        ):
            client.upload_file(b"mp4", mime_type="video/mp4", display_name="wf-1")

        assert [(r.method, r.url.path) for r in seen] == [
            ("POST", "/v1beta/models/gemini-test:streamGenerateContent"),
            ("POST", "/v1beta/cachedContents"),
            ("DELETE", "/v1beta/cachedContents/c1"),
            ("GET", "/v1beta/files/abc"),
            ("DELETE", "/v1beta/files/abc"),
            ("POST", "/v1beta/files:upload"),
        ]
        for request in seen:
            assert request.headers["x-posthog-product"] == "replay_vision", request.url
            assert request.headers["x-goog-api-key"] == "phs_gateway", request.url

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
        assert request.headers["content-type"] == "video/mp4"
        assert request.headers["content-length"] == str(len(b"mp4-bytes"))
        assert "transfer-encoding" not in request.headers
        assert request.headers["x-goog-upload-display-name"] == "wf-1"
        assert client_kwargs["trust_env"] is False
        timeout = client_kwargs["timeout"]
        assert timeout.connect == 10.0 and timeout.read == 60.0 and timeout.write == 60.0

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
