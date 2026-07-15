from __future__ import annotations

from llm_gateway.products.config import CreditBucket, get_product_config
from llm_gateway.rate_limiting.throttles import Throttle, ThrottleContext, ThrottleResult

_BUCKET_EXHAUSTED_DETAIL = {
    CreditBucket.AI_CREDITS: (
        "Your team has used its monthly PostHog AI credits. "
        "Top up at https://app.posthog.com/organization/billing to continue."
    ),
    CreditBucket.POSTHOG_CODE_CREDITS: (
        "Your team has reached its PostHog Code usage limit for this billing period. "
        "See https://app.posthog.com/organization/billing for your usage and limits."
    ),
}

# Fallback for a bucket added to the enum without a matching entry above —
# a missing message should never turn an exhausted team's 429 into a 500.
_DEFAULT_EXHAUSTED_DETAIL = (
    "Your team has reached its usage limit for this billing period. "
    "See https://app.posthog.com/organization/billing for your usage and limits."
)

# Hint the client to back off for a minute. A precise expiry timestamp is
# available upstream in Redis, but with Django's 30s in-process cache and the
# gateway's 30s resolver cache stacked on top, any computed retry window would
# be 0–60s stale anyway — a fixed minute is no worse and cuts the data
# plumbing.
_RETRY_AFTER_SECONDS = 60


def bucket_block_applies(context: ThrottleContext) -> bool:
    """Whether the product's exhausted credit bucket blocks this caller.

    The single source of truth for the bucket-block decision, shared by the
    request-path throttle and the usage endpoint so what's reported always
    matches what's enforced. Unbilled products (``credit_bucket=None``) are
    never blocked. For a bucket scoped to seatless users (see
    ``ProductConfig.credit_bucket_scope``), seat holders are exempt — their
    usage is excluded from the org's usage counter at the usage-report layer,
    so the org's limit must not take the product away from them because of
    other users' spend. Seatless callers count against the bucket whether or
    not the org pays for the usage: a free org's monthly allocation and a
    paying org's billing limit both surface here as exhaustion. A caller whose
    seat state can't be resolved reads as seated (``seat_missing`` is only set
    on a definitive no-seat response), i.e. not blocked — consistent with the
    quota resolver's fail-open posture.
    """
    config = get_product_config(context.product)
    if not (config and config.credit_bucket is not None):
        return False
    if not context.credits_exhausted:
        return False
    if config.credit_bucket_scope == "seatless_users" and not context.seat_missing:
        return False
    return True


class BillableCreditThrottle(Throttle):
    """Gate bucket-billed LLM calls on the team's balance for that bucket.

    Reads ``credits_exhausted`` from :class:`ThrottleContext`, pre-resolved by
    the dependency layer for the product's own credit bucket (see
    ``resolve_quota_status``), and applies :func:`bucket_block_applies`.
    """

    scope = "billable_credits"

    async def allow_request(self, context: ThrottleContext) -> ThrottleResult:
        config = get_product_config(context.product)
        if config is None or config.credit_bucket is None:
            return ThrottleResult.allow()

        if not bucket_block_applies(context):
            return ThrottleResult.allow()

        return ThrottleResult.deny(
            detail=_BUCKET_EXHAUSTED_DETAIL.get(config.credit_bucket, _DEFAULT_EXHAUSTED_DETAIL),
            scope=self.scope,
            retry_after=_RETRY_AFTER_SECONDS,
        )
