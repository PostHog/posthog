import uuid
from datetime import datetime, timedelta
from typing import Optional

from django.conf import settings
from django.utils import timezone

import structlog

from posthog.api.app_metrics2 import fetch_app_metric_daily_totals_by_team, fetch_app_metric_totals_by_team_and_source
from posthog.dataclasses import frozen

from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob
from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig
from products.workflows.backend.utils.email_sending_tiers import (
    MIN_EMAIL_SENDING_TIER,
    get_email_sending_tier_limits,
    max_email_sending_tier,
)

logger = structlog.get_logger(__name__)

APP_SOURCE = "hog_flow"

SENT_METRIC = "email_sent"
HARD_BOUNCE_METRIC = "email_bounced_hard"
# SES complaint events are recorded under this name (see the SES webhook handler in the email
# worker), so a complaint rate reads `email_blocked`, not a metric called "complaint".
COMPLAINT_METRIC = "email_blocked"


@frozen
class TeamSendingHistory:
    """What a team's workflow email metrics say over the trailing rate window."""

    team_id: int
    sent: int
    hard_bounced: int
    complained: int
    auto_paused: bool
    # Sends per calendar day, keyed "YYYY-MM-DD". Used to tell steady use of a tier apart from one
    # burst of the same total.
    daily_sends: dict[str, int]

    @property
    def complaint_rate(self) -> float:
        return min(1.0, self.complained / self.sent) if self.sent else 0.0

    @property
    def hard_bounce_rate(self) -> float:
        return min(1.0, self.hard_bounced / self.sent) if self.sent else 0.0

    @property
    def rates_are_clean(self) -> bool:
        if self.sent == 0:
            # Nothing sent means nothing measured, so the rates neither pass nor fail. Callers pair
            # this with the volume bar, which a team that sent nothing cannot clear.
            return True
        return (
            self.complaint_rate <= settings.WORKFLOWS_EMAIL_TIER_MAX_COMPLAINT_RATE
            and self.hard_bounce_rate <= settings.WORKFLOWS_EMAIL_TIER_MAX_BOUNCE_RATE
        )


@frozen
class TierDecision:
    team_id: int
    previous_tier: int
    new_tier: int
    reason: str

    @property
    def changed(self) -> bool:
        return self.previous_tier != self.new_tier


def highest_qualifying_tier(daily_sends: dict[str, int], *, since: Optional[datetime] = None) -> int:
    """
    Highest tier the team's send volume has earned.

    Clearing a tier's use bar earns the tier above it, so the walk stops at the first tier whose bar
    the team did not meet on enough separate days. It never returns more than the top tier.
    """
    min_days = settings.WORKFLOWS_EMAIL_TIER_MIN_ACTIVE_DAYS
    ratio = settings.WORKFLOWS_EMAIL_TIER_MIN_DAILY_USE_RATIO
    since_key = since.strftime("%Y-%m-%d") if since else None
    counted = {day: sent for day, sent in daily_sends.items() if since_key is None or day >= since_key}

    tier = MIN_EMAIL_SENDING_TIER
    top = max_email_sending_tier()
    while tier < top:
        bar = get_email_sending_tier_limits(tier).per_day * ratio
        days_at_bar = sum(1 for sent in counted.values() if sent >= bar)
        if days_at_bar < min_days:
            break
        tier += 1
    return tier


def decide_tier(
    *,
    history: TeamSendingHistory,
    current_tier: int,
    tier_updated_at: Optional[datetime],
    suspended: bool,
    now: Optional[datetime] = None,
    require_time_at_tier: bool = True,
    single_step: bool = True,
) -> TierDecision:
    """
    The tier a team should hold, given its sending history.

    `require_time_at_tier` and `single_step` are both off for the backfill, which reads a long
    history at once and must land an established sender on its real tier immediately instead of
    walking it up one step per run.
    """
    now = now or timezone.now()
    top = max_email_sending_tier()

    if suspended:
        return TierDecision(
            team_id=history.team_id,
            previous_tier=current_tier,
            new_tier=MIN_EMAIL_SENDING_TIER,
            reason="staff_suspension",
        )

    if history.auto_paused:
        return TierDecision(
            team_id=history.team_id,
            previous_tier=current_tier,
            new_tier=max(MIN_EMAIL_SENDING_TIER, current_tier - 1),
            reason="workflow_auto_paused",
        )

    if not history.rates_are_clean:
        return TierDecision(
            team_id=history.team_id,
            previous_tier=current_tier,
            new_tier=max(MIN_EMAIL_SENDING_TIER, current_tier - 1),
            reason="rates_above_threshold",
        )

    if current_tier >= top:
        return TierDecision(
            team_id=history.team_id, previous_tier=current_tier, new_tier=current_tier, reason="already_top_tier"
        )

    if require_time_at_tier:
        anchor = tier_updated_at
        if anchor is not None and now - anchor < timedelta(days=settings.WORKFLOWS_EMAIL_TIER_MIN_DAYS_AT_TIER):
            return TierDecision(
                team_id=history.team_id, previous_tier=current_tier, new_tier=current_tier, reason="too_soon"
            )

    # Only days spent at the current tier count toward its use bar, so a demotion does not carry the
    # previous tier's volume forward as evidence.
    since = tier_updated_at if require_time_at_tier else None
    earned = highest_qualifying_tier(history.daily_sends, since=since)
    if earned <= current_tier:
        return TierDecision(
            team_id=history.team_id, previous_tier=current_tier, new_tier=current_tier, reason="tier_not_used_enough"
        )

    new_tier = min(current_tier + 1, top) if single_step else min(earned, top)
    return TierDecision(team_id=history.team_id, previous_tier=current_tier, new_tier=new_tier, reason="clean_and_used")


def build_sending_histories(
    *,
    after: datetime,
    before: Optional[datetime] = None,
    team_ids: Optional[list[int]] = None,
) -> dict[int, TeamSendingHistory]:
    """Read every team's workflow email metrics for the window in two grouped queries."""
    auto_pause_metrics = [name for name in settings.WORKFLOWS_EMAIL_TIER_AUTO_PAUSE_METRIC_NAMES if name]
    metric_names = [SENT_METRIC, HARD_BOUNCE_METRIC, COMPLAINT_METRIC, *auto_pause_metrics]

    totals_by_team = fetch_app_metric_totals_by_team_and_source(
        app_source=APP_SOURCE,
        name=metric_names,
        after=after,
        before=before,
        team_ids=team_ids,
    )
    daily_by_team = fetch_app_metric_daily_totals_by_team(
        app_source=APP_SOURCE,
        name=[SENT_METRIC],
        after=after,
        before=before,
        team_ids=team_ids,
    )

    batch_job_to_flow = _resolve_batch_jobs(totals_by_team)

    histories: dict[int, TeamSendingHistory] = {}
    for team_id, totals_by_source in totals_by_team.items():
        # Metrics land under the workflow id for event-triggered runs and under the batch job id for
        # batch runs. The team totals are the same either way, but folding batch jobs into their
        # parent workflow is what makes the per-workflow signals (an auto-pause) attributable.
        folded = _fold_batch_jobs_into_workflows(totals_by_source, batch_job_to_flow)
        histories[team_id] = TeamSendingHistory(
            team_id=team_id,
            sent=sum(counts.get(SENT_METRIC, 0) for counts in folded.values()),
            hard_bounced=sum(counts.get(HARD_BOUNCE_METRIC, 0) for counts in folded.values()),
            complained=sum(counts.get(COMPLAINT_METRIC, 0) for counts in folded.values()),
            auto_paused=any(counts.get(metric, 0) > 0 for counts in folded.values() for metric in auto_pause_metrics),
            daily_sends={day: counts.get(SENT_METRIC, 0) for day, counts in daily_by_team.get(team_id, {}).items()},
        )
    return histories


def _looks_like_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _resolve_batch_jobs(totals_by_team: dict[int, dict[str, dict[str, int]]]) -> dict[str, str]:
    """Map every batch-job source id in the sweep to its parent workflow id, in one query.

    Non-UUID source ids are dropped first because a UUID column lookup rejects them outright.
    """
    source_ids = [
        source_id
        for totals_by_source in totals_by_team.values()
        for source_id in totals_by_source
        if _looks_like_uuid(source_id)
    ]
    if not source_ids:
        return {}
    return {
        str(batch_job_id): str(flow_id)
        for batch_job_id, flow_id in HogFlowBatchJob.objects.filter(id__in=source_ids).values_list("id", "hog_flow_id")
    }


def _fold_batch_jobs_into_workflows(
    totals_by_source: dict[str, dict[str, int]], batch_job_to_flow: dict[str, str]
) -> dict[str, dict[str, int]]:
    folded: dict[str, dict[str, int]] = {}
    for source_id, counts in totals_by_source.items():
        key = batch_job_to_flow.get(source_id, source_id)
        target = folded.setdefault(key, {})
        for metric_name, count in counts.items():
            target[metric_name] = target.get(metric_name, 0) + count
    return folded


def _empty_history(team_id: int) -> TeamSendingHistory:
    return TeamSendingHistory(team_id=team_id, sent=0, hard_bounced=0, complained=0, auto_paused=False, daily_sends={})


def apply_tier_decision(config: TeamWorkflowsConfig, decision: TierDecision) -> bool:
    """Persist a tier change. Returns whether anything was written."""
    if not decision.changed:
        return False

    config.email_sending_tier = decision.new_tier
    config.email_sending_tier_updated_at = timezone.now()
    config.save(update_fields=["email_sending_tier", "email_sending_tier_updated_at"])
    logger.info(
        "workflows_email_sending_tier_changed",
        team_id=decision.team_id,
        previous_tier=decision.previous_tier,
        new_tier=decision.new_tier,
        reason=decision.reason,
    )
    return True


def recompute_email_sending_tiers(team_ids: Optional[list[int]] = None) -> list[TierDecision]:
    """
    Move every candidate team at most one tier, up or down.

    Candidates are teams that sent workflow email in the window plus teams whose stored state can
    only be corrected by a run: a suspended team owed a demotion, and any team already above tier 0.
    A pinned team is skipped in both directions.
    """
    window_days = settings.WORKFLOWS_EMAIL_TIER_RATE_WINDOW_DAYS
    after = timezone.now() - timedelta(days=window_days)
    histories = build_sending_histories(after=after, team_ids=team_ids)

    stateful_teams = TeamWorkflowsConfig.objects.filter(email_sending_tier_pinned=False).exclude(
        email_sending_tier=MIN_EMAIL_SENDING_TIER, email_sending_suspended_at__isnull=True
    )
    if team_ids is not None:
        stateful_teams = stateful_teams.filter(team_id__in=team_ids)

    candidate_ids = set(histories) | set(stateful_teams.values_list("team_id", flat=True))
    if not candidate_ids:
        return []

    configs = {
        config.team_id: config
        for config in TeamWorkflowsConfig.objects.filter(team_id__in=candidate_ids).select_related("team")
    }

    decisions: list[TierDecision] = []
    for team_id in sorted(candidate_ids):
        config = configs.get(team_id)
        if config is None:
            # No row means tier 0 with no history worth acting on: a promotion needs volume the
            # metrics sweep would have surfaced, and there is nothing stored to demote.
            continue
        if config.email_sending_tier_pinned:
            continue

        decision = decide_tier(
            history=histories.get(team_id) or _empty_history(team_id),
            current_tier=config.email_sending_tier,
            tier_updated_at=config.email_sending_tier_updated_at or config.team.created_at,
            suspended=config.email_sending_suspended_at is not None,
        )
        if apply_tier_decision(config, decision):
            decisions.append(decision)
    return decisions


def recompute_email_sending_tier_for_team(team_id: int) -> Optional[TierDecision]:
    """
    Recompute one team now, so a staff suspension takes its tier down without waiting for the
    next periodic run. Returns the applied decision, or None when nothing changed.
    """
    applied = recompute_email_sending_tiers(team_ids=[team_id])
    return applied[0] if applied else None
