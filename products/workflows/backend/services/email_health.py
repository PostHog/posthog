"""The email reputation page: sending rates, the AWS SES tenant verdict, the per-ISP breakdown and
the sending allowance."""

import hashlib
from collections.abc import Collection, Mapping
from datetime import datetime, timedelta
from typing import Any

from django.core.cache import cache
from django.utils import timezone

import structlog

from posthog.api.app_metrics2 import fetch_app_metric_totals_by_source, fetch_app_metric_totals_by_team_and_source

from products.workflows.backend.facade.contracts import (
    EMAIL_HEALTH_METRIC_NAMES,
    EmailSendingAllowance,
    FlowEmailTotals,
)
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.providers.ses import SESProvider
from products.workflows.backend.services.email_sending_attribution import fold_email_totals_by_flow
from products.workflows.backend.utils.email_sending_tiers import max_email_sending_tier, resolve_team_email_sending_tier

logger = structlog.get_logger(__name__)


def fetch_email_totals_by_source(team_id: int, window_days: int) -> dict[str, dict[str, int]]:
    # Cached briefly: the UI reloads per search keystroke, but search filters in Python - the
    # ClickHouse totals are search-independent. Session-authenticated requests bypass the
    # default (personal-API-key-only) ClickHouse throttles, so without this a member could
    # re-run the 30-day aggregation on every request.
    totals_cache_key = f"workflows_email_reputation_totals_{team_id}"
    totals_by_source = cache.get(totals_cache_key)
    if totals_by_source is None:
        after = timezone.now() - timedelta(days=window_days)
        totals_by_source = fetch_app_metric_totals_by_source(
            team_id=team_id,
            app_source="hog_flow",
            after=after,
            name=EMAIL_HEALTH_METRIC_NAMES,
        )
        cache.set(totals_cache_key, totals_by_source, 60)
    return totals_by_source


def fold_email_totals(
    *, team_id: int, totals_by_source: Mapping[str, Mapping[str, int]], flow_ids: Collection[str]
) -> FlowEmailTotals:
    return fold_email_totals_by_flow(
        team_id=team_id,
        totals_by_source=totals_by_source,
        flows=HogFlow.objects.filter(team_id=team_id, id__in=list(flow_ids)),
    )


SENDING_ALLOWANCE_CACHE_SECONDS = 60


def team_email_sending_allowance(team_id: int) -> EmailSendingAllowance:
    """
    Usage comes from the send metrics rather than the worker's token buckets, so the numbers match
    what the rest of this page reports. Cached briefly because the endpoint reloads on every search
    keystroke while these two aggregations do not depend on the search.
    """
    # Entries are pickles: bump the version when EmailSendingAllowance changes module or shape.
    cache_key = f"workflows_email_sending_allowance_v2_{team_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    resolved = resolve_team_email_sending_tier(team_id)
    now = timezone.now()
    allowance = EmailSendingAllowance(
        tier=resolved.tier,
        max_tier=max_email_sending_tier(),
        emails_per_hour=resolved.limits.per_hour,
        emails_per_day=resolved.limits.per_day,
        max_batch_audience=resolved.limits.max_batch_audience,
        emails_sent_last_hour=_team_email_sends_since(team_id, now - timedelta(hours=1)),
        emails_sent_last_day=_team_email_sends_since(team_id, now - timedelta(days=1)),
        enforced=resolved.enforced,
    )
    cache.set(cache_key, allowance, SENDING_ALLOWANCE_CACHE_SECONDS)
    return allowance


def _team_email_sends_since(team_id: int, after: datetime) -> int:
    totals = fetch_app_metric_totals_by_team_and_source(
        app_source="hog_flow", name=["email_sent"], after=after, team_ids=[team_id]
    )
    return sum(counts.get("email_sent", 0) for counts in totals.get(team_id, {}).values())


AWS_TENANT_REPUTATION_CACHE_SECONDS = 5 * 60
# Failures cache too, but far shorter than successes: long enough that an unreachable SES isn't
# re-dialled on every request, short enough that a just-fixed config recovers within a minute.
AWS_TENANT_REPUTATION_ERROR_CACHE_SECONDS = 60


def _aws_tenant_health(sending_status: str, reputation_impact: str | None) -> str:
    if sending_status == "DISABLED":
        return "suspended"
    if reputation_impact == "HIGH":
        return "critical"
    if reputation_impact == "LOW":
        return "warning"
    return "healthy"


def fetch_aws_tenant_reputation(team_id: int) -> dict[str, Any] | None:
    """
    AWS-side tenant state for the reputation endpoint, cached briefly: the endpoint reloads on every
    search keystroke and three SES API round-trips per keystroke would be slow and rate-limited.
    Failures return None (the response field is nullable) so AWS being unreachable never breaks the
    rates display; failures cache under a shorter TTL so a broken SES isn't re-dialled per request.

    Deliberately no SES_ACCESS_KEY_ID gate: cloud pods authenticate via their IAM role and leave
    the key env vars unset, so a key check reads as "SES not configured" exactly where SES IS
    configured. Environments truly without SES fail the call and land in the error path below.
    """
    cache_key = f"workflows_ses_tenant_reputation_{team_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached["value"]
    try:
        raw = SESProvider().get_tenant_reputation(team_id)
    except Exception:
        logger.exception("Failed to fetch SES tenant reputation", team_id=team_id)
        cache.set(cache_key, {"value": None}, AWS_TENANT_REPUTATION_ERROR_CACHE_SECONDS)
        return None
    value = (
        {
            "health": _aws_tenant_health(raw["sending_status"], raw["reputation_impact"]),
            "sending_status": raw["sending_status"],
            "findings": raw["findings"],
        }
        if raw is not None
        else None
    )
    cache.set(cache_key, {"value": value}, AWS_TENANT_REPUTATION_CACHE_SECONDS)
    return value


# VDM aggregates by whole day and the window ends at the last UTC midnight, so these numbers move
# at most once a day. A five-minute TTL bought nothing and cost a full fan-out on every expiry.
# One refresh of five domains is 150 queries across 15 sequential BatchGetMetricData calls, and the
# endpoint reloads on every search keystroke, so this is what keeps typing a workflow name from
# costing a fan-out per character.
ISP_METRICS_CACHE_SECONDS = 30 * 60
# A failure is cached too, briefly: without it an unreachable SES is retried in full per keystroke.
ISP_METRICS_ERROR_CACHE_SECONDS = 60
# Held while one request does the fan-out so a cold key admits one, not all of them. Typing races
# concurrent misses through the same key, and each miss can hold a worker for the whole query
# budget. Longer than that budget, so the holder always outlives its own work.
ISP_METRICS_REFRESH_LOCK_SECONDS = 30
# Bounds the BatchGetMetricData fan-out: every extra domain costs one query per provider per
# metric. A project with more sending domains gets a breakdown over its first few.
ISP_METRICS_MAX_DOMAINS = 5


def fetch_isp_metrics(team_id: int, window_days: int, domains: list[str]) -> list[dict[str, Any]]:
    """
    Per-mailbox-provider sending health for the given sending domains, cached like the tenant
    reputation above and for the same reason: the endpoint reloads on every search keystroke.

    Returns an empty list rather than raising when SES is unreachable or VDM is not collecting yet,
    because the breakdown adds to the rates display and must not stop it loading.
    """
    if not domains:
        return []
    # The domain set depends on what the caller may see, so it belongs in the key: two members of
    # one project can be entitled to different domains, and one must not be served the other's.
    domain_key = hashlib.sha256("|".join(domains).encode()).hexdigest()[:12]
    cache_key = f"workflows_ses_isp_metrics_{team_id}_{window_days}_{domain_key}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached["value"]

    # Losers show no breakdown rather than queueing behind the holder: the rates above are what the
    # page is for, and a second fan-out would buy a number the next reload gets from cache anyway.
    if not cache.add(f"{cache_key}_refreshing", True, ISP_METRICS_REFRESH_LOCK_SECONDS):
        return []

    try:
        rows = SESProvider().get_identity_isp_metrics(
            domains, window_days=window_days, max_domains=ISP_METRICS_MAX_DOMAINS
        )
    except Exception:
        logger.exception("Failed to fetch SES per-ISP metrics", team_id=team_id)
        cache.set(cache_key, {"value": []}, ISP_METRICS_ERROR_CACHE_SECONDS)
        return []

    value = [
        {
            "isp": row.isp,
            "emails_sent": row.emails_sent,
            "delivery_rate": row.delivery_rate,
            "bounce_rate": row.bounce_rate,
            "transient_bounce_rate": row.transient_bounce_rate,
            "complaint_rate": row.complaint_rate,
            "complaint_base": row.complaint_base,
            "unavailable": list(row.unavailable),
        }
        for row in rows
    ]
    cache.set(cache_key, {"value": value}, ISP_METRICS_CACHE_SECONDS)
    return value
