from __future__ import annotations

from unittest.mock import patch

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


def _make_context(
    product: str,
    *,
    credits_exhausted: bool = False,
    plan_key: str | None = None,
    seat_missing: bool = False,
    code_usage_billed: bool = False,
) -> ThrottleContext:
    return ThrottleContext(
        user=_make_user(),
        product=product,
        credits_exhausted=credits_exhausted,
        plan_key=plan_key,
        seat_missing=seat_missing,
        code_usage_billed=code_usage_billed,
    )


class TestBillableCreditThrottle:
    @pytest.mark.asyncio
    async def test_allows_non_billable_product_even_when_exhausted(self) -> None:
        # `sherlockhog` is non-billable; exhaustion at the context level is
        # irrelevant — the throttle short-circuits before checking the flag.
        throttle = BillableCreditThrottle()

        result = await throttle.allow_request(_make_context(product="sherlockhog", credits_exhausted=True))

        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_denies_posthog_code_when_its_bucket_is_exhausted(self) -> None:
        # `posthog_code` bills into posthog_code_credits; the dependency layer
        # resolves exhaustion for that bucket, so the throttle blocks on it —
        # with the Code-specific message, not the PostHog AI one.
        throttle = BillableCreditThrottle()

        result = await throttle.allow_request(_make_context(product="posthog_code", credits_exhausted=True))

        assert result.allowed is False
        assert result.status_code == 429
        assert "PostHog Code usage limit" in result.detail

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("seat_missing", "code_usage_billed"),
        [
            # Seatless in a paying org: the org's billing limit is the only
            # ceiling (the per-user cap is lifted) - exhaustion must block, or
            # usage runs past the org's configured limit.
            (True, True),
            # Seatless in a non-paying org: the free plan's monthly allocation
            # surfaces the same way and must block the same way.
            (True, False),
            # Every generation is counted into the bucket regardless of seat
            # state, so a seat-based carve-out would let the exempted callers
            # burn past the limit their own spend is filling.
            (False, True),
            (False, False),
        ],
    )
    async def test_bucket_blocks_regardless_of_seat_or_billing_state(
        self, seat_missing: bool, code_usage_billed: bool
    ) -> None:
        throttle = BillableCreditThrottle()

        result = await throttle.allow_request(
            _make_context(
                product="posthog_code",
                credits_exhausted=True,
                seat_missing=seat_missing,
                code_usage_billed=code_usage_billed,
            )
        )

        assert result.allowed is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("product", ["slack_app", "slack_app_routing", "posthog_code"])
    async def test_allows_billable_product_when_not_exhausted(self, product: str) -> None:
        throttle = BillableCreditThrottle()

        result = await throttle.allow_request(_make_context(product=product, credits_exhausted=False))

        assert result.allowed is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("product", ["slack_app", "slack_app_routing"])
    async def test_denies_billable_product_when_exhausted(self, product: str) -> None:
        throttle = BillableCreditThrottle()

        result = await throttle.allow_request(_make_context(product=product, credits_exhausted=True))

        assert result.allowed is False
        assert result.status_code == 429
        assert result.scope == "billable_credits"
        assert "PostHog AI credits" in result.detail
        assert result.retry_after == 60

    @pytest.mark.asyncio
    async def test_unmapped_bucket_falls_back_to_generic_detail(self) -> None:
        # A bucket added to the enum without a detail entry must still deny
        # with a 429, not blow up with a KeyError.
        throttle = BillableCreditThrottle()

        with patch.dict("llm_gateway.rate_limiting.billable_credits_throttle._BUCKET_EXHAUSTED_DETAIL", clear=True):
            result = await throttle.allow_request(_make_context(product="posthog_code", credits_exhausted=True))

        assert result.allowed is False
        assert result.status_code == 429
        assert "reached its usage limit" in result.detail
