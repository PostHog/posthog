from collections import Counter
from collections.abc import Iterable
from datetime import timedelta
from typing import Any, Optional

from django.core.management.base import BaseCommand
from django.utils import timezone

import structlog

from posthog.clickhouse.client.connection import Workload
from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension

from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig
from products.workflows.backend.services.email_sending_tier import (
    SesTenantState,
    TeamSendingHistory,
    TierDecision,
    build_sending_histories,
    decide_tier,
)
from products.workflows.backend.utils.email_sending_tiers import (
    MIN_EMAIL_SENDING_TIER,
    get_email_sending_tier_limits,
    max_email_sending_tier,
)

logger = structlog.get_logger(__name__)

DEFAULT_HISTORY_DAYS = 90


class Command(BaseCommand):
    help = (
        "Assign every team an initial workflow email sending tier from its recent sending history. "
        "Uses the same promotion rules as the periodic task, minus the time-at-tier requirement and "
        "the one-tier-per-run step, so an established high-volume sender lands at the top tier at "
        "once instead of climbing for weeks. Teams with no sending history stay at tier 0. Prints a "
        "tier distribution so the tier boundaries can be checked against reality before enforcement "
        "is switched on. Read-only unless --apply is passed."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--days",
            type=int,
            default=DEFAULT_HISTORY_DAYS,
            help=f"How many days of sending history to read. Defaults to {DEFAULT_HISTORY_DAYS}.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the computed tiers. Without this the command only reports what it would do.",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            action="append",
            dest="team_ids",
            help="Restrict the backfill to this team. Repeatable.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        days: int = options["days"]
        apply_changes: bool = options["apply"]
        team_ids: Optional[list[int]] = options.get("team_ids")

        after = timezone.now() - timedelta(days=days)
        # A management command inherits the online workload, but this fleet-wide 90-day scan belongs
        # on the offline pool, away from customer queries. The daily Celery sweep already runs offline.
        histories = self._without_deleted_teams(
            build_sending_histories(after=after, team_ids=team_ids, workload=Workload.OFFLINE)
        )
        decisions = self._decide(histories=histories, team_ids=team_ids)

        written = self._apply(decisions) if apply_changes else 0

        self._report(decisions=decisions, histories=histories, days=days, applied=apply_changes, written=written)

    def _without_deleted_teams(self, histories: dict[int, TeamSendingHistory]) -> dict[int, TeamSendingHistory]:
        # app_metrics2 lives in ClickHouse and is not cleared when a team is deleted from Postgres,
        # so its history can name teams that no longer exist. Drop them so a defunct team_id does not
        # inflate the distribution, the denominator, or the written count.
        existing = set(Team.objects.filter(id__in=list(histories)).values_list("id", flat=True))
        return {team_id: history for team_id, history in histories.items() if team_id in existing}

    def _decide(self, *, histories: dict[int, TeamSendingHistory], team_ids: Optional[list[int]]) -> list[TierDecision]:
        configs = TeamWorkflowsConfig.objects.all()
        if team_ids is not None:
            configs = configs.filter(team_id__in=team_ids)
        state_by_team = {
            row["team_id"]: row
            for row in configs.values(
                "team_id",
                "email_sending_tier",
                "email_sending_tier_pinned",
                "email_sending_suspended_at",
                "ses_tenant_sending_status",
                "ses_tenant_reputation_impact",
            )
        }

        decisions: list[TierDecision] = []
        for team_id in sorted(set(histories) | set(state_by_team)):
            state = state_by_team.get(team_id)
            if state and state["email_sending_tier_pinned"]:
                continue
            history = histories.get(team_id)
            if history is None:
                if state is None or state["email_sending_suspended_at"] is None:
                    # No sending in the window and no suspension owed, so there is nothing to earn a
                    # tier with. Tier 0 is right for a new team and harmless for a dormant one,
                    # which will not hit a cap anyway.
                    continue
                # A suspended team must land on tier 0 even with no sends in the window, or the
                # backfill would leave its elevated allowance in place for reinstatement.
                history = TeamSendingHistory(
                    team_id=team_id, sent=0, hard_bounced=0, complained=0, auto_paused=False, daily_sends={}
                )
            decision = decide_tier(
                history=history,
                current_tier=state["email_sending_tier"] if state else MIN_EMAIL_SENDING_TIER,
                tier_updated_at=None,
                suspended=state is not None and state["email_sending_suspended_at"] is not None,
                tenant_state=SesTenantState(
                    sending_status=state["ses_tenant_sending_status"] if state else "",
                    reputation_impact=state["ses_tenant_reputation_impact"] if state else "",
                ),
                require_time_at_tier=False,
                single_step=False,
            )
            if decision.changed:
                decisions.append(decision)
        return decisions

    def _apply(self, decisions: list[TierDecision]) -> int:
        teams = {team.id: team for team in Team.objects.filter(id__in=[d.team_id for d in decisions])}
        now = timezone.now()
        written = 0
        for decision in decisions:
            team = teams.get(decision.team_id)
            if team is None:
                continue
            get_or_create_team_extension(team, TeamWorkflowsConfig)
            # Compare-and-set against the state the decision was computed from, like the daily
            # sweep's write: a staff pin, suspension, or manual tier set landing during the fleet
            # scan must not be overwritten by a stale decision. A no-op here is left for the next
            # sweep, which recomputes from the new state.
            updated = TeamWorkflowsConfig.objects.filter(
                team_id=decision.team_id,
                email_sending_tier=decision.previous_tier,
                email_sending_tier_pinned=False,
                email_sending_suspended_at__isnull=decision.reason != "staff_suspension",
            ).update(
                email_sending_tier=decision.new_tier,
                email_sending_tier_updated_at=now,
            )
            if not updated:
                continue
            written += 1
            logger.info(
                "workflows_email_sending_tier_backfilled",
                team_id=decision.team_id,
                previous_tier=decision.previous_tier,
                new_tier=decision.new_tier,
                reason=decision.reason,
            )
        return written

    def _current_tiers(self, team_ids: Iterable[int]) -> dict[int, int]:
        return {
            row["team_id"]: row["email_sending_tier"]
            for row in TeamWorkflowsConfig.objects.filter(team_id__in=team_ids).values("team_id", "email_sending_tier")
        }

    def _report(
        self,
        *,
        decisions: list[TierDecision],
        histories: dict[int, TeamSendingHistory],
        days: int,
        applied: bool,
        written: int,
    ) -> None:
        moved_to = {decision.team_id: decision.new_tier for decision in decisions}
        current_tiers = self._current_tiers(histories.keys())
        distribution: Counter[int] = Counter()
        for team_id in histories:
            # Report the tier the team would actually hold: the new tier if it moved, otherwise its
            # stored tier, or the default 0 when it has no stored row yet. An unchanged or pinned
            # team keeps its stored tier, so a re-run must not count it back down to tier 0.
            effective_tier = moved_to.get(team_id, current_tiers.get(team_id, MIN_EMAIL_SENDING_TIER))
            distribution[effective_tier] += 1

        sending_teams = len(histories)
        self.stdout.write(f"Read {days} days of history for {sending_teams} teams that sent workflow email.")
        self.stdout.write("")
        self.stdout.write("Tier distribution across those teams:")
        for tier in range(max_email_sending_tier() + 1):
            limits = get_email_sending_tier_limits(tier)
            count = distribution.get(tier, 0)
            share = (count / sending_teams * 100) if sending_teams else 0.0
            self.stdout.write(
                f"  tier {tier}: {count:>6} teams ({share:5.1f}%)  "
                f"{limits.per_hour:>9,}/hour  {limits.per_day:>10,}/day  {limits.max_batch_audience:>10,} batch"
            )
        self.stdout.write("")

        dirty = [team_id for team_id, history in histories.items() if not history.rates_are_clean]
        self.stdout.write(f"Teams with complaint or bounce rates above the threshold: {len(dirty)}")
        self.stdout.write(f"Teams whose tier would change: {len(decisions)}")

        if applied:
            self.stdout.write(self.style.SUCCESS(f"Wrote {written} tier changes."))
        else:
            self.stdout.write(self.style.WARNING("Nothing written. Re-run with --apply to write these tiers."))
