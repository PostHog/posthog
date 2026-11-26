from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from llm_gateway.services.billing_period_resolver import BillingPeriodResolver, OrganizationBillingPeriod


@pytest.mark.asyncio
async def test_fetches_the_local_billing_period_endpoint() -> None:
    response = httpx.Response(
        200,
        json={
            "current_period_start": "2026-07-09T00:00:00Z",
            "current_period_end": "2026-08-09T00:00:00Z",
        },
        request=httpx.Request("GET", "https://us.posthog.com/api/billing/period/"),
    )
    http_client = MagicMock()
    http_client.get = AsyncMock(return_value=response)
    resolver = BillingPeriodResolver(redis=None, http_client=http_client)

    period = await resolver.get_period(team_id=42, auth_header="Bearer phx_test")

    assert period == OrganizationBillingPeriod(
        current_period_start="2026-07-09T00:00:00Z",
        current_period_end="2026-08-09T00:00:00Z",
    )
    http_client.get.assert_awaited_once_with(
        "https://us.posthog.com/api/billing/period/",
        headers={"Authorization": "Bearer phx_test"},
        params={"team_id": 42},
        timeout=2.0,
    )


@pytest.mark.asyncio
async def test_malformed_response_falls_open() -> None:
    response = httpx.Response(
        200,
        content=b"not json",
        request=httpx.Request("GET", "https://us.posthog.com/api/billing/period/"),
    )
    http_client = MagicMock()
    http_client.get = AsyncMock(return_value=response)
    resolver = BillingPeriodResolver(redis=None, http_client=http_client)

    assert await resolver.get_period(team_id=42, auth_header="Bearer phx_test") is None


@pytest.mark.asyncio
async def test_caches_a_successful_missing_period() -> None:
    response = httpx.Response(
        200,
        json={"current_period_start": None, "current_period_end": None},
        request=httpx.Request("GET", "https://us.posthog.com/api/billing/period/"),
    )
    redis = AsyncMock()
    redis.get.side_effect = [None, b'{"current_period_start": null, "current_period_end": null}']
    http_client = MagicMock()
    http_client.get = AsyncMock(return_value=response)
    resolver = BillingPeriodResolver(redis=redis, http_client=http_client)

    assert await resolver.get_period(team_id=42, auth_header="Bearer phx_test") is None
    assert await resolver.get_period(team_id=42, auth_header="Bearer phx_test") is None
    http_client.get.assert_awaited_once()
    redis.set.assert_awaited_once()
