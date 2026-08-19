from __future__ import annotations

import json
from collections.abc import Iterator
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

if TYPE_CHECKING:
    from redis.asyncio import Redis

from llm_gateway.config import get_settings
from llm_gateway.services.desktop_access_resolver import DesktopAccessResolver, _redis_key


def _make_response(status_code: int, payload: dict[str, object] | None = None) -> httpx.Response:
    content = json.dumps(payload if payload is not None else {}).encode()
    return httpx.Response(
        status_code,
        content=content,
        headers={"content-type": "application/json"},
        request=httpx.Request("GET", "https://us.posthog.com/api/code/invites/check-access/"),
    )


def _make_http_client(response: httpx.Response | Exception) -> MagicMock:
    client = MagicMock()
    if isinstance(response, Exception):
        client.get = AsyncMock(side_effect=response)
    else:
        client.get = AsyncMock(return_value=response)
    return client


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def set(self, key: str, value: str | bytes, ex: int | None = None) -> None:
        self.store[key] = value if isinstance(value, bytes) else value.encode()
        if ex is not None:
            self.ttls[key] = ex


def _make_resolver(redis: _FakeRedis | None, http_client: MagicMock) -> DesktopAccessResolver:
    return DesktopAccessResolver(cast("Redis[bytes] | None", redis), http_client)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestDesktopAccessResolver:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("has_access", [True, False])
    async def test_returns_django_answer(self, has_access: bool) -> None:
        resolver = _make_resolver(_FakeRedis(), _make_http_client(_make_response(200, {"has_access": has_access})))
        assert await resolver.has_access(7, "Bearer tok") is has_access

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "response",
        [
            pytest.param(httpx.ConnectError("boom"), id="transport_error"),
            pytest.param(httpx.ReadTimeout("slow"), id="timeout"),
            pytest.param(_make_response(500), id="server_error"),
            pytest.param(_make_response(404), id="route_missing"),
            pytest.param(_make_response(401), id="unauthorized"),
            pytest.param(_make_response(429), id="throttled"),
            pytest.param(_make_response(200, {"has_access": "yes"}), id="malformed_payload"),
        ],
    )
    async def test_anything_but_an_explicit_grant_denies_and_is_cached_briefly(
        self, response: httpx.Response | Exception
    ) -> None:
        redis = _FakeRedis()
        http = _make_http_client(response)
        resolver = _make_resolver(redis, http)

        assert await resolver.has_access(7, "Bearer tok") is False
        assert await resolver.has_access(7, "Bearer tok") is False

        assert http.get.await_count == 1
        assert redis.ttls[_redis_key(7)] == get_settings().desktop_access_denied_cache_ttl

    @pytest.mark.asyncio
    async def test_result_is_cached_and_reused(self) -> None:
        redis = _FakeRedis()
        http = _make_http_client(_make_response(200, {"has_access": True}))
        resolver = _make_resolver(redis, http)

        assert await resolver.has_access(7, "Bearer tok") is True
        assert await resolver.has_access(7, "Bearer tok") is True
        assert http.get.await_count == 1

    @pytest.mark.asyncio
    async def test_denial_cached_more_briefly_than_grant(self) -> None:
        settings = get_settings()
        redis = _FakeRedis()

        granted = _make_resolver(redis, _make_http_client(_make_response(200, {"has_access": True})))
        await granted.has_access(7, "Bearer tok")
        denied = _make_resolver(redis, _make_http_client(_make_response(200, {"has_access": False})))
        await denied.has_access(8, "Bearer tok")

        assert redis.ttls[_redis_key(7)] == settings.desktop_access_cache_ttl
        assert redis.ttls[_redis_key(8)] == settings.desktop_access_denied_cache_ttl
        assert settings.desktop_access_denied_cache_ttl < settings.desktop_access_cache_ttl

    @pytest.mark.asyncio
    async def test_calls_django_check_access_endpoint(self) -> None:
        http = _make_http_client(_make_response(200, {"has_access": True}))
        resolver = _make_resolver(None, http)

        await resolver.has_access(7, "Bearer tok")

        base_url = get_settings().posthog_api_base_url.rstrip("/")
        url = http.get.await_args.args[0]
        assert url == f"{base_url}/api/code/invites/check-access/"
        assert http.get.await_args.kwargs["headers"] == {"Authorization": "Bearer tok"}
