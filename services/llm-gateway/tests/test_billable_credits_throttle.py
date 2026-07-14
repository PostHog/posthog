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


def _make_context(product: str, *, credits_exhausted: bool = False, plan_key: str | None = None) -> ThrottleContext:
    return ThrottleContext(user=_make_user(), product=product, credits_exhausted=credits_exhausted, plan_key=plan_key)


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
        # `posthog_code` bills into posthog_code_credits, scoped to usage-based-plan
        # users; the dependency layer resolves exhaustion for that bucket, so the
        # throttle blocks a usage-based-plan user on it — with the Code-specific
        # message, not the PostHog AI one.
        throttle = BillableCreditThrottle()

        result = await throttle.allow_request(
            _make_context(product="posthog_code", credits_exhausted=True, plan_key="posthog-code-usage-20260709")
        )

        assert result.allowed is False
        assert result.status_code == 429
        assert "PostHog Code usage limit" in result.detail

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "plan_key",
        ["posthog-code-pro-200-20260301", "posthog-code-free-20260301", None],
    )
    async def test_allows_posthog_code_seat_covered_plans_even_when_exhausted(self, plan_key: str | None) -> None:
        # `posthog_code`'s bucket is scoped to usage-based plans: seat-covered
        # (pro/free/alpha) users' generations aren't billed to the org's usage
        # subscription at the usage-report layer, so the org's usage limit must not
        # block them either — including when the plan can't be resolved at all.
        throttle = BillableCreditThrottle()

        result = await throttle.allow_request(
            _make_context(product="posthog_code", credits_exhausted=True, plan_key=plan_key)
        )

        assert result.allowed is True

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
    @pytest.mark.parametrize("plan_key", ["posthog-code-pro-200-20260301", "posthog-code-free-20260301", None])
    async def test_denies_all_users_scope_product_regardless_of_plan_key(self, plan_key: str | None) -> None:
        # `slack_app` bills AI_CREDITS with the default `credit_bucket_scope="all_users"`:
        # unlike posthog_code, every user counts against the bucket limit, so exhaustion
        # blocks the request no matter what plan (or lack of one) the caller is on.
        throttle = BillableCreditThrottle()

        result = await throttle.allow_request(
            _make_context(product="slack_app", credits_exhausted=True, plan_key=plan_key)
        )

        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_unmapped_bucket_falls_back_to_generic_detail(self) -> None:
        # A bucket added to the enum without a detail entry must still deny
        # with a 429, not blow up with a KeyError.
        throttle = BillableCreditThrottle()

        with patch.dict("llm_gateway.rate_limiting.billable_credits_throttle._BUCKET_EXHAUSTED_DETAIL", clear=True):
            result = await throttle.allow_request(
                _make_context(product="posthog_code", credits_exhausted=True, plan_key="posthog-code-usage-20260709")
            )

        assert result.allowed is False
        assert result.status_code == 429
        assert "reached its usage limit" in result.detail
