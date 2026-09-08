"""Assemble what `/usage` answers: this conversation, this product, and all of PostHog AI.

Every surface that offers the command — the Max chat, the Slack app, a cloud agent — reports the
same three numbers over the same period, so a person reading one recognizes the others.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from django.core.cache import cache
from django.utils import timezone

from posthog.schema import MaxBillingContext

from posthog.dataclasses import frozen
from posthog.tasks.usage_report import POSTHOG_AI_PRODUCTS, POSTHOG_CODE_AI_PRODUCTS

from products.posthog_ai.backend.services.usage.credits import (
    AiUsagePeriod,
    ProductUsage,
    format_usage_message,
    get_ai_credits,
    get_ai_credits_for_conversation,
    get_ai_credits_for_team,
    get_ai_free_tier_credits,
    get_ai_usage_period,
    get_conversation_start_time,
)

from ee.billing.quota_limiting import QuotaResource, organization_resource_usage

if TYPE_CHECKING:
    from posthog.models import Team

# What a person calls the product a surface belongs to. A product missing here reads as its
# `ai_product` slug, which is still recognizable.
PRODUCT_LABELS = {
    "alert_investigation_agent": "Alert investigation",
    "posthog_ai": "PostHog AI",
    "posthog_code": "PostHog Desktop",
    "product_analytics": "Product analytics",
    "replay_vision": "Replay vision",
    "slack_app": "Slack app",
    "subscriptions": "Subscriptions",
    "surveys": "Surveys",
}

# Products billed against their own credit counter, read from billing rather than summed from
# events. Billing is region-independent, which is what makes the row correct on both deployments:
# Desktop generations are only readable from the US.
SEPARATE_CREDIT_BUCKETS = dict.fromkeys(POSTHOG_CODE_AI_PRODUCTS, QuotaResource.POSTHOG_CODE_CREDITS)

# Long enough to collapse a person re-asking, short enough that a report still tracks a run in
# progress. `get_task_usage` caches its own ClickHouse read for the same span.
REPORT_CACHE_TIMEOUT_SECONDS = 60


def product_label(product: str) -> str:
    return PRODUCT_LABELS.get(product, product.replace("_", " "))


@frozen
class UsageReport:
    # None where the surface has no conversation in scope, which reads as unknown rather than as a
    # conversation that spent nothing.
    conversation_credits: Optional[int]
    period_credits: int
    free_tier_credits: int
    usage_period: AiUsagePeriod
    conversation_start: Optional[datetime] = None
    product: Optional[ProductUsage] = None

    @property
    def remaining_credits(self) -> int:
        return self.free_tier_credits - self.period_credits

    @property
    def message(self) -> str:
        return format_usage_message(
            conversation_credits=self.conversation_credits,
            period_credits=self.period_credits,
            free_tier_credits=self.free_tier_credits,
            conversation_start=self.conversation_start,
            usage_period=self.usage_period,
            product_usage=self.product,
        )


def build_usage_report(
    team: "Team",
    *,
    conversation_id: Optional[UUID] = None,
    conversation_started_at: Optional[datetime] = None,
    product: Optional[str] = None,
    billing_context: MaxBillingContext | dict[str, object] | None = None,
) -> UsageReport:
    """The three usage numbers for one team, as of now.

    `conversation_id` is the `$ai_session_id` every generation of a conversation carries — the Max
    conversation for a chat, the task for an agent run. A caller that knows when its conversation
    started passes it, because only a Max conversation can be looked up here; without one the
    reported period bounds the search.

    The answer is cached briefly. Credits are reported from ingested traces, which lag anyway, so a
    caller asking twice in a minute reads the same numbers either way and pays for one set of scans.
    """
    cache_key = _cache_key(team.id, conversation_id, product)
    cached = cache.get(cache_key)
    if isinstance(cached, UsageReport):
        return cached

    report = _build_usage_report(
        team,
        conversation_id=conversation_id,
        conversation_started_at=conversation_started_at,
        product=product,
        billing_context=billing_context,
    )
    cache.set(cache_key, report, timeout=REPORT_CACHE_TIMEOUT_SECONDS)
    return report


def _cache_key(team_id: int, conversation_id: Optional[UUID], product: Optional[str]) -> str:
    return f"ai_usage_report:v1:{team_id}:{conversation_id or '-'}:{product or '-'}"


def _build_usage_report(
    team: "Team",
    *,
    conversation_id: Optional[UUID] = None,
    conversation_started_at: Optional[datetime] = None,
    product: Optional[str] = None,
    billing_context: MaxBillingContext | dict[str, object] | None = None,
) -> UsageReport:
    usage_period = get_ai_usage_period(team, billing_context)
    period_has_run = usage_period.query_start < usage_period.end

    conversation_start = conversation_started_at
    if conversation_start is None and conversation_id is not None:
        conversation_start = get_conversation_start_time(conversation_id)

    conversation_credits = (
        get_ai_credits_for_conversation(
            team_id=team.id,
            conversation_id=conversation_id,
            begin=conversation_start or usage_period.query_start,
            end=timezone.now(),
        )
        if conversation_id is not None
        else None
    )

    period_credits = (
        get_ai_credits_for_team(team_id=team.id, begin=usage_period.query_start, end=usage_period.end)
        if period_has_run
        else 0
    )

    return UsageReport(
        conversation_credits=conversation_credits,
        period_credits=period_credits,
        free_tier_credits=get_ai_free_tier_credits(team.id),
        usage_period=usage_period,
        conversation_start=conversation_start,
        product=_product_usage(team, product, usage_period) if product else None,
    )


def _product_usage(team: "Team", product: str, usage_period: AiUsagePeriod) -> Optional[ProductUsage]:
    """What one product spent over the reported period, or None when it has no credit counter."""
    if product in POSTHOG_AI_PRODUCTS:
        credits = (
            get_ai_credits(team.id, usage_period.query_start, usage_period.end, ai_products=[product])
            if usage_period.query_start < usage_period.end
            else 0
        )
        return ProductUsage(label=product_label(product), credits=credits, separate_bucket=False)

    bucket = SEPARATE_CREDIT_BUCKETS.get(product)
    if bucket is None:
        return None

    used = organization_resource_usage(team.organization, bucket)
    if used is None:
        # Billing has never synced the bucket. Absent reads as unknown; 0 would read as unspent.
        return None
    return ProductUsage(label=product_label(product), credits=round(used), separate_bucket=True)
