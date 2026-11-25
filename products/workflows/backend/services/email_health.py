"""The email reputation page: sending rates, the AWS SES tenant verdict, the per-ISP breakdown, the
sending allowance and the shared infrastructure's health."""

import math
import hashlib
from collections.abc import Collection, Mapping
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

import structlog
import posthoganalytics

from posthog.api.app_metrics2 import fetch_app_metric_totals_by_source, fetch_app_metric_totals_by_team_and_source
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature
from posthog.integrations import CrossTeamFilter, IntegrationManager
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.team.team import Team

from products.workflows.backend.facade.contracts import (
    EMAIL_HEALTH_METRIC_NAMES,
    EmailInfrastructureHealth,
    EmailSendingAllowance,
    EmailSendingAllowanceChange,
    EmailSendingNextTier,
    EmailSendingRecentRates,
    FlowEmailTotals,
)
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig
from products.workflows.backend.providers.ses import IspSendingMetrics, SESProvider
from products.workflows.backend.services.email_sending_attribution import fold_email_totals_by_flow
from products.workflows.backend.services.email_sending_tier import TeamSendingHistory, build_sending_history_windows
from products.workflows.backend.services.email_sending_tier_audit import EMAIL_SENDING_TIER_CHANGED_ACTIVITY
from products.workflows.backend.utils.batch_trigger_limit import resolve_batch_audience_limit
from products.workflows.backend.utils.email_sending_tiers import (
    get_email_sending_tier_limits,
    max_email_sending_tier,
    min_days_at_tier,
    resolve_team_email_sending_tier,
)

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
    keystroke while these reads do not depend on the search.
    """
    # Entries are pickles: bump the version when EmailSendingAllowance changes module or shape.
    cache_key = f"workflows_email_sending_allowance_v6_{team_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    resolved = resolve_team_email_sending_tier(team_id)
    rate_limited = resolve_batch_audience_limit(team_id).rate_limited
    now = timezone.now()
    next_tier, recent_rates = (
        (None, None) if resolved.pinned else _next_tier_and_recent_rates(team_id, resolved.tier, now)
    )
    allowance = EmailSendingAllowance(
        tier=resolved.tier,
        max_tier=max_email_sending_tier(),
        emails_per_day=resolved.limits.per_day,
        max_batch_audience=resolved.limits.max_batch_audience,
        emails_sent_last_day=_team_email_sends_since(team_id, now - timedelta(days=1)),
        enforced=resolved.enforced,
        rate_limited_max_batch_audience=rate_limited.limit if rate_limited else None,
        next_tier=next_tier,
        recent_rates=recent_rates,
        recent_changes=_recent_allowance_changes(team_id, now),
    )
    cache.set(cache_key, allowance, SENDING_ALLOWANCE_CACHE_SECONDS)
    return allowance


def _next_tier_and_recent_rates(
    team_id: int, tier: int, now: datetime
) -> tuple[EmailSendingNextTier | None, EmailSendingRecentRates]:
    """Reads the same history and anchor as the daily check, so the page shows what its next run
    looks at: the use bar and time at tier for the next step, and the demotion window's rates."""
    windows = build_sending_history_windows(
        after=now - timedelta(days=settings.WORKFLOWS_EMAIL_TIER_RATE_WINDOW_DAYS),
        recent_after=now - timedelta(days=settings.WORKFLOWS_EMAIL_TIER_DEMOTION_WINDOW_DAYS),
        team_ids=[team_id],
        feature=Feature.QUERY,
        workload=Workload.ONLINE,
    )
    empty = TeamSendingHistory(team_id=team_id, sent=0, hard_bounced=0, complained=0, auto_paused=False, daily_sends={})
    recent = windows.recent.get(team_id, empty)
    recent_rates = EmailSendingRecentRates(
        window_days=settings.WORKFLOWS_EMAIL_TIER_DEMOTION_WINDOW_DAYS,
        emails_sent=recent.sent,
        bounce_rate=recent.hard_bounce_rate,
        complaint_rate=recent.complaint_rate,
        max_bounce_rate=settings.WORKFLOWS_EMAIL_TIER_MAX_BOUNCE_RATE,
        max_complaint_rate=settings.WORKFLOWS_EMAIL_TIER_MAX_COMPLAINT_RATE,
        complaints=recent.complained,
        bounces_within_limits=recent.bounces_are_clean,
        complaints_within_limits=recent.complaints_are_clean,
    )
    if tier >= max_email_sending_tier():
        return None, recent_rates

    anchor = (
        TeamWorkflowsConfig.objects.filter(team_id=team_id)
        .values_list("email_sending_tier_updated_at", flat=True)
        .first()
    ) or Team.objects.only("created_at").get(id=team_id).created_at
    daily_target = math.ceil(
        get_email_sending_tier_limits(tier).per_day * settings.WORKFLOWS_EMAIL_TIER_MIN_DAILY_USE_RATIO
    )
    # The anchor day holds sends from before the change, so the daily check never counts it.
    anchor_day = anchor.strftime("%Y-%m-%d")
    daily_sends = windows.window.get(team_id, empty).daily_sends
    days_reached = sum(1 for day, sent in daily_sends.items() if day > anchor_day and sent >= daily_target)
    next_tier = EmailSendingNextTier(
        emails_per_day=get_email_sending_tier_limits(tier + 1).per_day,
        daily_target=daily_target,
        days_required=settings.WORKFLOWS_EMAIL_TIER_MIN_ACTIVE_DAYS,
        days_reached=min(days_reached, settings.WORKFLOWS_EMAIL_TIER_MIN_ACTIVE_DAYS),
        not_before=anchor + timedelta(days=min_days_at_tier(tier)),
    )
    return next_tier, recent_rates


RECENT_ALLOWANCE_CHANGES_DAYS = 90
RECENT_ALLOWANCE_CHANGES_LIMIT = 5


def _recent_allowance_changes(team_id: int, now: datetime) -> tuple[EmailSendingAllowanceChange, ...]:
    # A row can record only a pin change, which moves no allowance.
    rows = ActivityLog.objects.filter(
        team_id=team_id,
        scope="Team",
        item_id=str(team_id),
        activity=EMAIL_SENDING_TIER_CHANGED_ACTIVITY,
        created_at__gte=now - timedelta(days=RECENT_ALLOWANCE_CHANGES_DAYS),
        detail__changes__contains=[{"field": "email_sending_tier"}],
    ).order_by("-created_at")[:RECENT_ALLOWANCE_CHANGES_LIMIT]
    changes: list[EmailSendingAllowanceChange] = []
    for row in rows:
        # The filter above only matches rows with a detail.
        detail = row.detail or {}
        tier_change = next(change for change in detail["changes"] if change["field"] == "email_sending_tier")
        changes.append(
            EmailSendingAllowanceChange(
                changed_at=row.created_at,
                previous_emails_per_day=get_email_sending_tier_limits(tier_change["before"]).per_day,
                emails_per_day=get_email_sending_tier_limits(tier_change["after"]).per_day,
                reason=detail.get("context", {}).get("reason", ""),
            )
        )
    return tuple(changes)


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


INFRASTRUCTURE_HEALTH_FLAG = "workflows-email-infrastructure-health"


def email_infrastructure_health_enabled(team: Team) -> bool:
    try:
        return bool(
            posthoganalytics.feature_enabled(
                INFRASTRUCTURE_HEALTH_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id)},
                },
                send_feature_flag_events=False,
                # The reputation request must not wait on a remote flag call.
                only_evaluate_locally=True,
            )
        )
    except Exception:
        return False


# VDM counts whole days, so the numbers move once a day; refreshing every few hours is plenty.
INFRASTRUCTURE_HEALTH_CACHE_SECONDS = 6 * 60 * 60
INFRASTRUCTURE_HEALTH_ERROR_CACHE_SECONDS = 60
INFRASTRUCTURE_HEALTH_REFRESH_LOCK_SECONDS = 30


def fetch_email_infrastructure_health(window_days: int) -> EmailInfrastructureHealth | None:
    """
    Delivery health across every project sending through this region's SES account, shown to every
    project so its members can judge the shared infrastructure, not just their own sending. One key
    serves every project, and a cold key admits one SES call rather than one per request.
    """
    cache_key = f"workflows_ses_infrastructure_health_v2_{window_days}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached["value"]
    if not cache.add(f"{cache_key}_refreshing", True, INFRASTRUCTURE_HEALTH_REFRESH_LOCK_SECONDS):
        return None

    try:
        metrics = SESProvider().get_account_sending_metrics(window_days)
    except Exception:
        logger.exception("Failed to fetch SES account sending metrics")
        cache.set(cache_key, {"value": None}, INFRASTRUCTURE_HEALTH_ERROR_CACHE_SECONDS)
        return None

    value = _rounded_infrastructure_health(metrics) if metrics is not None else None
    # SES reports a failed query as a missing rate rather than an exception, so retry it soon.
    lifetime = INFRASTRUCTURE_HEALTH_CACHE_SECONDS if value is not None else INFRASTRUCTURE_HEALTH_ERROR_CACHE_SECONDS
    cache.set(cache_key, {"value": value}, lifetime)
    return value


def _rounded_infrastructure_health(metrics: IspSendingMetrics) -> EmailInfrastructureHealth | None:
    """
    The exact send volume stays private, so it is cut to a lower bound. Each rate rounds towards
    the worse reading, so rounding never flatters the infrastructure.
    """
    if metrics.bounce_rate is None or metrics.complaint_rate is None:
        return None
    return EmailInfrastructureHealth(
        emails_sent_at_least=_floor_to_one_significant_figure(metrics.emails_sent),
        bounce_rate=_round_rate_up(metrics.bounce_rate),
        complaint_rate=_round_rate_up(metrics.complaint_rate),
    )


def _floor_to_one_significant_figure(count: int) -> int:
    magnitude = 10 ** (len(str(count)) - 1)
    return count // magnitude * magnitude


def _round_rate_up(rate: float) -> float:
    return float(Decimal(str(rate)).quantize(Decimal("0.0001"), rounding=ROUND_CEILING))


def verified_email_domains(*, team_id: int) -> list[str]:
    """The project's verified sending domains, oldest integration first, without repeats."""
    return list(
        dict.fromkeys(
            domain
            for domain in (
                (row.config or {}).get("domain")
                for row in IntegrationManager.email.credentials.list(team_id, where={"verified": True})
            )
            if domain
        )
    )


def email_domain_sharers(*, team_id: int, domains: Collection[str]) -> dict[str, set[int]]:
    """For each domain, the other projects that also send from it."""
    sharers: dict[str, set[int]] = {domain: set() for domain in domains}
    rows = IntegrationManager.email.any.list_across_teams(
        CrossTeamFilter(where={"verified": True}, where_in={"domain": tuple(domains)}, exclude_team_ids=(team_id,))
    )
    for row in rows:
        sharers[row.config["domain"]].add(row.team_id)
    return sharers
