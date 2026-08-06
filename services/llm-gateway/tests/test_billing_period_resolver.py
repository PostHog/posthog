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
        timeout=2.0,
    )
