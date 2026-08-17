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

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


def _make_resolver(redis: _FakeRedis | None, http_client: MagicMock) -> DesktopAccessResolver:
    return DesktopAccessResolver(cast("Redis[bytes] | None", redis), http_client)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestDesktopAccessResolver:
    @pytest.mark.asyncio
    async def test_entitled_user_allowed(self) -> None:
        resolver = _make_resolver(_FakeRedis(), _make_http_client(_make_response(200, {"has_access": True})))
        assert await resolver.has_access(7, "Bearer tok") is True

    @pytest.mark.asyncio
    async def test_unentitled_user_denied(self) -> None:
        resolver = _make_resolver(_FakeRedis(), _make_http_client(_make_response(200, {"has_access": False})))
        assert await resolver.has_access(7, "Bearer tok") is False

    @pytest.mark.asyncio
    async def test_no_auth_header_is_unknown(self) -> None:
        http = _make_http_client(_make_response(200, {"has_access": False}))
        resolver = _make_resolver(_FakeRedis(), http)
        assert await resolver.has_access(7, "") is None
        http.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_transport_error_is_unknown_not_denied(self) -> None:
        resolver = _make_resolver(_FakeRedis(), _make_http_client(httpx.ConnectError("boom")))
        assert await resolver.has_access(7, "Bearer tok") is None

    @pytest.mark.asyncio
    async def test_server_error_is_unknown_not_denied(self) -> None:
        resolver = _make_resolver(_FakeRedis(), _make_http_client(_make_response(500)))
        assert await resolver.has_access(7, "Bearer tok") is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [400, 401, 403, 429])
    async def test_caller_attributable_rejection_is_denied(self, status_code: int) -> None:
        resolver = _make_resolver(_FakeRedis(), _make_http_client(_make_response(status_code)))
        assert await resolver.has_access(7, "Bearer tok") is False

    @pytest.mark.asyncio
    async def test_missing_route_is_unknown_not_denied(self) -> None:
        resolver = _make_resolver(_FakeRedis(), _make_http_client(_make_response(404)))
        assert await resolver.has_access(7, "Bearer tok") is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("header", ["bearer tok", "BEARER  tok ", "Bearer tok"])
    async def test_bearer_scheme_is_canonicalized(self, header: str) -> None:
        http = _make_http_client(_make_response(200, {"has_access": True}))
        resolver = _make_resolver(None, http)

        await resolver.has_access(7, header)

        assert http.get.await_args.kwargs["headers"] == {"Authorization": "Bearer tok"}

    @pytest.mark.asyncio
    async def test_malformed_payload_is_unknown(self) -> None:
        resolver = _make_resolver(_FakeRedis(), _make_http_client(_make_response(200, {"has_access": "yes"})))
        assert await resolver.has_access(7, "Bearer tok") is None

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
    async def test_unknown_result_is_not_cached(self) -> None:
        redis = _FakeRedis()
        http = _make_http_client(_make_response(500))
        resolver = _make_resolver(redis, http)

        assert await resolver.has_access(7, "Bearer tok") is None
        assert await resolver.has_access(7, "Bearer tok") is None
        assert http.get.await_count == 2

    @pytest.mark.asyncio
    async def test_invalidate_clears_cache(self) -> None:
        redis = _FakeRedis()
        resolver = _make_resolver(redis, _make_http_client(_make_response(200, {"has_access": True})))

        await resolver.has_access(7, "Bearer tok")
        await resolver.invalidate(7)
        assert _redis_key(7) not in redis.store

    @pytest.mark.asyncio
    async def test_calls_django_check_access_endpoint(self) -> None:
        http = _make_http_client(_make_response(200, {"has_access": True}))
        resolver = _make_resolver(None, http)

        await resolver.has_access(7, "Bearer tok")

        base_url = get_settings().posthog_api_base_url.rstrip("/")
        url = http.get.await_args.args[0]
        assert url == f"{base_url}/api/code/invites/check-access/"
        assert http.get.await_args.kwargs["headers"] == {"Authorization": "Bearer tok"}
