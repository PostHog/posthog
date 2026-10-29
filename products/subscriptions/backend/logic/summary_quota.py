"""The organization-wide cap on active AI summaries, and the cached count the API reports against it."""

import uuid

from django.core.cache import cache

import posthoganalytics

from posthog.models.organization import Organization
from posthog.resource_limits import LimitKey, get_organization_limit

from products.subscriptions.backend.facade.contracts import SubscriptionQuotaExceededError, SummaryQuota
from products.subscriptions.backend.models.subscription import Subscription

SUMMARY_QUOTA_CACHE_TTL_SECONDS = 60
SUMMARY_CAP_HIT_DEDUPE_TTL_SECONDS = 600


def _summary_quota_cache_key(organization_id: uuid.UUID) -> str:
    return f"subscription:summary_quota:org:{organization_id}"


def _summary_cap_hit_dedupe_key(organization_id: uuid.UUID) -> str:
    return f"subscription:summary_cap_hit:org:{organization_id}"


def count_active_summaries(organization: Organization) -> int:
    """Count subscriptions with summary_enabled=True (and not soft-deleted) across
    every team in this organization. Single source of truth for both the cap-check
    in the serializer and the `summary_quota` action endpoint."""
    return Subscription.objects.filter(
        team__organization_id=organization.id,
        summary_enabled=True,
        deleted=False,
    ).count()


def invalidate_summary_quota_cache(organization_id: uuid.UUID) -> None:
    cache.delete(_summary_quota_cache_key(organization_id))


def summary_quota(organization: Organization) -> SummaryQuota:
    cache_key = _summary_quota_cache_key(organization.id)
    cached = cache.get(cache_key)
    if cached is not None:
        return SummaryQuota(active_count=cached["active_count"], limit=cached["limit"], at_limit=cached["at_limit"])

    active_count = count_active_summaries(organization)
    limit = get_organization_limit(
        organization=organization,
        key=LimitKey.MAX_ACTIVE_AI_SUMMARIES_PER_ORG,
    )
    at_limit = limit is not None and active_count >= limit
    payload = {
        "active_count": active_count,
        "limit": limit,
        "at_limit": at_limit,
    }
    cache.set(cache_key, payload, SUMMARY_QUOTA_CACHE_TTL_SECONDS)
    return SummaryQuota(active_count=active_count, limit=limit, at_limit=at_limit)


def validate_summary_enabled_org_limit(
    organization: Organization, *, team_id: int, caller_distinct_id: str, is_create: bool
) -> None:
    # Already-on subscriptions stay on for grandfathered orgs already over
    # the cap; the becoming-active check in validate() ensures we only get
    # here when the row is transitioning into the active-summary state.
    limit = get_organization_limit(
        organization=organization,
        key=LimitKey.MAX_ACTIVE_AI_SUMMARIES_PER_ORG,
    )
    if limit is None:
        return

    active_count = count_active_summaries(organization)
    if active_count >= limit:
        _capture_summary_cap_hit(
            organization,
            active_count,
            limit,
            team_id=team_id,
            caller_distinct_id=caller_distinct_id,
            is_create=is_create,
        )
        raise SubscriptionQuotaExceededError(
            f"Your plan allows up to {limit} active AI summaries. "
            "Disable an existing summary or upgrade your plan to add more."
        )


def _capture_summary_cap_hit(
    organization: Organization,
    active_count: int,
    limit: int,
    *,
    team_id: int,
    caller_distinct_id: str,
    is_create: bool,
) -> None:
    # Rate-limited to one event per org per 10 minutes so a misbehaving
    # client retrying in a loop doesn't spam the analytics stream. Within
    # that window the user-visible 402 still fires every time.
    dedupe_key = _summary_cap_hit_dedupe_key(organization.id)
    if cache.get(dedupe_key):
        return
    cache.set(dedupe_key, True, SUMMARY_CAP_HIT_DEDUPE_TTL_SECONDS)

    try:
        posthoganalytics.capture(
            distinct_id=caller_distinct_id,
            event="subscription_ai_summary_cap_hit",
            properties={
                "team_id": team_id,
                "organization_id": str(organization.id),
                "active_count": active_count,
                "limit": limit,
                "is_create": is_create,
            },
            groups={"organization": str(organization.id)},
        )
    except Exception:
        # Telemetry must never poison the validation path.
        pass
