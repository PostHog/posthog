from datetime import UTC, datetime
from typing import Literal, Optional

from django.conf import settings
from django.utils.dateparse import parse_datetime

import structlog

from posthog.dataclasses import frozen
from posthog.models.team import Team

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
    # False while the rollout mode is "off" or "shadow", or while enforcement is narrowed to teams
    # created after a cutoff this team predates. Callers must fall back to pre-tier behavior.
    enforced: bool


def email_sending_tier_mode() -> TierMode:
    """Rollout mode. An unrecognized value reads as "off" so a typo cannot start throttling teams."""
    mode = str(settings.WORKFLOWS_EMAIL_TIER_MODE or "").strip().lower()
    if mode in ("shadow", "enforce"):
        return mode  # type: ignore[return-value]
    return "off"


def max_email_sending_tier() -> int:
    return _tier_count() - 1


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


def _enforcement_cutoff() -> Optional[datetime]:
    raw = str(settings.WORKFLOWS_EMAIL_TIER_ENFORCE_TEAMS_CREATED_AFTER or "").strip()
    if not raw:
        return None
    # Read on the send path, so a typo in the env var must not raise here.
    try:
        parsed = parse_datetime(raw)
    except ValueError:
        parsed = None
    if parsed is None:
        logger.warning("workflows_email_tier_cutoff_unparseable", value=raw)
        return None
    # A bare date ("2026-01-01") parses to a naive datetime, while the team creation dates it is
    # compared against are UTC-aware. Read a naive cutoff as UTC instead of raising on the compare.
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def is_tier_enforced_for_team(team_created_at: Optional[datetime]) -> bool:
    if email_sending_tier_mode() != "enforce":
        return False
    cutoff = _enforcement_cutoff()
    if cutoff is None:
        return True
    # An unknown creation date reads as "not after the cutoff": the cutoff exists to spare
    # established teams, so an unresolvable team must land on the established side.
    return team_created_at is not None and team_created_at >= cutoff


def resolve_team_email_sending_tier(team_id: int) -> TeamEmailSendingTier:
    """
    A team's stored tier plus the caps it maps to.

    Fails open: any lookup problem reads as the top tier, matching TeamWorkflowsConfigService in the
    email worker. A config blip must not throttle a legitimate customer.
    """
    top_tier = max(max_email_sending_tier(), MIN_EMAIL_SENDING_TIER)
    try:
        row = (
            TeamWorkflowsConfig.objects.filter(team_id=team_id)
            .values("email_sending_tier", "email_sending_tier_pinned", "team__created_at")
            .first()
        )
    except Exception:
        logger.exception("workflows_email_tier_lookup_failed", team_id=team_id)
        return TeamEmailSendingTier(
            tier=top_tier,
            pinned=False,
            limits=get_email_sending_tier_limits(top_tier),
            enforced=False,
        )

    if team_id in settings.HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS:
        # The pre-tier allowlist keeps working as a staff pin at the top tier.
        return TeamEmailSendingTier(
            tier=top_tier,
            pinned=True,
            limits=get_email_sending_tier_limits(top_tier),
            enforced=is_tier_enforced_for_team(row["team__created_at"] if row else _team_created_at(team_id)),
        )

    if row is None:
        # No row means the team never touched a workflows setting, so it starts at tier 0. Reading
        # the creation date still matters: enforcement can be narrowed to teams created after a
        # cutoff, and a team without a row can sit on either side of it.
        tier = MIN_EMAIL_SENDING_TIER
        pinned = False
        created_at = _team_created_at(team_id)
    else:
        tier = row["email_sending_tier"]
        pinned = row["email_sending_tier_pinned"]
        created_at = row["team__created_at"]

    return TeamEmailSendingTier(
        tier=tier,
        pinned=pinned,
        limits=get_email_sending_tier_limits(tier),
        enforced=is_tier_enforced_for_team(created_at),
    )


def _team_created_at(team_id: int) -> Optional[datetime]:
    if _enforcement_cutoff() is None:
        # Without a cutoff the date changes nothing, so skip the query.
        return None
    return Team.objects.filter(id=team_id).values_list("created_at", flat=True).first()
