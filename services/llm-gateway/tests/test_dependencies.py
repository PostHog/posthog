import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, Request
from starlette.datastructures import Headers

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.dependencies import _extract_end_user_id_from_body, enforce_throttles, get_provider_from_request
from llm_gateway.rate_limiting.throttles import ThrottleContext, ThrottleResult


def _make_request(body: dict | None = None, headers: dict[str, str] | None = None) -> Request:
    request = MagicMock(spec=Request)
    request.state = MagicMock()
    del request.state._cached_body
    request.headers = Headers(headers or {})

    if body is not None:
        raw = json.dumps(body).encode()
    else:
        raw = None

    async def fake_body():
        return raw

    request.body = fake_body
    return request


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

        async def fake_body():
            return b'["not", "a", "dict"]'

        request.body = fake_body
        assert await _extract_end_user_id_from_body(request) is None


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
        request.url = MagicMock()
        request.url.path = "/openai/v1/chat/completions"
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
    """The ai_credits quota resolver roundtrip is skipped for products that don't
    bill into the ai_credits bucket — unbilled ones, and products billing into a
    bucket without gateway-side quota enforcement (e.g. posthog_code)."""

    async def _run(self, product: str) -> tuple:
        from unittest.mock import AsyncMock

        from llm_gateway.dependencies import resolve_plan_and_quota
        from llm_gateway.services.plan_resolver import PlanInfo
        from llm_gateway.services.quota_resolver import QuotaResourceStatus

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
    async def test_ai_credits_billed_product_resolves_quota(self) -> None:
        (_, quota_status), quota_mock = await self._run("slack_app")

        quota_mock.assert_awaited_once()
        assert quota_status.limited is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("product", ["posthog_code", "wizard"])
    async def test_ungated_products_skip_quota_resolver(self, product: str) -> None:
        # posthog_code bills into its own bucket (no gateway quota enforcement);
        # wizard is unbilled. Neither should pay for the quota resolver roundtrip.
        (_, quota_status), quota_mock = await self._run(product)

        quota_mock.assert_not_awaited()
        assert quota_status.limited is False
