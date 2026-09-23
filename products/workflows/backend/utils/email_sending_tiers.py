from typing import Literal

from django.conf import settings

import structlog

from posthog.dataclasses import frozen

from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig

logger = structlog.get_logger(__name__)

TierMode = Literal["off", "shadow", "enforce"]

MIN_EMAIL_SENDING_TIER = 0


@frozen
class EmailSendingTierLimits:
    """What a trust tier allows: two send-rate caps and a maximum batch audience."""

    tier: int
    per_hour: int
    per_day: int
    max_batch_audience: int


@frozen
class TeamEmailSendingTier:
    tier: int
    pinned: bool
    limits: EmailSendingTierLimits
    # False while the rollout mode is "off" or "shadow". Callers must fall back to pre-tier behavior.
    enforced: bool


def email_sending_tier_mode() -> TierMode:
    """Rollout mode. An unrecognized value reads as "off" so a typo cannot start throttling teams."""
    mode = str(settings.WORKFLOWS_EMAIL_TIER_MODE or "").strip().lower()
    if mode == "shadow":
        return "shadow"
    if mode == "enforce":
        return "enforce"
    return "off"


def max_email_sending_tier() -> int:
    return _tier_count() - 1


def min_days_at_tier(tier: int) -> int:
    """Days a team must hold `tier` before it can be promoted off it. Clamped into the configured
    list so a partial env override cannot raise on a high tier."""
    days = settings.WORKFLOWS_EMAIL_TIER_MIN_DAYS_AT_TIER
    if not days:
        return 0
    return int(days[min(max(tier, 0), len(days) - 1)])


def _tier_count() -> int:
    # The shortest list wins so a partial env override cannot index past the end of another table.
    return min(
        len(settings.WORKFLOWS_EMAIL_TIER_HOURLY_CAPS),
        len(settings.WORKFLOWS_EMAIL_TIER_DAILY_CAPS),
        len(settings.WORKFLOWS_EMAIL_TIER_BATCH_AUDIENCE_CAPS),
    )


def get_email_sending_tier_limits(tier: int) -> EmailSendingTierLimits:
    """
    Caps for a tier, clamped into the configured table.

    An unusable table (an env override that emptied one of the lists) falls back to the pre-tier
    ceiling rather than to a small number. Misconfiguration must never throttle a paying customer.
    """
    count = _tier_count()
    if count <= 0:
        logger.warning("workflows_email_tier_table_empty", tier=tier)
        elevated = settings.HOGFLOW_BATCH_TRIGGER_LIMIT_ELEVATED
        return EmailSendingTierLimits(
            tier=tier,
            per_hour=elevated,
            per_day=elevated,
            max_batch_audience=elevated,
        )

    clamped = min(max(tier, MIN_EMAIL_SENDING_TIER), count - 1)
    return EmailSendingTierLimits(
        tier=clamped,
        per_hour=settings.WORKFLOWS_EMAIL_TIER_HOURLY_CAPS[clamped],
        per_day=settings.WORKFLOWS_EMAIL_TIER_DAILY_CAPS[clamped],
        max_batch_audience=settings.WORKFLOWS_EMAIL_TIER_BATCH_AUDIENCE_CAPS[clamped],
    )


def is_tier_enforced() -> bool:
    return email_sending_tier_mode() == "enforce"


def resolve_team_email_sending_tier(team_id: int) -> TeamEmailSendingTier:
    """
    A team's stored tier plus the caps it maps to.

    Fails open: any lookup problem reads as the top tier, matching TeamWorkflowsConfigService in the
    email worker. A config blip must not throttle a legitimate customer.
    """
    top_tier = max(max_email_sending_tier(), MIN_EMAIL_SENDING_TIER)
    # The guard wraps the whole resolution, not just the first query: the allowlist and no-row
    # branches run their own creation-date lookup, and a database blip there must fail open too
    # rather than crash the send path.
    try:
        return _resolve_team_email_sending_tier(team_id, top_tier)
    except Exception:
        logger.exception("workflows_email_tier_lookup_failed", team_id=team_id)
        return TeamEmailSendingTier(
            tier=top_tier,
            pinned=False,
            limits=get_email_sending_tier_limits(top_tier),
            enforced=False,
        )


def _resolve_team_email_sending_tier(team_id: int, top_tier: int) -> TeamEmailSendingTier:
    if team_id in settings.HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS:
        # The pre-tier allowlist keeps working as a staff pin at the top tier.
        return TeamEmailSendingTier(
            tier=top_tier,
            pinned=True,
            limits=get_email_sending_tier_limits(top_tier),
            enforced=is_tier_enforced(),
        )

    row = (
        TeamWorkflowsConfig.objects.filter(team_id=team_id)
        .values("email_sending_tier", "email_sending_tier_pinned")
        .first()
    )
    if row is None:
        # No row means the team never touched a workflows setting, so it starts at tier 0.
        tier = MIN_EMAIL_SENDING_TIER
        pinned = False
    else:
        tier = row["email_sending_tier"]
        pinned = row["email_sending_tier_pinned"]

    return TeamEmailSendingTier(
        tier=tier,
        pinned=pinned,
        limits=get_email_sending_tier_limits(tier),
        enforced=is_tier_enforced(),
    )
