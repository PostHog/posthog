from __future__ import annotations

from llm_gateway.products.config import CreditBucket, get_product_config
from llm_gateway.rate_limiting.throttles import Throttle, ThrottleContext, ThrottleResult
from llm_gateway.services.plan_resolver import is_usage_based_plan

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


class BillableCreditThrottle(Throttle):
    """Gate bucket-billed LLM calls on the team's balance for that bucket.

    Reads ``credits_exhausted`` from :class:`ThrottleContext`, pre-resolved by
    the dependency layer for the product's own credit bucket (see
    ``resolve_quota_status``). Unbilled products (``credit_bucket=None``) are
    never blocked here. For a bucket scoped to usage-based plans (see
    ``ProductConfig.credit_bucket_scope``), only requests from a user on a
    usage-based plan are blocked when the bucket is exhausted — seat-covered
    users pass through regardless of the org's usage limit.
    """

    scope = "billable_credits"

    async def allow_request(self, context: ThrottleContext) -> ThrottleResult:
        config = get_product_config(context.product)
        if not (config and config.credit_bucket is not None):
            return ThrottleResult.allow()

        if not context.credits_exhausted:
            return ThrottleResult.allow()

        if config.credit_bucket_scope == "usage_based_plans" and not is_usage_based_plan(context.plan_key):
            # Seat-covered usage is excluded from the billed usage counter at the
            # usage-report layer, so the org's usage limit doesn't apply to these
            # users; blocking them would take Code away from free/pro seat holders
            # because of other users' usage-based spend. An unknown/missing plan_key
            # means NOT usage-based here too, i.e. not blocked — consistent with the
            # resolver's fail-open posture.
            return ThrottleResult.allow()

        return ThrottleResult.deny(
            detail=_BUCKET_EXHAUSTED_DETAIL.get(config.credit_bucket, _DEFAULT_EXHAUSTED_DETAIL),
            scope=self.scope,
            retry_after=_RETRY_AFTER_SECONDS,
        )
