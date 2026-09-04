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
from llm_gateway.services.desktop_access_resolver import DesktopAccessDecision, DesktopAccessResolver, _redis_key


def _make_response(status_code: int, payload: dict[str, object] | None = None) -> httpx.Response:
    content = json.dumps(payload if payload is not None else {}).encode()
    return httpx.Response(
        status_code,
        content=content,
        headers={"content-type": "application/json"},
        request=httpx.Request("GET", "https://us.posthog.com/api/projects/42/desktop/access/"),
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
    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            ({"allowed": True, "reason": None}, DesktopAccessDecision(status="allowed")),
            ({"allowed": False, "reason": None}, DesktopAccessDecision(status="blocked")),
            (
                {"allowed": False, "reason": "startup_plan"},
                DesktopAccessDecision(status="blocked", reason="startup_plan"),
            ),
            (
                {"allowed": False, "reason": "prepaid_credits"},
                DesktopAccessDecision(status="blocked", reason="prepaid_credits"),
            ),
        ],
    )
    async def test_returns_django_decision(self, payload: dict[str, object], expected: DesktopAccessDecision) -> None:
        resolver = _make_resolver(_FakeRedis(), _make_http_client(_make_response(200, payload)))

        assert await resolver.resolve_access(7, 42, "Bearer tok") == expected

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "response",
        [
            pytest.param(httpx.ConnectError("boom"), id="transport_error"),
            pytest.param(httpx.ReadTimeout("slow"), id="timeout"),
            pytest.param(_make_response(500), id="server_error"),
            pytest.param(_make_response(404), id="route_missing"),
            pytest.param(_make_response(429), id="throttled"),
            pytest.param(_make_response(200, {"allowed": "yes", "reason": None}), id="malformed_allowed"),
            pytest.param(_make_response(200, {"allowed": False}), id="missing_reason"),
        ],
    )
    async def test_resolution_failure_is_not_cached(self, response: httpx.Response | Exception) -> None:
        redis = _FakeRedis()
        http = _make_http_client(response)
        resolver = _make_resolver(redis, http)

        expected = DesktopAccessDecision(status="unavailable")
        assert await resolver.resolve_access(7, 42, "Bearer tok") == expected
        assert await resolver.resolve_access(7, 42, "Bearer tok") == expected

        assert http.get.await_count == 2
        assert _redis_key(7, 42, "Bearer tok") not in redis.store

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [401, 403])
    async def test_credential_rejection_is_cached_as_denial(self, status_code: int) -> None:
        settings = get_settings()
        redis = _FakeRedis()
        http = _make_http_client(_make_response(status_code))
        resolver = _make_resolver(redis, http)

        expected = DesktopAccessDecision(status="blocked")
        assert await resolver.resolve_access(7, 42, "Bearer restricted") == expected
        assert await resolver.resolve_access(7, 42, "Bearer restricted") == expected

        key = _redis_key(7, 42, "Bearer restricted")
        assert http.get.await_count == 1
        assert redis.ttls[key] == settings.desktop_access_denied_cache_ttl

    @pytest.mark.asyncio
    async def test_cache_is_isolated_by_user_team_and_credential(self) -> None:
        redis = _FakeRedis()
        http = _make_http_client(_make_response(200, {"allowed": True, "reason": None}))
        http.get.side_effect = [
            _make_response(200, {"allowed": True, "reason": None}),
            _make_response(200, {"allowed": True, "reason": None}),
            _make_response(200, {"allowed": True, "reason": None}),
            _make_response(403),
        ]
        resolver = _make_resolver(redis, http)

        assert (await resolver.resolve_access(7, 42, "Bearer unrestricted")).allowed is True
        assert (await resolver.resolve_access(7, 42, "Bearer unrestricted")).allowed is True
        assert (await resolver.resolve_access(7, 43, "Bearer unrestricted")).allowed is True
        assert (await resolver.resolve_access(8, 42, "Bearer unrestricted")).allowed is True
        assert (await resolver.resolve_access(7, 42, "Bearer restricted")).allowed is False

        assert http.get.await_count == 4
        assert len(redis.store) == 4

    @pytest.mark.asyncio
    async def test_denial_cached_more_briefly_than_grant(self) -> None:
        settings = get_settings()
        redis = _FakeRedis()

        granted = _make_resolver(redis, _make_http_client(_make_response(200, {"allowed": True, "reason": None})))
        await granted.resolve_access(7, 42, "Bearer tok")
        denied = _make_resolver(
            redis,
            _make_http_client(_make_response(200, {"allowed": False, "reason": "startup_plan"})),
        )
        await denied.resolve_access(8, 42, "Bearer tok")

        assert redis.ttls[_redis_key(7, 42, "Bearer tok")] == settings.desktop_access_cache_ttl
        assert redis.ttls[_redis_key(8, 42, "Bearer tok")] == settings.desktop_access_denied_cache_ttl
        assert settings.desktop_access_denied_cache_ttl < settings.desktop_access_cache_ttl

    @pytest.mark.asyncio
    async def test_calls_project_scoped_django_endpoint(self) -> None:
        http = _make_http_client(_make_response(200, {"allowed": True, "reason": None}))
        resolver = _make_resolver(None, http)

        await resolver.resolve_access(7, 42, "Bearer tok")

        base_url = get_settings().posthog_api_base_url.rstrip("/")
        url = http.get.await_args.args[0]
        assert url == f"{base_url}/api/projects/42/desktop/access/"
        assert http.get.await_args.kwargs["headers"] == {"Authorization": "Bearer tok"}
