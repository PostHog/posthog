from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from llm_gateway.services.quota_resolver import (
    QuotaResolver,
    QuotaResourceStatus,
    _redis_key,
)


def _make_response(status_code: int, payload: dict[str, object] | None = None) -> httpx.Response:
    content = json.dumps(payload or {}).encode()
    return httpx.Response(status_code, content=content, headers={"content-type": "application/json"})


def _make_http_client(response: httpx.Response | Exception) -> MagicMock:
    client = MagicMock()
    if isinstance(response, Exception):
        client.get = AsyncMock(side_effect=response)
    else:
        client.get = AsyncMock(return_value=response)
    return client


class TestQuotaResolver:
    @pytest.mark.asyncio
    async def test_fetches_and_parses_limited_response(self) -> None:
        http_client = _make_http_client(
            _make_response(200, {"team_id": 1, "limited": {"ai_credits": {"limited": True}}})
        )
        resolver = QuotaResolver(redis=None, http_client=http_client)

        status = await resolver.get_ai_credits_status(team_id=42, auth_header="Bearer phx_test")

        assert status == QuotaResourceStatus(limited=True)
        http_client.get.assert_awaited_once()
        assert http_client.get.await_args.kwargs["headers"]["Authorization"] == "Bearer phx_test"

    @pytest.mark.asyncio
    async def test_fetches_and_parses_unlimited_response(self) -> None:
        http_client = _make_http_client(
            _make_response(200, {"team_id": 1, "limited": {"ai_credits": {"limited": False}}})
        )
        resolver = QuotaResolver(redis=None, http_client=http_client)

        status = await resolver.get_ai_credits_status(team_id=42, auth_header="Bearer phx_test")

        assert status == QuotaResourceStatus(limited=False)

    @pytest.mark.asyncio
    async def test_fail_open_on_http_error(self) -> None:
        http_client = _make_http_client(httpx.ConnectError("boom"))
        resolver = QuotaResolver(redis=None, http_client=http_client)

        status = await resolver.get_ai_credits_status(team_id=42, auth_header="Bearer phx_test")

        assert status == QuotaResourceStatus(limited=False)

    @pytest.mark.asyncio
    async def test_fail_open_on_4xx(self) -> None:
        http_client = _make_http_client(_make_response(401, {"detail": "no auth"}))
        resolver = QuotaResolver(redis=None, http_client=http_client)

        status = await resolver.get_ai_credits_status(team_id=42, auth_header="Bearer phx_test")

        assert status == QuotaResourceStatus(limited=False)

    @pytest.mark.asyncio
    async def test_uses_cached_result_and_skips_http(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=json.dumps({"limited": True}).encode())
        http_client = _make_http_client(_make_response(200))
        resolver = QuotaResolver(redis=redis, http_client=http_client)

        status = await resolver.get_ai_credits_status(team_id=42, auth_header="Bearer phx_test")

        assert status == QuotaResourceStatus(limited=True)
        redis.get.assert_awaited_once_with(_redis_key("ai_credits", 42))
        http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_writes_cache_on_miss(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()
        http_client = _make_http_client(_make_response(200, {"limited": {"ai_credits": {"limited": True}}}))
        resolver = QuotaResolver(redis=redis, http_client=http_client)

        await resolver.get_ai_credits_status(team_id=42, auth_header="Bearer phx_test")

        redis.set.assert_awaited_once()
        call = redis.set.await_args
        assert call.args[0] == _redis_key("ai_credits", 42)
        assert json.loads(call.args[1]) == {"limited": True}
        # TTL matches the gateway settings default of 30s.
        assert call.kwargs.get("ex") == 30

    @pytest.mark.asyncio
    async def test_caches_fail_open_briefly_on_4xx(self) -> None:
        # 4xx responses (e.g. expired token) cache for a short window so a hot
        # loop with a broken token doesn't hammer Django.
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()
        http_client = _make_http_client(_make_response(401, {"detail": "no auth"}))
        resolver = QuotaResolver(redis=redis, http_client=http_client)

        await resolver.get_ai_credits_status(team_id=42, auth_header="Bearer phx_test")

        redis.set.assert_awaited_once()
        assert redis.set.await_args.kwargs.get("ex") == 5
