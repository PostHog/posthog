from __future__ import annotations

import pytest

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.rate_limiting.billable_credits_throttle import BillableCreditThrottle
from llm_gateway.rate_limiting.throttles import ThrottleContext


def _make_user() -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=1,
        team_id=42,
        auth_method="personal_api_key",
        distinct_id="distinct-1",
        scopes=["llm_gateway:read"],
    )


def _make_context(product: str, *, ai_credits_exhausted: bool = False) -> ThrottleContext:
    return ThrottleContext(user=_make_user(), product=product, ai_credits_exhausted=ai_credits_exhausted)


class TestBillableCreditThrottle:
    @pytest.mark.asyncio
    async def test_allows_non_billable_product_even_when_exhausted(self) -> None:
        # `sherlockhog` is non-billable; exhaustion at the context level is
        # irrelevant — the throttle short-circuits before checking the flag.
        throttle = BillableCreditThrottle()

        result = await throttle.allow_request(_make_context(product="sherlockhog", ai_credits_exhausted=True))

        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_allows_product_billing_outside_ai_credits_even_when_exhausted(self) -> None:
        # `posthog_code` bills into the posthog_code_credits bucket, not the
        # PostHog AI one, so the ai_credits quota must never block it.
        throttle = BillableCreditThrottle()

        result = await throttle.allow_request(_make_context(product="posthog_code", ai_credits_exhausted=True))

        assert result.allowed is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("product", ["slack_app", "slack_app_routing"])
    async def test_allows_billable_product_when_not_exhausted(self, product: str) -> None:
        throttle = BillableCreditThrottle()

        result = await throttle.allow_request(_make_context(product=product, ai_credits_exhausted=False))

        assert result.allowed is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("product", ["slack_app", "slack_app_routing"])
    async def test_denies_billable_product_when_exhausted(self, product: str) -> None:
        throttle = BillableCreditThrottle()

        result = await throttle.allow_request(_make_context(product=product, ai_credits_exhausted=True))

        assert result.allowed is False
        assert result.status_code == 429
        assert result.scope == "billable_credits"
        assert "PostHog AI credits" in result.detail
        assert result.retry_after == 60
