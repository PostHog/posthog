import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Request

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.dependencies import _extract_end_user_id_from_body, enforce_throttles
from llm_gateway.rate_limiting.throttles import ThrottleContext, ThrottleResult


def _make_request(body: dict | None = None) -> Request:
    request = MagicMock(spec=Request)
    request.state = MagicMock()
    del request.state._cached_body

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
