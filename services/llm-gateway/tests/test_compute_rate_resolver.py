import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from llm_gateway.services.compute_rate_resolver import (
    ComputeRateResolver,
    ComputeRateStatus,
    _redis_key,
    resolve_compute_rates,
)


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


def _response(payload: object, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code, content=json.dumps(payload).encode(), request=httpx.Request("GET", "http://test")
    )


@pytest.mark.asyncio
async def test_rates_round_trip_through_the_existing_freshness_window() -> None:
    payload = {
        "rate_cards": [
            {
                "version": "2026-07-15",
                "effective_at": "2026-07-15T00:00:00Z",
                "expires_at": None,
                "cpu_usd_per_core_second": "0.00001234",
                "memory_usd_per_gib_second": "0.00000567",
            }
        ],
        "error": None,
    }
    redis = _FakeRedis()
    http_client = MagicMock()
    http_client.get = AsyncMock(return_value=_response(payload))
    resolver = ComputeRateResolver(redis=redis, http_client=http_client)  # type: ignore[arg-type]

    first = await resolver.get_rates(42, "Bearer phx_test")
    cached = await resolver.get_rates(42, "Bearer phx_test")

    assert first == cached == ComputeRateStatus(rate_cards=payload["rate_cards"])
    assert redis.ttls[_redis_key(42)] == 300
    http_client.get.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"rate_cards": [], "error": None}, ComputeRateStatus(rate_cards=[])),
        (
            {"rate_cards": None, "error": "invalid_configuration"},
            ComputeRateStatus(rate_cards=None, error="invalid_configuration"),
        ),
    ],
)
async def test_inactive_or_invalid_configuration_is_cached_without_rates(
    payload: dict[str, object], expected: ComputeRateStatus
) -> None:
    redis = _FakeRedis()
    http_client = MagicMock()
    http_client.get = AsyncMock(return_value=_response(payload))
    resolver = ComputeRateResolver(redis=redis, http_client=http_client)  # type: ignore[arg-type]

    status = await resolver.get_rates(42, "Bearer phx_test")

    assert status == expected


@pytest.mark.asyncio
async def test_upstream_failure_preserves_the_usage_response() -> None:
    request = MagicMock()
    request.headers = {"Authorization": "Bearer phx_test"}
    request.app.state.compute_rate_resolver.get_rates = AsyncMock(side_effect=httpx.ConnectError("unavailable"))

    with patch("llm_gateway.services.compute_rate_resolver.upstream_auth_header", return_value="Bearer phx_test"):
        status = await resolve_compute_rates(request, 42)

    assert status == ComputeRateStatus()
