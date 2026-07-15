import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request
from starlette.datastructures import Headers

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.dependencies import (
    _extract_end_user_id_from_body,
    enforce_product_access,
    enforce_throttles,
    get_model_from_request,
    get_provider_from_request,
    get_request_json,
    resolve_plan_and_quota,
)
from llm_gateway.products.config import POSTHOG_CODE_US_APP_ID
from llm_gateway.rate_limiting.throttles import ThrottleContext, ThrottleResult
from llm_gateway.services.plan_resolver import PlanInfo
from llm_gateway.services.quota_resolver import QuotaResourceStatus


def _make_request(
    body: dict | None = None,
    headers: dict[str, str] | None = None,
    path: str = "/openai/v1/chat/completions",
) -> Request:
    request = MagicMock(spec=Request)
    request.state = MagicMock()
    del request.state._cached_body
    del request.state._cached_json
    request.headers = Headers(headers or {})
    # configure_mock dodges the read-only URL.path property the spec exposes
    request.configure_mock(**{"url.path": path})

    if body is not None:
        raw = json.dumps(body).encode()
    else:
        raw = None

    async def fake_body():
        return raw

    request.body = fake_body
    return request


_TRANSCRIPTION_MULTIPART_BODY = (
    b'--boundary\r\nContent-Disposition: form-data; name="model"\r\n\r\ngpt-4o-transcribe\r\n--boundary--\r\n'
)


def _make_form_request(body: bytes, content_type: str, path: str) -> Request:
    # real Request, not a mock: these tests exercise starlette's actual form parsing
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "query_string": b"",
        "headers": [(b"content-type", content_type.encode())],
        "app": MagicMock(),
    }

    async def receive() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


def _make_user(auth_method: str = "personal_api_key", user_id: int = 1) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id,
        team_id=1,
        auth_method=auth_method,
        distinct_id=f"test-distinct-id-{user_id}",
        scopes=["llm_gateway:read"],
    )


class TestExtractEndUserIdFromBody:
    @pytest.mark.asyncio
    async def test_returns_openai_user_field(self) -> None:
        request = _make_request({"model": "gpt-4o", "messages": [], "user": "user-123"})
        assert await _extract_end_user_id_from_body(request) == "user-123"

    @pytest.mark.asyncio
    async def test_returns_anthropic_metadata_user_id(self) -> None:
        request = _make_request({"model": "claude-3", "messages": [], "metadata": {"user_id": "user-456"}})
        assert await _extract_end_user_id_from_body(request) == "user-456"

    @pytest.mark.asyncio
    async def test_openai_user_takes_precedence_over_metadata(self) -> None:
        request = _make_request({"model": "gpt-4o", "user": "openai-user", "metadata": {"user_id": "anthro-user"}})
        assert await _extract_end_user_id_from_body(request) == "openai-user"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_user_provided(self) -> None:
        request = _make_request({"model": "gpt-4o", "messages": []})
        assert await _extract_end_user_id_from_body(request) is None

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_body(self) -> None:
        request = _make_request()
        assert await _extract_end_user_id_from_body(request) is None

    @pytest.mark.asyncio
    async def test_returns_none_for_non_string_user(self) -> None:
        request = _make_request({"model": "gpt-4o", "user": 123})
        assert await _extract_end_user_id_from_body(request) is None

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_string_user(self) -> None:
        request = _make_request({"model": "gpt-4o", "user": ""})
        assert await _extract_end_user_id_from_body(request) is None

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_metadata(self) -> None:
        request = _make_request({"model": "gpt-4o", "metadata": {}})
        assert await _extract_end_user_id_from_body(request) is None

    @pytest.mark.asyncio
    async def test_returns_none_for_non_dict_metadata(self) -> None:
        request = _make_request({"model": "gpt-4o", "metadata": "not-a-dict"})
        assert await _extract_end_user_id_from_body(request) is None

    @pytest.mark.asyncio
    async def test_returns_none_for_non_dict_json_body(self) -> None:
        request = MagicMock(spec=Request)
        request.state = MagicMock()
        del request.state._cached_body
        del request.state._cached_json

        async def fake_body():
            return b'["not", "a", "dict"]'

        request.body = fake_body
        assert await _extract_end_user_id_from_body(request) is None


class TestGetRequestJson:
    @pytest.mark.asyncio
    async def test_parses_once_and_caches_the_dict(self) -> None:
        # the access-check chain (product access, free-tier gate, end-user id) reads
        # the body several times per request; losing the cache re-parses multi-MB
        # completion bodies on the hot path
        request = _make_request({"model": "gpt-4o", "messages": []})

        first = await get_request_json(request)

        assert first == {"model": "gpt-4o", "messages": []}
        assert await get_request_json(request) is first


class TestGetProviderFromRequest:
    @pytest.mark.asyncio
    async def test_returns_provider_from_header(self) -> None:
        request = _make_request(
            {"model": "claude-sonnet-4-6", "provider": "anthropic"},
            headers={"X-PostHog-Provider": "bedrock"},
        )

        assert await get_provider_from_request(request) == "bedrock"

    @pytest.mark.asyncio
    async def test_invalid_provider_header_raises_http_400(self) -> None:
        request = _make_request(headers={"X-PostHog-Provider": "vertex"})

        with pytest.raises(HTTPException) as exc_info:
            await get_provider_from_request(request)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["error"]["type"] == "invalid_request_error"


class TestEnforceThrottles:
    async def _run_enforce_throttles(
        self,
        body: dict | None = None,
        auth_method: str = "personal_api_key",
        user_id: int = 1,
    ) -> ThrottleContext:
        request = _make_request(body)
        user = _make_user(auth_method=auth_method, user_id=user_id)

        captured_context: ThrottleContext | None = None

        async def capture_check(context: ThrottleContext) -> ThrottleResult:
            nonlocal captured_context
            captured_context = context
            return ThrottleResult.allow()

        runner = MagicMock()
        runner.check = capture_check

        with patch("llm_gateway.dependencies.ensure_costs_fresh"):
            await enforce_throttles(request=request, user=user, runner=runner)

        assert captured_context is not None
        return captured_context

    @pytest.mark.asyncio
    async def test_api_key_without_user_sets_end_user_id_none(self) -> None:
        context = await self._run_enforce_throttles(
            body={"model": "gpt-4o", "messages": []},
            auth_method="personal_api_key",
        )
        assert context.end_user_id is None

    @pytest.mark.asyncio
    async def test_api_key_with_openai_user_sets_end_user_id(self) -> None:
        context = await self._run_enforce_throttles(
            body={"model": "gpt-4o", "messages": [], "user": "user-abc"},
            auth_method="personal_api_key",
        )
        assert context.end_user_id == "user-abc"

    @pytest.mark.asyncio
    async def test_api_key_with_anthropic_metadata_user_id_sets_end_user_id(self) -> None:
        context = await self._run_enforce_throttles(
            body={"model": "claude-3", "messages": [], "metadata": {"user_id": "user-xyz"}},
            auth_method="personal_api_key",
        )
        assert context.end_user_id == "user-xyz"

    @pytest.mark.asyncio
    async def test_oauth_always_sets_end_user_id_to_user_id(self) -> None:
        context = await self._run_enforce_throttles(
            body={"model": "gpt-4o", "messages": []},
            auth_method="oauth_access_token",
            user_id=42,
        )
        assert context.end_user_id == "42"

    @pytest.mark.asyncio
    async def test_oauth_ignores_body_user_field(self) -> None:
        context = await self._run_enforce_throttles(
            body={"model": "gpt-4o", "messages": [], "user": "body-user"},
            auth_method="oauth_access_token",
            user_id=42,
        )
        assert context.end_user_id == "42"

    @pytest.mark.asyncio
    async def test_api_key_no_body_sets_end_user_id_none(self) -> None:
        context = await self._run_enforce_throttles(
            body=None,
            auth_method="personal_api_key",
        )
        assert context.end_user_id is None


class TestResolvePlanAndQuota:
    """The quota resolver roundtrip runs for bucket-billed products (against the
    product's own bucket) and is skipped entirely for unbilled ones."""

    async def _run(self, product: str) -> tuple:
        plan_info = PlanInfo(plan_key="pro", seat_created_at=None)
        plan_mock = AsyncMock(return_value=plan_info)
        quota_mock = AsyncMock(return_value=QuotaResourceStatus(limited=True))
        with (
            patch("llm_gateway.dependencies.resolve_plan_info", plan_mock),
            patch("llm_gateway.dependencies.resolve_quota_status", quota_mock),
        ):
            result = await resolve_plan_and_quota(_make_request(), user_id=1, team_id=42, product=product)
        return result, quota_mock

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("product", "expected_resource"),
        [("slack_app", "ai_credits"), ("posthog_code", "posthog_code_credits")],
    )
    async def test_bucket_billed_product_resolves_its_own_bucket(self, product: str, expected_resource: str) -> None:
        (_, quota_status), quota_mock = await self._run(product)

        quota_mock.assert_awaited_once()
        assert quota_mock.call_args.args[2] == expected_resource
        assert quota_status.limited is True

    @pytest.mark.asyncio
    async def test_unbilled_product_skips_quota_resolver(self) -> None:
        # wizard is unbilled — it shouldn't pay for the quota resolver roundtrip.
        (_, quota_status), quota_mock = await self._run("wizard")

        quota_mock.assert_not_awaited()
        assert quota_status.limited is False


class TestGetModelFromRequest:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "body,content_type",
        [
            (_TRANSCRIPTION_MULTIPART_BODY, "multipart/form-data; boundary=boundary"),
            (b"model=gpt-4o-transcribe&language=en", "application/x-www-form-urlencoded"),
        ],
    )
    async def test_reads_model_from_form_bodies(self, body: bytes, content_type: str) -> None:
        request = _make_form_request(body, content_type, "/posthog_code/v1/audio/transcriptions")
        assert await get_model_from_request(request) == "gpt-4o-transcribe"

    @pytest.mark.asyncio
    async def test_form_parse_leaves_the_upload_readable_for_the_endpoint(self) -> None:
        # a parse that consumed the stream or left the upload cursor at the end
        # would make every legitimate transcription send empty audio
        body = (
            b"--boundary\r\n"
            b'Content-Disposition: form-data; name="model"\r\n\r\ngpt-4o-transcribe\r\n'
            b"--boundary\r\n"
            b'Content-Disposition: form-data; name="file"; filename="a.mp3"\r\n'
            b"Content-Type: audio/mpeg\r\n\r\naudio-bytes\r\n"
            b"--boundary--\r\n"
        )
        request = _make_form_request(
            body, "multipart/form-data; boundary=boundary", "/posthog_code/v1/audio/transcriptions"
        )

        assert await get_model_from_request(request) == "gpt-4o-transcribe"

        form = await request.form()
        upload = form["file"]
        assert not isinstance(upload, str)
        assert await upload.read() == b"audio-bytes"


class TestFreeTierModelGateWiring:
    @pytest.mark.asyncio
    async def test_multipart_transcription_model_is_gated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # the gate must see form-encoded models, not just JSON ones
        from llm_gateway.config import get_settings

        monkeypatch.setenv("LLM_GATEWAY_POSTHOG_CODE_MODEL_GATE_ENABLED", "true")
        get_settings.cache_clear()
        try:
            request = _make_form_request(
                _TRANSCRIPTION_MULTIPART_BODY,
                "multipart/form-data; boundary=boundary",
                "/posthog_code/v1/audio/transcriptions",
            )
            user = _make_user(auth_method="oauth_access_token", user_id=7)

            runner = MagicMock()
            runner.check = AsyncMock(return_value=ThrottleResult.allow())

            with patch("llm_gateway.dependencies.ensure_costs_fresh"):
                with pytest.raises(HTTPException) as exc_info:
                    await enforce_throttles(request=request, user=user, runner=runner)

            assert exc_info.value.status_code == 403
            assert "gpt-4o-transcribe" in exc_info.value.detail["error"]["message"]
        finally:
            get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_gated_model_is_rejected_on_the_enforcement_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # pins that enforce_throttles actually consults the gate on the request path
        from llm_gateway.config import get_settings

        monkeypatch.setenv("LLM_GATEWAY_POSTHOG_CODE_MODEL_GATE_ENABLED", "true")
        get_settings.cache_clear()
        try:
            request = _make_request({"model": "claude-fable-5", "messages": []}, path="/array/v1/messages")
            user = _make_user(auth_method="oauth_access_token", user_id=7)

            runner = MagicMock()
            runner.check = AsyncMock(return_value=ThrottleResult.allow())

            with patch("llm_gateway.dependencies.ensure_costs_fresh"):
                with pytest.raises(HTTPException) as exc_info:
                    await enforce_throttles(request=request, user=user, runner=runner)

            assert exc_info.value.status_code == 403
            error = exc_info.value.detail["error"]
            assert "claude-fable-5" in error["message"]
            assert error["code"] == "model_gate"
            # Legacy PostHog Code clients route errors by substring; the
            # "(rate_limit)" suffix sends this 403 to their usage-limit modal
            # instead of their fatal-session teardown path.
            assert error["message"].endswith("(rate_limit)")
        finally:
            get_settings.cache_clear()


class TestServerCredentialRequirementWiring:
    def _oauth_user(self, scopes: list[str]) -> AuthenticatedUser:
        return AuthenticatedUser(
            user_id=7,
            team_id=1,
            auth_method="oauth_access_token",
            distinct_id="test-distinct-id-7",
            scopes=scopes,
            application_id=POSTHOG_CODE_US_APP_ID,
        )

    @pytest.mark.asyncio
    async def test_marker_less_oauth_token_rejected_on_sibling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # pins that enforce_product_access actually applies the server-credential check on the path
        from llm_gateway.config import get_settings

        monkeypatch.setenv("LLM_GATEWAY_POSTHOG_CODE_MODEL_GATE_ENABLED", "true")
        get_settings.cache_clear()
        try:
            request = _make_request({"model": "claude-sonnet-5", "messages": []}, path="/signals/v1/messages")
            with pytest.raises(HTTPException) as exc_info:
                await enforce_product_access(request=request, user=self._oauth_user(["*"]))
            assert exc_info.value.status_code == 403
            assert "server-minted" in exc_info.value.detail
        finally:
            get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_marker_token_allowed_on_sibling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # pins that enforce_product_access forwards the token scopes; without scopes=user.scopes a
        # real server-minted token (carrying the marker) would be wrongly rejected here.
        from llm_gateway.config import get_settings

        monkeypatch.setenv("LLM_GATEWAY_POSTHOG_CODE_MODEL_GATE_ENABLED", "true")
        get_settings.cache_clear()
        try:
            request = _make_request({"model": "claude-sonnet-5", "messages": []}, path="/signals/v1/messages")
            user = self._oauth_user(["llm_gateway:read", "internal_run:read"])
            assert await enforce_product_access(request=request, user=user) is user
        finally:
            get_settings.cache_clear()
