from __future__ import annotations

import json
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from starlette.datastructures import Headers

from llm_gateway.services.quota_resolver import (
    _FAIL_OPEN_CACHE_TTL_SECONDS,
    _LAST_KNOWN_BILLING_TTL_SECONDS,
    _RETRY_DELAYS_SECONDS,
    QuotaResolver,
    QuotaResourceStatus,
    _billing_key,
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


class _FakeRedis:
    """Dict-backed get/set so multi-key round-trips are honest instead of stubbed."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def set(self, key: str, value: str | bytes, ex: int | None = None) -> None:
        self.store[key] = value if isinstance(value, bytes) else value.encode()
        if ex is not None:
            self.ttls[key] = ex


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
    async def test_parses_and_caches_code_usage_billing_flag(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()
        http_client = _make_http_client(
            _make_response(
                200,
                {"team_id": 1, "limited": {"ai_credits": {"limited": False}}, "code_usage_billing_active": True},
            )
        )
        resolver = QuotaResolver(redis=redis, http_client=http_client)

        status = await resolver.get_resource_status("ai_credits", team_id=42, auth_header="Bearer phx_test")
        assert status.code_usage_billing_active is True

        # Round-trips through the cache - a one-sided cache would flip a paying
        # user's cap between hit and miss.
        cached_payload = redis.set.call_args.args[1]
        redis.get = AsyncMock(return_value=cached_payload.encode())
        cached = await resolver.get_resource_status("ai_credits", team_id=42, auth_header="Bearer phx_test")
        assert cached.code_usage_billing_active is True

    @pytest.mark.asyncio
    async def test_missing_billing_field_defaults_false(self) -> None:
        # Old Django responses (pre-flag) must read as not-billed, not error.
        http_client = _make_http_client(
            _make_response(200, {"team_id": 1, "limited": {"ai_credits": {"limited": False}}})
        )
        resolver = QuotaResolver(redis=None, http_client=http_client)

        status = await resolver.get_resource_status("ai_credits", team_id=42, auth_header="Bearer phx_test")
        assert status.code_usage_billing_active is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("failure_mode", ["4xx", "retries_exhausted"])
    async def test_billing_flag_falls_back_to_last_known_value_on_fetch_failure(self, failure_mode: str) -> None:
        # A Django blip - or one caller's under-scoped token 4xxing the shared
        # per-team fetch - must not flip a paying org's billing bit to False
        # and re-cap its users at the free limit for the fail-open window.
        failures: list[httpx.Response | Exception]
        if failure_mode == "4xx":
            failures = [_make_response(403, {"detail": "missing scope"})]
        else:
            failures = [httpx.ConnectError("boom")] * len(_RETRY_DELAYS_SECONDS)
        http_client = _make_http_client_sequence(
            [
                _make_response(200, {"limited": {"ai_credits": {"limited": False}}, "code_usage_billing_active": True}),
                *failures,
            ]
        )
        redis = _FakeRedis()
        resolver = QuotaResolver(redis=redis, http_client=http_client)  # type: ignore[arg-type]

        first = await resolver.get_resource_status("ai_credits", team_id=42, auth_header="Bearer phx_test")
        assert first.code_usage_billing_active is True
        assert redis.ttls[_billing_key(42)] == _LAST_KNOWN_BILLING_TTL_SECONDS

        # The per-team quota entry expires; the refetch fails.
        del redis.store[_redis_key("ai_credits", 42)]
        status = await resolver.get_resource_status("ai_credits", team_id=42, auth_header="Bearer phx_test")

        assert status == QuotaResourceStatus(limited=False, code_usage_billing_active=True)
        if failure_mode == "retries_exhausted":
            assert json.loads(redis.store[_redis_key("ai_credits", 42)]) == {
                "limited": False,
                "code_usage_billing_active": True,
            }
            assert redis.ttls[_redis_key("ai_credits", 42)] == _FAIL_OPEN_CACHE_TTL_SECONDS
        else:
            # 4xx is caller-specific and must not repopulate the shared entry.
            assert _redis_key("ai_credits", 42) not in redis.store

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

        # One write per key: the team+resource quota entry and the per-team
        # last-known billing bit.
        quota_writes = [c for c in redis.set.await_args_list if c.args[0] == _redis_key("ai_credits", 42)]
        assert len(quota_writes) == 1
        call = quota_writes[0]
        assert json.loads(call.args[1]) == {"limited": True, "code_usage_billing_active": False}
        # Successful fetches use the gateway settings default of 5 minutes.
        assert call.kwargs.get("ex") == 300
        assert redis.set.await_count == 2

    @pytest.mark.asyncio
    async def test_does_not_cache_on_4xx(self) -> None:
        # Caching a 4xx team-wide would let a caller who can 403 the quota
        # endpoint pin limited=False for everyone on the team.
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()
        http_client = _make_http_client(_make_response(401, {"detail": "no auth"}))
        resolver = QuotaResolver(redis=redis, http_client=http_client)

        status = await resolver.get_resource_status("ai_credits", team_id=42, auth_header="Bearer phx_test")

        assert status == QuotaResourceStatus(limited=False)
        redis.set.assert_not_awaited()
