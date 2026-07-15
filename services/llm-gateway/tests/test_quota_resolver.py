from __future__ import annotations

import json
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from starlette.datastructures import Headers

from llm_gateway.services.quota_resolver import (
    _FAIL_OPEN_CACHE_TTL_SECONDS,
    _RETRY_DELAYS_SECONDS,
    QuotaResolver,
    QuotaResourceStatus,
    _redis_key,
    resolve_quota_status,
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


def _make_http_client_sequence(responses: list[httpx.Response | Exception]) -> MagicMock:
    client = MagicMock()

    async def _next(*args: object, **kwargs: object) -> httpx.Response:
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    client.get = AsyncMock(side_effect=_next)
    return client


@pytest.fixture(autouse=True)
def _no_retry_sleep() -> Iterator[None]:
    """Don't actually sleep between retries — keeps tests fast and deterministic."""
    with patch("llm_gateway.services.quota_resolver.asyncio.sleep", new=AsyncMock()):
        yield


def _make_request(headers: dict[str, str], resolver: AsyncMock | None = None) -> MagicMock:
    request = MagicMock()
    request.headers = Headers(headers)
    request.app.state.quota_resolver = resolver
    return request


class TestResolveQuotaStatus:
    """Credential forwarding must mirror extract_token: either header authenticates,
    so either header must reach the quota check — otherwise x-api-key callers
    bypass enforcement."""

    def _make_resolver(self) -> AsyncMock:
        resolver = MagicMock()
        resolver.get_resource_status = AsyncMock(return_value=QuotaResourceStatus(limited=True))
        return resolver

    @pytest.mark.asyncio
    async def test_forwards_authorization_header(self) -> None:
        resolver = self._make_resolver()
        request = _make_request({"Authorization": "Bearer phx_test"}, resolver)

        status = await resolve_quota_status(request, team_id=42, resource_key="ai_credits")

        assert status == QuotaResourceStatus(limited=True)
        assert resolver.get_resource_status.await_args.kwargs["auth_header"] == "Bearer phx_test"

    @pytest.mark.asyncio
    async def test_forwards_x_api_key_as_bearer(self) -> None:
        resolver = self._make_resolver()
        request = _make_request({"x-api-key": " phx_test "}, resolver)

        status = await resolve_quota_status(request, team_id=42, resource_key="ai_credits")

        assert status == QuotaResourceStatus(limited=True)
        assert resolver.get_resource_status.await_args.kwargs["auth_header"] == "Bearer phx_test"

    @pytest.mark.asyncio
    async def test_x_api_key_takes_precedence_over_authorization(self) -> None:
        # Matches extract_token — the token that authenticated the request is
        # the one whose quota gets checked.
        resolver = self._make_resolver()
        request = _make_request(
            {"x-api-key": "phx_from_api_key", "Authorization": "Bearer phx_from_auth"},
            resolver,
        )

        await resolve_quota_status(request, team_id=42, resource_key="ai_credits")

        assert resolver.get_resource_status.await_args.kwargs["auth_header"] == "Bearer phx_from_api_key"

    @pytest.mark.asyncio
    async def test_no_credentials_fails_open_without_resolver_call(self) -> None:
        resolver = self._make_resolver()
        request = _make_request({}, resolver)

        status = await resolve_quota_status(request, team_id=42, resource_key="ai_credits")

        assert status == QuotaResourceStatus(limited=False)
        resolver.get_resource_status.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_team_id_fails_open(self) -> None:
        resolver = self._make_resolver()
        request = _make_request({"Authorization": "Bearer phx_test"}, resolver)

        status = await resolve_quota_status(request, team_id=None, resource_key="ai_credits")

        assert status == QuotaResourceStatus(limited=False)
        resolver.get_resource_status.assert_not_awaited()


class TestQuotaResolver:
    @pytest.mark.asyncio
    async def test_fetches_and_parses_limited_response(self) -> None:
        http_client = _make_http_client(
            _make_response(200, {"team_id": 1, "limited": {"ai_credits": {"limited": True}}})
        )
        resolver = QuotaResolver(redis=None, http_client=http_client)

        status = await resolver.get_resource_status("ai_credits", team_id=42, auth_header="Bearer phx_test")

        assert status == QuotaResourceStatus(limited=True)
        http_client.get.assert_awaited_once()
        assert http_client.get.await_args.kwargs["headers"]["Authorization"] == "Bearer phx_test"

    @pytest.mark.asyncio
    async def test_fetches_and_parses_unlimited_response(self) -> None:
        http_client = _make_http_client(
            _make_response(200, {"team_id": 1, "limited": {"ai_credits": {"limited": False}}})
        )
        resolver = QuotaResolver(redis=None, http_client=http_client)

        status = await resolver.get_resource_status("ai_credits", team_id=42, auth_header="Bearer phx_test")

        assert status == QuotaResourceStatus(limited=False)

    @pytest.mark.asyncio
    async def test_4xx_fails_open_without_retrying(self) -> None:
        # 4xx is treated as a permanent failure for the lifetime of this request,
        # so we don't burn the retry budget on a token that won't fix itself.
        http_client = _make_http_client(_make_response(401, {"detail": "no auth"}))
        resolver = QuotaResolver(redis=None, http_client=http_client)

        status = await resolver.get_resource_status("ai_credits", team_id=42, auth_header="Bearer phx_test")

        assert status == QuotaResourceStatus(limited=False)
        http_client.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retries_on_5xx_and_succeeds(self) -> None:
        # A transient 503 is retried; the next attempt succeeds.
        http_client = _make_http_client_sequence(
            [
                _make_response(503, {}),
                _make_response(200, {"limited": {"ai_credits": {"limited": True}}}),
            ]
        )
        resolver = QuotaResolver(redis=None, http_client=http_client)

        status = await resolver.get_resource_status("ai_credits", team_id=42, auth_header="Bearer phx_test")

        assert status == QuotaResourceStatus(limited=True)
        assert http_client.get.await_count == 2

    @pytest.mark.asyncio
    async def test_retries_on_network_error_and_succeeds(self) -> None:
        http_client = _make_http_client_sequence(
            [
                httpx.ConnectError("boom"),
                _make_response(200, {"limited": {"ai_credits": {"limited": False}}}),
            ]
        )
        resolver = QuotaResolver(redis=None, http_client=http_client)

        status = await resolver.get_resource_status("ai_credits", team_id=42, auth_header="Bearer phx_test")

        assert status == QuotaResourceStatus(limited=False)
        assert http_client.get.await_count == 2

    @pytest.mark.asyncio
    async def test_gives_up_after_all_retries_and_fails_open(self) -> None:
        # Consecutive network errors exhaust the retry budget; we fall open
        # and cache the answer for the fail-open window.
        http_client = _make_http_client(httpx.ConnectError("boom"))
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()
        resolver = QuotaResolver(redis=redis, http_client=http_client)

        status = await resolver.get_resource_status("ai_credits", team_id=42, auth_header="Bearer phx_test")

        assert status == QuotaResourceStatus(limited=False)
        assert http_client.get.await_count == len(_RETRY_DELAYS_SECONDS)
        redis.set.assert_awaited_once()
        assert redis.set.await_args.kwargs.get("ex") == _FAIL_OPEN_CACHE_TTL_SECONDS

    @pytest.mark.asyncio
    async def test_uses_cached_result_and_skips_http(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=json.dumps({"limited": True}).encode())
        http_client = _make_http_client(_make_response(200))
        resolver = QuotaResolver(redis=redis, http_client=http_client)

        status = await resolver.get_resource_status("ai_credits", team_id=42, auth_header="Bearer phx_test")

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

        await resolver.get_resource_status("ai_credits", team_id=42, auth_header="Bearer phx_test")

        redis.set.assert_awaited_once()
        call = redis.set.await_args
        assert call.args[0] == _redis_key("ai_credits", 42)
        assert json.loads(call.args[1]) == {"limited": True}
        # Successful fetches use the gateway settings default of 5 minutes.
        assert call.kwargs.get("ex") == 300

    @pytest.mark.asyncio
    async def test_caches_fail_open_for_full_window_on_4xx(self) -> None:
        # 4xx responses (e.g. expired token) cache for the fail-open window so
        # a hot loop with a broken token doesn't hammer Django.
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()
        http_client = _make_http_client(_make_response(401, {"detail": "no auth"}))
        resolver = QuotaResolver(redis=redis, http_client=http_client)

        await resolver.get_resource_status("ai_credits", team_id=42, auth_header="Bearer phx_test")

        redis.set.assert_awaited_once()
        assert redis.set.await_args.kwargs.get("ex") == _FAIL_OPEN_CACHE_TTL_SECONDS
