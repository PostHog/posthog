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

from products.replay_vision.backend import (
    learned_rules,
    prompt_questions,
    scanner_draft,
    search_suggestions,
    tag_suggestions,
)
from products.replay_vision.backend.gemini_client import (
    GATEWAY_FLAG,
    GatewayGeminiClient,
    GatewaySpendLimitError,
    _send_before,
    _warn_gateway_without_dedicated_key,
    assemble_stream,
    replay_gateway_client,
    replay_gateway_enabled,
    replay_gemini_client,
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
_UNSET = {"AI_GATEWAY_URL": "", "AI_GATEWAY_API_KEY": "", "REPLAY_VISION_AI_GATEWAY_API_KEY": ""}
_OK = {"candidates": [{"content": {"role": "model", "parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}
_FLAG = "products.replay_vision.backend.gemini_client.feature_enabled_or_false"


def _gateway_error(code: int) -> dict[str, Any]:
    # The gateway's own envelope: Google's shape plus an ErrorInfo in the posthog.com domain.
    info = {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "forbidden", "domain": "posthog.com"}
    return {"error": {"code": code, "message": "refused", "status": "PERMISSION_DENIED", "details": [info]}}


def _google_error(code: int) -> dict[str, Any]:
    return {"error": {"code": code, "message": "You do not have permission", "status": "PERMISSION_DENIED"}}


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


def _wired_gateway_client(
    properties: dict[str, Any], respond: Callable[[httpx.Request], httpx.Response] = _ok
) -> tuple[GatewayGeminiClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return respond(request)

    with override_settings(**_GATEWAY):
        client = replay_gemini_client(MagicMock(), team_id=42, properties=properties, distinct_id="replay-vision:42")
    assert isinstance(client, GatewayGeminiClient)
    # Swaps only the transport, so a client the SDK has closed still fails the call.
    api_client = client.models._client._api_client
    api_client._httpx_client._transport = httpx.MockTransport(handler)
    api_client._async_httpx_client._transport = httpx.MockTransport(handler)
    return client, seen


class TestReplayGeminiClient:
    def test_direct_mode_returns_the_callers_client(self) -> None:
        direct = MagicMock()
        with override_settings(**_UNSET):
            assert replay_gemini_client(direct, team_id=42) is direct.return_value

    def test_flag_off_keeps_the_team_direct_even_with_the_gateway_configured(self, flag_on: MagicMock) -> None:
        flag_on.return_value = False
        direct = MagicMock()
        with override_settings(**_GATEWAY), patch("posthog.llm.gateway_client.genai.Client") as gateway_client:
            assert replay_gemini_client(direct, team_id=42) is direct.return_value
        gateway_client.assert_not_called()

    def test_flag_is_evaluated_locally_per_project_without_events(self, flag_on: MagicMock) -> None:
        with override_settings(**_GATEWAY):
            assert replay_gateway_enabled(42) is True
        flag_on.assert_called_once_with(
            GATEWAY_FLAG,
            "team-42",
            groups={"project": "42"},
            group_properties={"project": {"id": "42"}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )

    def test_unset_gateway_skips_the_flag(self, flag_on: MagicMock) -> None:
        with override_settings(**_UNSET):
            assert replay_gateway_enabled(42) is False
        flag_on.assert_not_called()

    def test_gateway_mode_never_builds_the_direct_client(self) -> None:
        direct = MagicMock()
        with override_settings(**_GATEWAY), patch("posthog.llm.gateway_client.genai.Client"):
            assert isinstance(replay_gemini_client(direct, team_id=42), GatewayGeminiClient)
        direct.assert_not_called()

    def test_per_call_capture_kwargs_become_request_headers(self) -> None:
        client, seen = _wired_gateway_client({"feature": "scanner", "team_id": 42})

        client.models.generate_content(
            model="models/gemini-test",
            contents=[types.Part.from_bytes(data=b"mp4", mime_type="video/mp4"), "hi"],
            config=types.GenerateContentConfig(temperature=0.2),
            posthog_distinct_id="user-1",
            posthog_trace_id="trace-1",
            posthog_properties={"$ai_span_name": "core", "feature": "override"},
            posthog_groups={"project": "42"},
        )

        request = seen[0]
        assert str(request.url) == "https://ai-gateway.example/v1beta/models/gemini-test:generateContent"
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

    def test_async_surface_uses_the_same_headers(self) -> None:
        client, seen = _wired_gateway_client({"feature": "scanner"})

        asyncio.run(client.aio.models.generate_content(model="gemini-test", contents="hi", posthog_trace_id="t"))

        assert seen[0].url.path.endswith(":streamGenerateContent")
        assert seen[0].headers["x-posthog-trace-id"] == "t"
        assert seen[0].headers["x-posthog-distinct-id"] == "replay-vision:42"

    def test_the_sdk_client_outlives_the_wrapper(self) -> None:
        async def call_after_collection() -> list[httpx.Request]:
            # Built inside a running loop, as the scan activity does: only there does the SDK close its async transport.
            client, seen = _wired_gateway_client({"feature": "scanner"})
            models, aio = client.models, client.aio
            del client
            gc.collect()
            await asyncio.sleep(0)
            models.generate_content(model="gemini-test", contents="hi")
            await aio.models.generate_content(model="gemini-test", contents="hi")
            await aio.aclose()
            return seen

        assert len(asyncio.run(call_after_collection())) == 2

    @pytest.mark.parametrize("code", [401, 403])
    def test_gateway_refusals_retry_as_transient(self, code: int) -> None:
        client, _ = _wired_gateway_client({}, respond=lambda _: httpx.Response(code, json=_gateway_error(code)))

        with pytest.raises(genai_errors.ServerError) as sync_error:
            client.models.generate_content(model="gemini-test", contents="hi")
        with pytest.raises(genai_errors.ServerError) as async_error:
            asyncio.run(client.aio.models.generate_content(model="gemini-test", contents="hi"))

        for error in (sync_error.value, async_error.value):
            assert classify_gemini_error(error) == FailureKind.PROVIDER_TRANSIENT
            assert f"HTTP {code}" in (error.message or "")

    def test_a_gateway_spend_limit_fails_without_retrying(self) -> None:
        client, _ = _wired_gateway_client({}, respond=lambda _: httpx.Response(402, json={"error": {"code": 402}}))

        with pytest.raises(GatewaySpendLimitError) as sync_error:
            client.models.generate_content(model="gemini-test", contents="hi")
        with pytest.raises(GatewaySpendLimitError) as async_error:
            asyncio.run(client.aio.models.generate_content(model="gemini-test", contents="hi"))

        for error in (sync_error.value, async_error.value):
            assert classify_gemini_error(error) == FailureKind.INTERNAL_ERROR
            assert not FailureKind.INTERNAL_ERROR.is_retryable
            assert describe_gemini_error(error) == "PostHog's AI spend limit for Replay Vision was reached"

    @pytest.mark.parametrize("code", [401, 403])
    def test_googles_own_refusals_keep_their_direct_mode_class(self, code: int) -> None:
        client, _ = _wired_gateway_client({}, respond=lambda _: httpx.Response(code, json=_google_error(code)))

        with pytest.raises(genai_errors.ClientError) as sync_error:
            client.models.generate_content(model="gemini-test", contents="hi")
        with pytest.raises(genai_errors.ClientError) as async_error:
            asyncio.run(client.aio.models.generate_content(model="gemini-test", contents="hi"))

        for error in (sync_error.value, async_error.value):
            assert error.code == code
            assert classify_gemini_error(error) == FailureKind.PROVIDER_REJECTED

    @pytest.mark.parametrize("code", [400, 413])
    def test_other_client_errors_pass_through(self, code: int) -> None:
        client, _ = _wired_gateway_client({}, respond=lambda _: httpx.Response(code, json={"error": {"code": code}}))

        with pytest.raises(genai_errors.ClientError) as exc_info:
            asyncio.run(client.aio.models.generate_content(model="gemini-test", contents="hi"))

        assert exc_info.value.code == code


def _call_search() -> None:
    search_suggestions._generate(user_content="x", team_id=1, distinct_id="u")


def _call_tags() -> None:
    tag_suggestions._generate(user_content="x", team_id=1, distinct_id="u")


def _call_draft() -> None:
    scanner_draft._generate(user_content="x", team_id=1, distinct_id="u")


@pytest.mark.parametrize(
    ("module", "call"),
    [
        (search_suggestions, _call_search),
        (tag_suggestions, _call_tags),
        (scanner_draft, _call_draft),
    ],
)
def test_text_call_sites_use_the_gateway_when_configured(module: Any, call: Callable[[], None]) -> None:
    with (
        override_settings(**_GATEWAY),
        patch("posthog.llm.gateway_client.genai.Client") as gateway_client,
        patch.object(module.genai, "Client") as direct_client,
    ):
        gateway_client.return_value.models.generate_content.side_effect = RuntimeError("stop")
        with pytest.raises(Exception):
            call()

    direct_client.assert_not_called()
    gateway_client.return_value.models.generate_content.assert_called()
    headers = gateway_client.call_args.kwargs["http_options"].headers
    assert headers["X-PostHog-Product"] == "replay_vision"
    assert headers["X-PostHog-Privacy-Mode"] == "true"
    request_headers = gateway_client.return_value.models.generate_content.call_args.kwargs[
        "config"
    ].http_options.headers
    labels = json.loads(request_headers["X-PostHog-Properties"])
    assert labels["ai_product"] == "replay_vision"
    assert labels["team_id"] == "1"
    assert labels["feature"]
    assert request_headers["X-PostHog-Distinct-Id"] == "u"


def test_prompt_questions_use_the_gateway_when_configured() -> None:
    # `_generate` falls back on any error, so the routing shows in the calls, not a raise.
    with (
        override_settings(**_GATEWAY),
        patch("posthog.llm.gateway_client.genai.Client") as gateway_client,
        patch.object(prompt_questions.genai, "Client") as direct_client,
    ):
        gateway_client.return_value.models.generate_content.side_effect = RuntimeError("stop")
        assert prompt_questions._generate(prompt="p", scale_line="", scanner_type="monitor", team_id=1) is None

    direct_client.assert_not_called()
    assert gateway_client.call_args.kwargs["http_options"].timeout == prompt_questions._MODEL_CALL_TIMEOUT_MS
    request_headers = gateway_client.return_value.models.generate_content.call_args.kwargs[
        "config"
    ].http_options.headers
    assert json.loads(request_headers["X-PostHog-Properties"])["feature"] == "prompt_question"


def test_learned_rules_use_the_gateway_when_configured() -> None:
    with (
        override_settings(**_GATEWAY),
        patch("posthog.llm.gateway_client.genai.Client") as gateway_client,
        patch.object(learned_rules.genai, "Client") as direct_client,
    ):
        gateway_client.return_value.models.generate_content.side_effect = RuntimeError("stop")
        with pytest.raises(learned_rules.LearnedRulesError):
            learned_rules._generate(user_content="x", team_id=1, trace_id="t")

    direct_client.assert_not_called()
    assert gateway_client.call_args.kwargs["http_options"].timeout == learned_rules._MODEL_CALL_TIMEOUT_MS
    request_headers = gateway_client.return_value.models.generate_content.call_args.kwargs[
        "config"
    ].http_options.headers
    assert json.loads(request_headers["X-PostHog-Properties"])["feature"] == "learned_rules"


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


def test_a_spend_limit_fails_the_pii_check_as_itself() -> None:
    output = MagicMock()
    with (
        patch.object(pii_check, "answer_text", return_value={"a": "my email is x@y.z"}),
        patch.object(pii_check, "asks_for_identity", return_value=False),
        patch.object(pii_check, "contains_pii", return_value=True),
        patch.object(
            pii_check, "rewrite_without_pii", AsyncMock(side_effect=GatewaySpendLimitError("AI gateway returned 402"))
        ),
        pytest.raises(GatewaySpendLimitError),
    ):
        asyncio.run(
            pii_check.keep_unrequested_pii_out(
                output, team_id=1, question="q", identity_values=(), scanner_type="monitor", trace_id="t"
            )
        )


def test_a_draft_does_not_retry_a_spend_limit() -> None:
    with (
        override_settings(**_GATEWAY),
        patch("posthog.llm.gateway_client.genai.Client") as gateway_client,
    ):
        gateway_client.return_value.models.generate_content.side_effect = genai_errors.ClientError(
            402, _gateway_error(402)
        )
        with pytest.raises(scanner_draft.DraftError) as exc_info:
            _call_draft()

    assert gateway_client.return_value.models.generate_content.call_count == 1
    assert isinstance(exc_info.value.__cause__, GatewaySpendLimitError)


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


class TestReplayVisionKey:
    def test_replay_vision_calls_use_its_own_key_never_the_shared_one(self) -> None:
        with override_settings(**_GATEWAY), patch("posthog.llm.gateway_client.genai.Client") as gateway_client:
            assert isinstance(replay_gemini_client(MagicMock(), team_id=42), GatewayGeminiClient)
        assert gateway_client.call_args.kwargs["api_key"] == "phs_replay_vision"

    def test_the_gateway_needs_replay_visions_own_google_key(self) -> None:
        # Without it, direct cleanup would use the shared project and miss the files the gateway stores.
        direct = MagicMock()
        no_google_key = {**_GATEWAY, "REPLAY_VISION_GEMINI_API_KEY": ""}
        _warn_gateway_without_dedicated_key.cache_clear()
        with (
            override_settings(**no_google_key),
            patch("posthog.llm.gateway_client.genai.Client") as gateway_client,
            patch("products.replay_vision.backend.gemini_client.logger") as replay_logger,
        ):
            assert replay_gemini_client(direct, team_id=42) is direct.return_value
            assert not replay_gateway_enabled(42)
            assert replay_gateway_client() is None
        gateway_client.assert_not_called()
        replay_logger.warning.assert_called_once()
        assert "REPLAY_VISION_GEMINI_API_KEY" in replay_logger.warning.call_args.kwargs["reason"]
        _warn_gateway_without_dedicated_key.cache_clear()

    def test_the_shared_key_alone_leaves_replay_vision_direct(self) -> None:
        direct = MagicMock()
        shared_only = {**_GATEWAY, "REPLAY_VISION_AI_GATEWAY_API_KEY": ""}
        with (
            override_settings(**shared_only),
            patch("posthog.llm.gateway_client.genai.Client") as gateway_client,
            patch("posthog.llm.gateway_client.logger") as gateway_logger,
        ):
            assert replay_gemini_client(direct, team_id=42) is direct.return_value
            assert not replay_gateway_enabled(42)
        gateway_client.assert_not_called()
        # An unset Replay Vision key is the default, not a misconfiguration, so it logs nothing per call.
        gateway_logger.warning.assert_not_called()


class TestGatewayFilesAndCaches:
    @pytest.mark.parametrize("code", [401, 403])
    def test_file_and_cache_refusals_retry_as_transient(self, code: int) -> None:
        client, _ = _wired_gateway_client({}, respond=lambda _: httpx.Response(code, json=_gateway_error(code)))
        with pytest.raises(genai_errors.ServerError) as cache_error:
            asyncio.run(client.aio.caches.delete(name="cachedContents/abc"))
        with pytest.raises(genai_errors.ServerError) as async_file_error:
            asyncio.run(client.aio.files.get(name="files/abc"))
        with pytest.raises(genai_errors.ServerError) as file_error:
            client.files.get(name="files/abc")
        for error in (cache_error.value, async_file_error.value, file_error.value):
            assert classify_gemini_error(error) == FailureKind.PROVIDER_TRANSIENT

    @pytest.mark.parametrize("code", [403, 404])
    def test_a_file_google_refuses_keeps_its_direct_mode_class(self, code: int) -> None:
        client, _ = _wired_gateway_client({}, respond=lambda _: httpx.Response(code, json=_google_error(code)))
        with pytest.raises(genai_errors.ClientError) as file_error:
            client.files.get(name="files/abc")
        with pytest.raises(genai_errors.ClientError) as cache_error:
            asyncio.run(client.aio.caches.get(name="cachedContents/abc"))
        for error in (file_error.value, cache_error.value):
            assert classify_gemini_error(error) == FailureKind.PROVIDER_REJECTED

    def test_a_spend_limit_on_a_file_call_fails_without_retrying(self) -> None:
        client, _ = _wired_gateway_client({}, respond=lambda _: httpx.Response(402, json=_gateway_error(402)))
        with pytest.raises(GatewaySpendLimitError):
            client.files.get(name="files/abc")
        with pytest.raises(GatewaySpendLimitError):
            asyncio.run(client.aio.caches.delete(name="cachedContents/abc"))

    def test_aclose_closes_both_transports(self) -> None:
        client, _ = _wired_gateway_client({})
        api_client = client.models._client._api_client
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
        with override_settings(**_GATEWAY):
            client = replay_gemini_client(MagicMock(), team_id=42)
        assert isinstance(client, GatewayGeminiClient)
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
        # The upload runs in a thread Temporal can't cancel, so it must end before the activity's 10 minutes.
        assert client_kwargs["trust_env"] is False
        timeout = client_kwargs["timeout"]
        assert timeout.connect == 10.0 and timeout.read == 60.0 and timeout.write == 60.0

    def test_upload_stops_sending_at_its_deadline(self) -> None:
        clock = iter([0.0, 1.0, 1000.0])
        with patch("products.replay_vision.backend.gemini_client.time.monotonic", lambda: next(clock)):
            chunks = _send_before(b"x" * (3 << 20), deadline=180.0)
            assert len(next(chunks)) == 1 << 20
            assert len(next(chunks)) == 1 << 20
            with pytest.raises(httpx.WriteTimeout):
                next(chunks)
        assert classify_gemini_error(httpx.WriteTimeout("deadline")) == FailureKind.PROVIDER_TRANSIENT

    @pytest.mark.parametrize("code", [401, 403])
    def test_upload_retries_a_gateway_refusal(self, code: int) -> None:
        with override_settings(**_GATEWAY):
            client = replay_gemini_client(MagicMock(), team_id=42)
        assert isinstance(client, GatewayGeminiClient)
        real_client = httpx.Client
        transport = httpx.MockTransport(lambda _: httpx.Response(code, json=_gateway_error(code)))
        with (
            patch(
                "products.replay_vision.backend.gemini_client.httpx.Client",
                lambda **kw: real_client(transport=transport, **kw),
            ),
            pytest.raises(genai_errors.ServerError) as exc_info,
        ):
            client.upload_file(b"x", mime_type="video/mp4", display_name="wf-1")
        assert classify_gemini_error(exc_info.value) == FailureKind.PROVIDER_TRANSIENT

    @pytest.mark.parametrize("code", [401, 403])
    def test_upload_keeps_googles_own_refusal(self, code: int) -> None:
        with override_settings(**_GATEWAY):
            client = replay_gemini_client(MagicMock(), team_id=42)
        assert isinstance(client, GatewayGeminiClient)
        real_client = httpx.Client
        transport = httpx.MockTransport(lambda _: httpx.Response(code, json=_google_error(code)))
        with (
            patch(
                "products.replay_vision.backend.gemini_client.httpx.Client",
                lambda **kw: real_client(transport=transport, **kw),
            ),
            pytest.raises(genai_errors.ClientError) as exc_info,
        ):
            client.upload_file(b"x", mime_type="video/mp4", display_name="wf-1")
        assert exc_info.value.code == code

    def test_upload_maps_a_gateway_refusal_like_a_generate_call(self) -> None:
        with override_settings(**_GATEWAY):
            client = replay_gemini_client(MagicMock(), team_id=42)
        assert isinstance(client, GatewayGeminiClient)
        real_client = httpx.Client
        with (
            patch(
                "products.replay_vision.backend.gemini_client.httpx.Client",
                lambda **kw: real_client(
                    transport=httpx.MockTransport(lambda _: httpx.Response(402, json={"error": {"code": 402}})), **kw
                ),
            ),
            pytest.raises(GatewaySpendLimitError),
        ):
            client.upload_file(b"x", mime_type="video/mp4", display_name="wf-1")
