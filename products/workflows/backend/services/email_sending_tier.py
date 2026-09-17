from datetime import datetime, timedelta
from typing import Any, Optional

from django.conf import settings
from django.utils import timezone

import structlog

from posthog.api.app_metrics2 import fetch_app_metric_daily_totals_by_team
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen

from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig
from products.workflows.backend.utils.email_sending_tiers import (
    MIN_EMAIL_SENDING_TIER,
    get_email_sending_tier_limits,
    max_email_sending_tier,
    min_days_at_tier,
)

logger = structlog.get_logger(__name__)

APP_SOURCE = "hog_flow"

SENT_METRIC = "email_sent"
HARD_BOUNCE_METRIC = "email_bounced_hard"
# SES complaint events are recorded under this name (see the SES webhook handler in the email
# worker), so a complaint rate reads `email_blocked`, not a metric called "complaint".
COMPLAINT_METRIC = "email_blocked"

# Decision reasons that count as a rate-driven demotion and therefore arm the demotion cooldown.
RATE_DEMOTION_REASONS = frozenset({"rates_above_threshold", "workflow_auto_paused", "ses_reputation_high"})


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
            # Nothing sent means no rate to measure, and callers pair this with the volume bar,
            # which a team that sent nothing cannot clear. Complaints still count through the
            # absolute backstop: feedback lags sends by hours or days, so a window can hold the
            # complaints from sends that happened just before it opened.
            return self.complained < settings.WORKFLOWS_EMAIL_TIER_COMPLAINT_COUNT_BACKSTOP
        # A rate needs a denominator to mean anything: at the 0.1% complaint threshold, one
        # complaint per 1,000 sends is exactly the line, so on a smaller window a single complaint
        # would read as dirty. Below the floor, complaints only count through the absolute
        # backstop, and the bounce rate does not count at all.
        complaints_are_dirty = self.complaint_rate > settings.WORKFLOWS_EMAIL_TIER_MAX_COMPLAINT_RATE and (
            self.sent >= settings.WORKFLOWS_EMAIL_TIER_COMPLAINT_RATE_MIN_SENDS
            or self.complained >= settings.WORKFLOWS_EMAIL_TIER_COMPLAINT_COUNT_BACKSTOP
        )
        bounces_are_dirty = (
            self.hard_bounce_rate > settings.WORKFLOWS_EMAIL_TIER_MAX_BOUNCE_RATE
            and self.sent >= settings.WORKFLOWS_EMAIL_TIER_BOUNCE_RATE_MIN_SENDS
        )
        return not (complaints_are_dirty or bounces_are_dirty)


@frozen
class TierDecision:
    team_id: int
    previous_tier: int
    new_tier: int
    reason: str

    @property
    def changed(self) -> bool:
        return self.previous_tier != self.new_tier


@frozen
class SesTenantState:
    """AWS's own view of the team's SES tenant, synced by the tenant-state tasks.

    This complements our internal rates rather than duplicating them: AWS measures the complaint
    rate against mail sent to FBL-providing domains only, while our rate divides by all sends, so
    ours reads systematically lower for teams whose audience skews toward non-FBL domains. A team
    can look clean to us while AWS is about to pause its tenant.
    """

    sending_status: str = ""
    reputation_impact: str = ""

    @property
    def is_paused(self) -> bool:
        # SendingStatusAggregate folds AWS-managed and customer-managed pauses; REINSTATED is a
        # re-enabled grace state and must not read as paused.
        return self.sending_status.strip().upper() == "DISABLED"

    @property
    def impact(self) -> str:
        # Empty string means never synced, which reads the same as NONE.
        return self.reputation_impact.strip().upper()


def highest_qualifying_tier(daily_sends: dict[str, int], *, since: Optional[datetime] = None) -> int:
    """
    Highest tier the team's send volume has earned.

    Clearing a tier's use bar earns the tier above it, so the walk stops at the first tier whose bar
    the team did not meet on enough separate days. It never returns more than the top tier.
    """
    min_days = settings.WORKFLOWS_EMAIL_TIER_MIN_ACTIVE_DAYS
    ratio = settings.WORKFLOWS_EMAIL_TIER_MIN_DAILY_USE_RATIO
    # Exclude the whole anchor day, not only the change moment. Metrics are day-grained, so the
    # anchor day holds sends made both before and after the tier change. Keeping it would count
    # pre-change volume as evidence for the new tier, which lets a demoted team re-promote on one
    # real day at the new tier plus the day it was demoted on.
    since_key = since.strftime("%Y-%m-%d") if since else None
    counted = {day: sent for day, sent in daily_sends.items() if since_key is None or day > since_key}

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
    recent_history: Optional[TeamSendingHistory] = None,
    tenant_state: Optional[SesTenantState] = None,
    last_rate_demotion_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
    require_time_at_tier: bool = True,
    single_step: bool = True,
) -> TierDecision:
    """
    The tier a team should hold, given its sending history.

    `history` covers the promotion window and `recent_history` the shorter demotion window, so an
    incident demotes while it is fresh but stops holding the team down once it ages out of the
    short window, while promotion still requires the full window to be clean. Callers with a
    single window (the backfill) omit `recent_history`.

    `tenant_state` carries AWS's per-tenant verdict, which sees the FBL-correct complaint rate
    our internal metrics dilute (see SesTenantState). A paused tenant drops to the bottom, a
    HIGH reputation impact demotes, and any non-clean impact blocks promotion.

    `require_time_at_tier` and `single_step` are both off for the backfill, which reads a long
    history at once and must land an established sender on its real tier immediately instead of
    walking it up one step per run.
    """
    now = now or timezone.now()
    top = max_email_sending_tier()
    recent = recent_history or history
    tenant = tenant_state or SesTenantState()

    if suspended:
        return TierDecision(
            team_id=history.team_id,
            previous_tier=current_tier,
            new_tier=MIN_EMAIL_SENDING_TIER,
            reason="staff_suspension",
        )

    if tenant.is_paused:
        # AWS stopped this tenant's sends over its reputation, which is a stronger verdict than
        # anything our internal rates can produce. The tier sets how fast the team may send once
        # the tenant is re-enabled, so it must restart from the bottom.
        return TierDecision(
            team_id=history.team_id,
            previous_tier=current_tier,
            new_tier=MIN_EMAIL_SENDING_TIER,
            reason="ses_tenant_paused",
        )

    if recent.auto_paused or not recent.rates_are_clean or tenant.impact == "HIGH":
        # One incident stays inside the demotion window for days and the sweep runs daily, so
        # without a cooldown the same incident would demote the team again on every run and
        # cascade it to the bottom. The anchor is the last rate demotion, not the last tier write:
        # a promotion or staff change must not shield a team from its first real demotion. With the
        # cooldown at least as long as the demotion window, the evidence behind the last demotion
        # has aged out by the time demotions resume, so a second step needs new evidence.
        cooldown = timedelta(days=settings.WORKFLOWS_EMAIL_TIER_DEMOTION_COOLDOWN_DAYS)
        if last_rate_demotion_at is not None and now - last_rate_demotion_at < cooldown:
            return TierDecision(
                team_id=history.team_id,
                previous_tier=current_tier,
                new_tier=current_tier,
                reason="demotion_cooldown",
            )
        if recent.auto_paused:
            demotion_reason = "workflow_auto_paused"
        elif not recent.rates_are_clean:
            demotion_reason = "rates_above_threshold"
        else:
            demotion_reason = "ses_reputation_high"
        return TierDecision(
            team_id=history.team_id,
            previous_tier=current_tier,
            new_tier=max(MIN_EMAIL_SENDING_TIER, current_tier - 1),
            reason=demotion_reason,
        )

    decay_days = settings.WORKFLOWS_EMAIL_TIER_INACTIVITY_DECAY_DAYS
    if (
        decay_days > 0
        and current_tier > MIN_EMAIL_SENDING_TIER
        and history.sent == 0
        and tier_updated_at is not None
        and now - tier_updated_at >= timedelta(days=decay_days)
    ):
        # Mailbox providers keep roughly 30 days of reputation history, so a long-dormant
        # allowance is no longer earned, and a comeback blast from a stale list is exactly what
        # the caps exist to prevent. Each decay step resets tier_updated_at, so a dormant team
        # steps down one tier per decay period rather than dropping at once.
        return TierDecision(
            team_id=history.team_id,
            previous_tier=current_tier,
            new_tier=current_tier - 1,
            reason="inactive",
        )

    if current_tier >= top:
        return TierDecision(
            team_id=history.team_id, previous_tier=current_tier, new_tier=current_tier, reason="already_top_tier"
        )

    if not history.rates_are_clean:
        # The recent window recovered but the promotion window has not. Hold rather than promote,
        # so a team does not climb while its long-run rates are still over the threshold.
        return TierDecision(
            team_id=history.team_id, previous_tier=current_tier, new_tier=current_tier, reason="rates_recovering"
        )

    if tenant.impact not in ("", "NONE"):
        # AWS sees a reputation problem our diluted internal rates may not. LOW is not worth a
        # demotion, but a team must not climb while AWS flags its tenant.
        return TierDecision(
            team_id=history.team_id,
            previous_tier=current_tier,
            new_tier=current_tier,
            reason="ses_reputation_not_clean",
        )

    if require_time_at_tier:
        anchor = tier_updated_at
        if anchor is not None and now - anchor < timedelta(days=min_days_at_tier(current_tier)):
            return TierDecision(
                team_id=history.team_id, previous_tier=current_tier, new_tier=current_tier, reason="too_soon"
            )

    # Only days spent at the current tier count toward its use bar, so a demotion does not carry the
    # previous tier's volume forward as evidence. The backfill has no tier anchor, but its long
    # history must still qualify on recent days: without the cutoff, two high-volume days months ago
    # would grant a dormant team a tier the inactivity decay exists to remove, and the write would
    # restart the decay clock on top.
    if require_time_at_tier:
        since = tier_updated_at
    else:
        decay_days = settings.WORKFLOWS_EMAIL_TIER_INACTIVITY_DECAY_DAYS
        since = now - timedelta(days=decay_days) if decay_days > 0 else None
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
    workload: Workload = Workload.DEFAULT,
) -> dict[int, TeamSendingHistory]:
    """Read every team's workflow email metrics for the window in one grouped query."""
    daily_by_team = _fetch_daily_metrics(after=after, before=before, team_ids=team_ids, workload=workload)
    return {team_id: _history_from_daily(team_id, days) for team_id, days in daily_by_team.items()}


@frozen
class SendingHistoryWindows:
    """Per-team sending histories over the promotion window and the shorter demotion window."""

    window: dict[int, TeamSendingHistory]
    recent: dict[int, TeamSendingHistory]


def build_sending_history_windows(
    *,
    after: datetime,
    recent_after: datetime,
    before: Optional[datetime] = None,
    team_ids: Optional[list[int]] = None,
) -> SendingHistoryWindows:
    """The full promotion window and the shorter demotion window, from one query.

    The recent window is cut on calendar days (UTC), matching the day granularity the metrics are
    fetched at, so its edge can be up to a day coarser than `recent_after`.
    """
    daily_by_team = _fetch_daily_metrics(after=after, before=before, team_ids=team_ids)
    recent_key = recent_after.strftime("%Y-%m-%d")
    return SendingHistoryWindows(
        window={team_id: _history_from_daily(team_id, days) for team_id, days in daily_by_team.items()},
        recent={
            team_id: _history_from_daily(team_id, {day: counts for day, counts in days.items() if day >= recent_key})
            for team_id, days in daily_by_team.items()
        },
    )


def _fetch_daily_metrics(
    *,
    after: datetime,
    before: Optional[datetime],
    team_ids: Optional[list[int]],
    workload: Workload = Workload.DEFAULT,
) -> dict[int, dict[str, dict[str, int]]]:
    auto_pause_metrics = [name for name in settings.WORKFLOWS_EMAIL_TIER_AUTO_PAUSE_METRIC_NAMES if name]
    metric_names = [SENT_METRIC, HARD_BOUNCE_METRIC, COMPLAINT_METRIC, *auto_pause_metrics]
    # Tag the query so it is attributable in query-cost analysis and does not trip the untagged-query
    # guard in local dev. Celery adds only task identity, not a product or feature. This derives tier
    # state in the background, so it is enrichment, not a customer-facing query. One context here
    # covers the daily sweep, the admin recompute, and the backfill command.
    with tags_context(product=Product.WORKFLOWS, feature=Feature.ENRICHMENT):
        return fetch_app_metric_daily_totals_by_team(
            app_source=APP_SOURCE,
            name=metric_names,
            after=after,
            before=before,
            team_ids=team_ids,
            workload=workload,
        )


def _history_from_daily(team_id: int, days: dict[str, dict[str, int]]) -> TeamSendingHistory:
    # The tier decision only reads team totals, so metrics recorded under a batch job id and under
    # its parent workflow id sum the same either way and need no per-source resolution.
    auto_pause_metrics = [name for name in settings.WORKFLOWS_EMAIL_TIER_AUTO_PAUSE_METRIC_NAMES if name]
    return TeamSendingHistory(
        team_id=team_id,
        sent=sum(counts.get(SENT_METRIC, 0) for counts in days.values()),
        hard_bounced=sum(counts.get(HARD_BOUNCE_METRIC, 0) for counts in days.values()),
        complained=sum(counts.get(COMPLAINT_METRIC, 0) for counts in days.values()),
        auto_paused=any(counts.get(metric, 0) > 0 for counts in days.values() for metric in auto_pause_metrics),
        daily_sends={day: counts.get(SENT_METRIC, 0) for day, counts in days.items() if counts.get(SENT_METRIC, 0)},
    )


def _empty_history(team_id: int) -> TeamSendingHistory:
    return TeamSendingHistory(team_id=team_id, sent=0, hard_bounced=0, complained=0, auto_paused=False, daily_sends={})


def apply_tier_decision(config: TeamWorkflowsConfig, decision: TierDecision) -> bool:
    """Persist a tier change. Returns whether anything was written."""
    if not decision.changed:
        return False

    # Compare-and-set against the state the decision was read from. The fleet sweep loads every
    # config in one snapshot and writes later in the loop, so a staff pin, suspension, or manual
    # tier set that lands in that gap must not be clobbered by a stale computed value. Every admin
    # writer of this row locks it; the sweep instead conditions the write, so it no-ops when the
    # row moved underneath and the next run recomputes from the new state.
    fields: dict[str, Any] = {
        "email_sending_tier": decision.new_tier,
        "email_sending_tier_updated_at": timezone.now(),
    }
    if decision.reason in RATE_DEMOTION_REASONS:
        # Only rate-driven demotions arm the demotion cooldown. Promotions, decay, suspensions,
        # and staff writes share the dwell anchor above but must not delay a real demotion.
        fields["email_sending_tier_demoted_at"] = timezone.now()

    updated = TeamWorkflowsConfig.objects.filter(
        team_id=decision.team_id,
        email_sending_tier=decision.previous_tier,
        email_sending_tier_pinned=False,
        email_sending_suspended_at__isnull=config.email_sending_suspended_at is None,
    ).update(**fields)
    if not updated:
        return False

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

    Returns every decision, including holds (`changed` False, with the reason), so callers like the
    admin recompute action can say why a team did not move. A changed decision whose write lost to
    a concurrent staff change is dropped: the stored state moved underneath it, so neither the
    change nor its reason describes the row anymore.
    """
    now = timezone.now()
    after = now - timedelta(days=settings.WORKFLOWS_EMAIL_TIER_RATE_WINDOW_DAYS)
    recent_after = now - timedelta(days=settings.WORKFLOWS_EMAIL_TIER_DEMOTION_WINDOW_DAYS)
    windows = build_sending_history_windows(after=after, recent_after=recent_after, team_ids=team_ids)
    histories = windows.window

    stateful_teams = TeamWorkflowsConfig.objects.filter(email_sending_tier_pinned=False).exclude(
        email_sending_tier=MIN_EMAIL_SENDING_TIER, email_sending_suspended_at__isnull=True
    )
    if team_ids is not None:
        stateful_teams = stateful_teams.filter(team_id__in=team_ids)

    candidate_ids = set(histories) | set(stateful_teams.values_list("team_id", flat=True))
    if not candidate_ids:
        return []

    # select_related bypasses TeamManager's defer, so without only() the join pulls every wide Team
    # column, including the deprecated taxonomy blobs, for every candidate. The decision reads only
    # created_at from Team, so restrict the load to that plus the config fields it uses.
    configs = {
        config.team_id: config
        for config in TeamWorkflowsConfig.objects.filter(team_id__in=candidate_ids)
        .select_related("team")
        .only(
            "email_sending_tier",
            "email_sending_tier_pinned",
            "email_sending_tier_updated_at",
            "email_sending_tier_demoted_at",
            "email_sending_suspended_at",
            "ses_tenant_sending_status",
            "ses_tenant_reputation_impact",
            "team__created_at",
        )
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
            recent_history=windows.recent.get(team_id) or _empty_history(team_id),
            current_tier=config.email_sending_tier,
            tier_updated_at=config.email_sending_tier_updated_at or config.team.created_at,
            suspended=config.email_sending_suspended_at is not None,
            tenant_state=SesTenantState(
                sending_status=config.ses_tenant_sending_status,
                reputation_impact=config.ses_tenant_reputation_impact,
            ),
            last_rate_demotion_at=config.email_sending_tier_demoted_at,
        )
        if not decision.changed or apply_tier_decision(config, decision):
            decisions.append(decision)
    return decisions


def recompute_email_sending_tier_for_team(team_id: int) -> Optional[TierDecision]:
    """
    Recompute one team now, so a staff suspension takes its tier down without waiting for the
    next periodic run. Returns the decision, held or applied, so the caller can say why a team
    did not move. None means the team was not evaluated at all: it is pinned, it has no config
    row, or its state changed while recomputing.
    """
    decisions = recompute_email_sending_tiers(team_ids=[team_id])
    return decisions[0] if decisions else None
