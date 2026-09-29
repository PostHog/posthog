"""Pre-computed scout suggestions: the push-side twin of the "Suggest a scout" chat.

The chat button mints a `SIGNALS_CHAT` task the user then waits on while the agent scans the
project. This module runs the same scan ahead of time, headless, for every eligible project and
stores 3-5 structured suggestions on `SignalScoutSuggestionSet`, so the scouts tab can offer them
with zero wait. Four pieces live here, all temporalio-free and cheap to import:

- the structured-output contract the headless run returns (`ScoutSuggestionBatch`)
- the planner: which teams to refresh this tick, in priority order (`plan_suggestion_runs`)
- the dispatch-time activity check on the picked candidates (`select_teams_to_scan`)
- persistence: write a batch, carry dismissals forward, dismiss / mark created

The runner that mints the headless task for one team lives in `suggestions_runner.py`, because it
pulls in the tasks agent facade (heavy by import) and the HTTP surface and receivers only need the
pieces here.

Everything that tunes the fleet-wide behavior reads from the `signals-scout-suggestions` flag
payload, so widening eligibility, capping spend, or switching the producer off is a flag edit
rather than a deploy or a per-team write.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Iterable
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from django.db import transaction
from django.db.models import F, Max, Q
from django.utils import timezone

import structlog
import posthoganalytics
from pydantic import BaseModel, Field

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.errors import InternalCHQueryError
from posthog.event_usage import groups
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team.team import Team
from posthog.models.utils import uuid7

from products.signals.backend.models import (
    SignalReportAction,
    SignalScoutConfig,
    SignalScoutSuggestionSet,
    SignalSourceConfig,
)
from products.signals.backend.scout_harness.lazy_seed import CanonicalSkillParseError, discover_canonical_skills
from products.signals.backend.scout_harness.prompt import SCOUT_PROJECT_SCAN_GUIDANCE
from products.signals.backend.scout_harness.team_limits import read_flag_payload, withheld_skills_for_team
from products.skills.backend.marketplace.packaging import SPEC_DESCRIPTION_MAX_LENGTH
from products.skills.backend.models.skills import LLMSkill

logger = structlog.get_logger(__name__)

SIGNALS_SCOUT_SUGGESTIONS_FLAG = "signals-scout-suggestions"

# A scan plus 3-5 suggestions is a fraction of a scout run; the ceiling exists so a wedged
# sandbox cannot hold a worker slot for a scout-length run.
SUGGESTIONS_MAX_RUNTIME_S = 10 * 60
SUGGESTIONS_ACTIVITY_SLACK_S = 60

MAX_SUGGESTIONS_PER_BATCH = 5
MIN_SUGGESTIONS_PER_BATCH = 3
MAX_DRAFT_BODY_CHARS = 20_000
# Read from `SignalScoutCreateSerializer.description` rather than restated: a longer one stores
# fine but fails the create it is supposed to be ready for.
MAX_DESCRIPTION_CHARS = SPEC_DESCRIPTION_MAX_LENGTH

# Resolves a suggestion run to the `signals_scout_suggestions` gateway product.
SUGGESTIONS_AI_STAGE = "scout_suggestions"

# Row cap on the per-candidate activity read, so the check stays cheap on a large project. The
# read refuses at the cap rather than truncating: the cap counts rows read while the query counts
# the rows that pass the window filter, so a truncated read would come back as a small count that
# reads like a quiet project. A project whose window does not fit the cap is active whatever the
# refusal hid, and only a read that finishes has numbers — the small projects the check is about.
ACTIVITY_READ_MAX_ROWS = 100_000

# Wall-clock cap on the same read. `sync_execute` adds none of its own and the pooled client's
# socket timeout is effectively infinite in production, so a stalled read would hold its worker
# thread past the planning activity's own deadline, which Temporal cannot reclaim. A capped read
# over the events primary-key prefix takes milliseconds, and the planner reads its candidates one
# after another inside a five-minute activity, so this leaves room for every candidate a tick
# picks at the default cap.
ACTIVITY_READ_MAX_EXECUTION_S = 10

SuggestionKind = Literal["canonical", "custom"]
SuggestionConfidence = Literal["low", "medium", "high"]


# ---------------------------------------------------------------------------
# Structured-output contract
# ---------------------------------------------------------------------------


class ScoutSuggestionProposedConfig(BaseModel):
    """Schedule and posture for the suggested scout. Mirrors the fields of the scout create API."""

    run_cron_schedule: str | None = Field(
        default=None,
        description=(
            "Optional five-field cron expression in the project timezone, e.g. '30 9 * * 1-5'. "
            "Takes precedence over run_interval_minutes."
        ),
    )
    run_interval_minutes: int | None = Field(
        default=None,
        description="Minutes between runs when no cron is given (30-43200). Omit for the daily default.",
    )
    emit: bool = Field(default=True, description="False for a dry run that logs but writes nothing to the inbox.")


class ScoutSuggestionItem(BaseModel):
    """One suggestion: either turn on a canonical scout, or create a custom draft."""

    kind: SuggestionKind = Field(
        description=(
            "'canonical' to enable one of the PostHog-authored scouts listed in the prompt; "
            "'custom' for a new project-specific scout you drafted."
        )
    )
    skill_name: str = Field(
        description=(
            "canonical: the exact listed name. custom: a new slug starting with 'signals-scout-' "
            "(lowercase letters, digits, hyphens), not already in the fleet."
        )
    )
    title: str = Field(max_length=80, description="Sentence case, <= 80 chars: what the scout watches.")
    why_here: str = Field(
        description=(
            "2-4 sentences of project-specific evidence: the named events, funnels, insights, dashboards "
            "or recent reports that make this scout worth running on THIS project."
        )
    )
    description: str = Field(
        default="",
        description="custom only: one or two sentences describing the signal or behavior the scout investigates.",
    )
    draft_body: str = Field(
        default="",
        description=(
            "custom only: the complete markdown body the scout runs on every run, written per the "
            "authoring-scouts skill (what to check, thresholds, what counts as a finding, what to ignore)."
        ),
    )
    proposed_config: ScoutSuggestionProposedConfig = Field(default_factory=ScoutSuggestionProposedConfig)
    gap: bool = Field(default=False, description="True when nothing in the current fleet covers this.")
    confidence: SuggestionConfidence = Field(default="medium")


class ScoutSuggestionBatch(BaseModel):
    """The JSON object the headless run ends its turn with."""

    suggestions: list[ScoutSuggestionItem] = Field(
        description=f"{MIN_SUGGESTIONS_PER_BATCH}-{MAX_SUGGESTIONS_PER_BATCH} suggestions, best first."
    )
    notes: str = Field(
        default="",
        description="Optional: why the batch is short or empty (e.g. the project has almost no data yet).",
    )


# ---------------------------------------------------------------------------
# Flag payload -> settings
# ---------------------------------------------------------------------------


@frozen
class SuggestionSettings:
    """The fleet-wide knobs, read from the `signals-scout-suggestions` flag payload every tick."""

    enabled: bool = False
    # The planner includes every tier <= this (see `_candidate_teams_by_tier`). 0 = the
    # `team_allowlist` only; 1 = engaged self-driving projects; 4 = every AI-approved team.
    eligibility_tier: int = 1
    engagement_window_days: int = 30
    refresh_days: int = 7
    # A batch the fleet has moved past is re-picked on this shorter window instead. `stale` is the
    # steady state — turning one scout on flips it — so a full refresh window would leave most
    # projects reading their batch under a stale note for a week.
    stale_refresh_days: int = 1
    max_children_per_tick: int = 10
    team_allowlist: frozenset[int] = frozenset()
    team_blocklist: frozenset[int] = frozenset()
    failure_breaker_threshold: int = 3
    failure_cooldown_hours: int = 24
    max_runtime_s: int = SUGGESTIONS_MAX_RUNTIME_S
    # The dispatch-time activity check. A project under either line is stamped `low_activity`
    # instead of scanned, because the scan could only refuse it. Either threshold at 0 turns
    # that half of the check off; both at 0 turns the check off.
    activity_window_days: int = 14
    min_events_in_window: int = 100
    min_active_days_in_window: int = 3


def _int_in(payload: dict[str, Any], key: str, default: int, *, low: int, high: int) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return min(max(value, low), high)


def _team_id_set(payload: dict[str, Any], key: str) -> frozenset[int]:
    raw = payload.get(key)
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(item for item in raw if isinstance(item, int) and not isinstance(item, bool))


def parse_suggestion_settings(payload: dict[str, Any] | None) -> SuggestionSettings:
    """Parse the flag payload defensively: an absent or malformed payload means "off"."""
    if not payload:
        return SuggestionSettings()
    return SuggestionSettings(
        enabled=payload.get("enabled") is True,
        eligibility_tier=_int_in(payload, "eligibility_tier", 1, low=0, high=4),
        engagement_window_days=_int_in(payload, "engagement_window_days", 30, low=1, high=365),
        refresh_days=_int_in(payload, "refresh_days", 7, low=1, high=90),
        stale_refresh_days=_int_in(payload, "stale_refresh_days", 1, low=1, high=90),
        max_children_per_tick=_int_in(payload, "max_children_per_tick", 10, low=0, high=500),
        team_allowlist=_team_id_set(payload, "team_allowlist"),
        team_blocklist=_team_id_set(payload, "team_blocklist"),
        failure_breaker_threshold=_int_in(payload, "failure_breaker_threshold", 3, low=1, high=100),
        failure_cooldown_hours=_int_in(payload, "failure_cooldown_hours", 24, low=1, high=24 * 30),
        max_runtime_s=_int_in(payload, "max_runtime_s", SUGGESTIONS_MAX_RUNTIME_S, low=60, high=30 * 60),
        activity_window_days=_int_in(payload, "activity_window_days", 14, low=1, high=90),
        min_events_in_window=_int_in(payload, "min_events_in_window", 100, low=0, high=ACTIVITY_READ_MAX_ROWS),
        min_active_days_in_window=_int_in(payload, "min_active_days_in_window", 3, low=0, high=90),
    )


def read_suggestion_settings() -> SuggestionSettings:
    """Blocking (flag SDK read); async callers wrap this in `asyncio.to_thread`."""
    return parse_suggestion_settings(read_flag_payload(SIGNALS_SCOUT_SUGGESTIONS_FLAG))


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


@frozen
class PlannedSuggestionRun:
    team_id: int
    tier: int


@frozen(order=True)
class _SortKey:
    # Tier first, never-generated before generated, most overdue first, then the project someone
    # looked at most recently, so when the cap bites the teams who will see the strip get
    # refreshed first. Field order is the sort order.
    tier: int
    generated: int
    overdue_negative_s: float
    engagement_recency_s: float


@frozen
class _Candidate:
    team_id: int
    tier: int
    never_generated: bool
    overdue_s: float
    engagement_recency_s: float

    @property
    def sort_key(self) -> _SortKey:
        return _SortKey(
            tier=self.tier,
            generated=0 if self.never_generated else 1,
            overdue_negative_s=-self.overdue_s,
            engagement_recency_s=self.engagement_recency_s,
        )


def _root_team_q() -> Q:
    # `TeamScopedRootMixin` rows canonicalize to the parent project, so child environments are
    # never planned; their parent's batch is what their inbox reads.
    return Q(parent_team_id__isnull=True) | Q(parent_team_id=F("id"))


def _engagement_by_team(cutoff: datetime, team_ids: Collection[int]) -> dict[int, datetime]:
    """Most recent inbox engagement per team inside the window: report views/ratings, a scout
    someone turned on or off, or a scout someone created. Aggregated in Postgres so the transfer
    is one row per team.

    The config row attributes only those two acts: `status_changed_by` is cleared by system
    transitions and enabled-only writes, and `created_by` is unset on coordinator-registered rows,
    so neither can mistake a system touch for a person. A plain edit carries no actor.

    Restricted to the teams the planner is already considering, so this rides the `team_id` index.
    `SignalReportAction.last_at` is deliberately unindexed, to keep the hot repeat-view UPDATE
    eligible for HOT, which makes an unbounded filter on it a scan of the whole action history.
    """
    if not team_ids:
        return {}
    latest: dict[int, datetime] = {}
    for queryset in (
        SignalReportAction.all_teams.filter(team_id__in=team_ids, last_at__gte=cutoff)
        .values("team_id")
        .annotate(latest=Max("last_at")),
        SignalScoutConfig.all_teams.filter(team_id__in=team_ids)
        .filter(
            Q(updated_at__gte=cutoff, status_changed_by__isnull=False)
            | Q(created_at__gte=cutoff, created_by__isnull=False)
        )
        .values("team_id")
        .annotate(latest=Max("updated_at")),
    ):
        for row in queryset:
            team_id, engaged_at = row["team_id"], row["latest"]
            if team_id not in latest or engaged_at > latest[team_id]:
                latest[team_id] = engaged_at
    return latest


def _candidate_teams_by_tier(settings: SuggestionSettings, now: datetime) -> tuple[dict[int, int], dict[int, datetime]]:
    """Map team_id -> tier for every team in a tier <= `settings.eligibility_tier`, plus the
    engagement map used as the sort tie-break. The tier predicates run as subqueries so only the
    matching ids cross the wire, never the whole approved-team set."""
    if settings.eligibility_tier < 1:
        # Allowlist-only mode: the caller injects the allowlist at tier 0, so there is
        # nothing to compute here.
        return {}, {}
    cutoff = now - timedelta(days=settings.engagement_window_days)

    # A project that has never ingested an event can only be refused by the scan, and this base
    # set feeds every tier. Nothing is stamped on the row, so the project re-enters the queue on
    # its first event; ingestion is environment-scoped, so traffic in a child environment counts.
    ingested_child_teams = Team.objects.filter(ingested_event=True, parent_team_id__isnull=False)
    approved_root_teams = Team.objects.filter(
        _root_team_q(),
        Q(ingested_event=True) | Q(id__in=ingested_child_teams.values("parent_team_id")),
        organization__is_ai_data_processing_approved=True,
    )
    # Source configs are environment-scoped, so a project whose Signals setup lives in a child
    # environment counts through that child's parent; scout configs already canonicalize.
    source_teams = SignalSourceConfig.objects.filter(enabled=True).values("team_id")
    set_up = (
        Q(id__in=source_teams)
        | Q(id__in=Team.objects.filter(id__in=source_teams, parent_team_id__isnull=False).values("parent_team_id"))
        | Q(id__in=SignalScoutConfig.all_teams.filter(enabled=True).values("team_id"))
    )

    tiers: dict[int, int] = {}
    set_up_team_ids = list(approved_root_teams.filter(set_up).values_list("id", flat=True))
    if settings.eligibility_tier >= 3:
        active_member_teams = (
            approved_root_teams.exclude(set_up)
            .filter(organization__membership__user__last_login__gte=cutoff)
            .values_list("id", flat=True)
            .distinct()
        )
        for team_id in active_member_teams:
            tiers[team_id] = 3
    if settings.eligibility_tier >= 4:
        for team_id in approved_root_teams.exclude(set_up).values_list("id", flat=True):
            tiers.setdefault(team_id, 4)
    # Engagement last, over the candidates we actually have: it splits tier 1 from tier 2 and
    # breaks ties in the sort, so it never needs a team the planner would not consider anyway.
    engagement = _engagement_by_team(cutoff, set(set_up_team_ids) | set(tiers))
    for team_id in set_up_team_ids:
        tiers[team_id] = 1 if team_id in engagement else 2
    tiers = {team_id: tier for team_id, tier in tiers.items() if tier <= settings.eligibility_tier}
    return tiers, engagement


def canonical_team_ids(team_ids: Iterable[int]) -> set[int]:
    """Resolve operator-supplied ids to canonical project ids, so a child environment listed in
    the flag payload lands on the same row the planner and the API read. Unknown ids drop out."""
    ids = set(team_ids)
    if not ids:
        return set()
    return {
        parent_id or team_id
        for team_id, parent_id in Team.objects.filter(id__in=ids).values_list("id", "parent_team_id")
    }


def suggestions_allowed_for_team(settings: SuggestionSettings, team_id: int) -> bool:
    """The kill switch and blocklist the planner honors, for the manual refresh path."""
    return settings.enabled and team_id not in canonical_team_ids(settings.team_blocklist)


# How far the failure backoff can double the refresh interval. At the defaults (threshold 3,
# refresh 7 days) a project that keeps failing waits 14 days, then 28, then 56, then 112.
MAX_BREAKER_DOUBLINGS = 4


def _wait_s(consecutive_failures: int, settings: SuggestionSettings, *, refresh_s: float) -> float:
    """How long a team must sit since its last request before it is due again.

    A tripped breaker doubles the refresh interval per failure past the threshold. The cooldown
    alone cannot suppress a scheduled retry, because it is shorter than the refresh window it
    would have to outlast, so a permanently failing project used to spend a scan every refresh
    period no matter how many times it had failed.
    """
    if consecutive_failures < settings.failure_breaker_threshold:
        return refresh_s
    doublings = min(consecutive_failures - settings.failure_breaker_threshold + 1, MAX_BREAKER_DOUBLINGS)
    return refresh_s * (2**doublings)


def plan_suggestion_runs(
    settings: SuggestionSettings, now: datetime | None = None, *, limit: int | None = None
) -> list[PlannedSuggestionRun]:
    """The teams to refresh this tick, best first, capped at `limit` (`max_children_per_tick`).

    The coordinator overselects, because the dispatch-time activity check drops candidates after
    the plan is made and a tick should still fill when several are skipped.

    The queue is recomputed from DB state every tick (no stored queue), so changing eligibility is a
    payload edit, never a migration of queued work. Allowlisted teams are always candidates
    (dogfood / support), blocklisted teams never are, and a team past the failure breaker backs off
    geometrically so a broken project cannot hold a slot every refresh period.
    """
    now = now or timezone.now()
    limit = settings.max_children_per_tick if limit is None else limit
    if not settings.enabled or limit <= 0:
        return []
    tiers, engagement = _candidate_teams_by_tier(settings, now)
    for team_id in canonical_team_ids(settings.team_allowlist):
        tiers.setdefault(team_id, 0)
    for team_id in canonical_team_ids(settings.team_blocklist):
        tiers.pop(team_id, None)
    if not tiers:
        return []

    # One row per ever-planned team, so loading the table beats an IN list the size of the fleet.
    state_by_team = {
        row.team_id: row
        for row in SignalScoutSuggestionSet.all_teams.only(
            "team_id", "status", "last_requested_at", "consecutive_failures", "last_completed_at"
        )
    }
    refresh_s = settings.refresh_days * 86400
    stale_refresh_s = settings.stale_refresh_days * 86400
    cooldown = timedelta(hours=settings.failure_cooldown_hours)
    candidates: list[_Candidate] = []
    for team_id, tier in tiers.items():
        state = state_by_team.get(team_id)
        # The failure backoff does not apply to a quiet project. A `low_activity` stamp runs no
        # scan and resets no count, so a project that tripped the breaker before it went quiet
        # would wait up to 16 refresh windows for its next activity check, and nothing that can
        # happen while it stays quiet would shorten that. The count stays on the row and holds
        # the next scan back again as soon as one runs.
        failures = (
            0
            if state is None or state.status == SignalScoutSuggestionSet.Status.LOW_ACTIVITY
            else state.consecutive_failures
        )
        if state is None or state.last_requested_at is None:
            never_generated, overdue_s = True, float("inf")
        else:
            never_generated = False
            wait_s = _wait_s(failures, settings, refresh_s=refresh_s)
            # A stale batch is due on the shorter window, and so is a failed one, since a failure
            # on a stale row replaces its status and would otherwise push the retry out to the full
            # window. Both only while the project is picking up batches at all — pulling a
            # repeatedly failing one forward would undo the breaker.
            if (
                state.status in (SignalScoutSuggestionSet.Status.STALE, SignalScoutSuggestionSet.Status.FAILED)
                and failures < settings.failure_breaker_threshold
            ):
                wait_s = min(wait_s, stale_refresh_s)
            overdue_s = (now - state.last_requested_at).total_seconds() - wait_s
            if overdue_s < 0:
                continue
        # The cooldown runs from the last attempt, not `updated_at`: a dismissal on the prior
        # batch touches the row too and must not push recovery out. It floors the wait; the
        # backoff above is what actually holds a repeatedly failing project back, since the
        # cooldown is shorter than the refresh window it would have to outlast.
        if (
            state is not None
            and failures >= settings.failure_breaker_threshold
            and state.last_completed_at is not None
            and state.last_completed_at >= now - cooldown
        ):
            continue
        engaged_at = engagement.get(team_id)
        recency = (now - engaged_at).total_seconds() if engaged_at else float("inf")
        candidates.append(
            _Candidate(
                team_id=team_id,
                tier=tier,
                never_generated=never_generated,
                overdue_s=overdue_s,
                engagement_recency_s=recency,
            )
        )
    candidates.sort(key=lambda candidate: candidate.sort_key)
    return [PlannedSuggestionRun(team_id=candidate.team_id, tier=candidate.tier) for candidate in candidates[:limit]]


def stamp_requested(team_ids: list[int], now: datetime | None = None) -> None:
    """Advance `last_requested_at` for the teams a child was dispatched for. Split from planning
    so a fan-out failure re-plans the team next tick instead of silently skipping a refresh."""
    if not team_ids:
        return
    now = now or timezone.now()
    # `bulk_create` skips `save()`, which is fine here: the planner only hands over canonical root
    # team ids, so there is nothing for `TeamScopedRootMixin` to rewrite.
    SignalScoutSuggestionSet.all_teams.bulk_create(
        [SignalScoutSuggestionSet(team_id=team_id) for team_id in team_ids], ignore_conflicts=True
    )
    SignalScoutSuggestionSet.all_teams.filter(team_id__in=team_ids).update(last_requested_at=now)


# ---------------------------------------------------------------------------
# Dispatch-time activity check
# ---------------------------------------------------------------------------


LOW_ACTIVITY_SKIP_REASON = "low_activity"

# TOO_MANY_ROWS / TOO_MANY_ROWS_OR_BYTES: what `read_overflow_mode: throw` raises at
# `ACTIVITY_READ_MAX_ROWS`. Any other failure belongs to the caller's dispatch-anyway path.
_READ_CAP_ERROR_CODES = (158, 396)


@frozen
class TeamActivity:
    """What the bounded read saw for one project inside the activity window."""

    event_count: int
    active_days: int
    # The read refused at `ACTIVITY_READ_MAX_ROWS` rather than answer with a truncated count, so
    # the two fields above hold nothing the check may read.
    capped: bool


@frozen
class ActivitySelection:
    dispatch: tuple[PlannedSuggestionRun, ...]
    skipped_team_ids: tuple[int, ...]


def activity_check_enabled(settings: SuggestionSettings) -> bool:
    return settings.min_events_in_window > 0 or settings.min_active_days_in_window > 0


def read_team_activity(team_id: int, *, window_days: int) -> TeamActivity:
    """Events and distinct active days for a project and its child environments in the window.

    Ingestion is environment-scoped while the batch is per canonical project, so the two are
    counted together. A read that hits the row cap refuses instead of answering, because a
    truncated aggregate is indistinguishable from a quiet project: the events table sorts on
    `toDate(timestamp)`, so the window bound drops rows the cap has already counted, and the
    spread is then a floor with nothing to mark it as one.
    """
    team_ids = list(Team.objects.filter(Q(id=team_id) | Q(parent_team_id=team_id)).values_list("id", flat=True))
    tag_queries(
        product=Product.SIGNALS,
        feature=Feature.DATA_FRESHNESS,
        query_type="SignalsScoutSuggestionsActivityCheck",
        trigger="signals_scout_suggestions_activity_check",
    )
    try:
        rows = sync_execute(
            """
            SELECT count(), uniqExact(toDate(timestamp))
            FROM events
            WHERE team_id IN %(team_ids)s
              AND timestamp >= now() - toIntervalDay(%(window_days)s)
            """,
            {"team_ids": team_ids, "window_days": window_days},
            # A scheduled fleet scan belongs off the interactive cluster: a tick reads one
            # candidate after another, and the per-tick cap is flag-tunable.
            workload=Workload.OFFLINE,
            settings={
                "max_rows_to_read": ACTIVITY_READ_MAX_ROWS,
                "read_overflow_mode": "throw",
                "max_execution_time": ACTIVITY_READ_MAX_EXECUTION_S,
                # Both overflow modes throw for the same reason: a partial aggregate reads as a
                # quiet project. A timed-out read raises instead, and the caller dispatches.
                "timeout_overflow_mode": "throw",
            },
            team_id=team_id,
        )
    except InternalCHQueryError as error:
        if error.code not in _READ_CAP_ERROR_CODES:
            raise
        return TeamActivity(event_count=ACTIVITY_READ_MAX_ROWS, active_days=0, capped=True)
    event_count = int(rows[0][0]) if rows else 0
    active_days = int(rows[0][1]) if rows else 0
    return TeamActivity(event_count=event_count, active_days=active_days, capped=False)


def team_is_active_enough(activity: TeamActivity, settings: SuggestionSettings) -> bool:
    if activity.capped:
        return True
    if settings.min_events_in_window and activity.event_count < settings.min_events_in_window:
        return False
    if settings.min_active_days_in_window and activity.active_days < settings.min_active_days_in_window:
        return False
    return True


def select_teams_to_scan(
    planned: Iterable[PlannedSuggestionRun], settings: SuggestionSettings, *, limit: int
) -> ActivitySelection:
    """The planned candidates worth a scan, in order, up to `limit`.

    One bounded read per candidate, over the picked set only, never over the pool. A project
    under either activity line is stamped `low_activity` and reported as a skipped run rather
    than dispatched, because the scan could only refuse it. Candidates past `limit` are left
    untouched, so a tick that fills early re-plans them next tick. Allowlisted projects are
    scanned whatever the read says, for dogfood and support.
    """
    candidates = list(planned)
    if not activity_check_enabled(settings):
        return ActivitySelection(dispatch=tuple(candidates[:limit]), skipped_team_ids=())
    exempt = canonical_team_ids(settings.team_allowlist)
    dispatch: list[PlannedSuggestionRun] = []
    skipped: list[int] = []
    for run in candidates:
        if len(dispatch) >= limit:
            break
        if run.team_id in exempt:
            dispatch.append(run)
            continue
        try:
            activity = read_team_activity(run.team_id, window_days=settings.activity_window_days)
        except Exception:
            # A read that cannot answer must not cost the project its refresh window.
            logger.warning("scout_suggestions: activity read failed", team_id=run.team_id, exc_info=True)
            dispatch.append(run)
            continue
        if team_is_active_enough(activity, settings):
            dispatch.append(run)
            continue
        skipped.append(run.team_id)
        _record_low_activity(run.team_id, activity=activity, settings=settings, tier=run.tier)
    return ActivitySelection(dispatch=tuple(dispatch), skipped_team_ids=tuple(skipped))


def _skip_event_uuid(team_id: int, *, requested_at: datetime | None) -> str:
    """One id per skip decision, so a retry of the planning activity does not count it twice.

    `last_requested_at` is stamped after fan-out, so it reads the same on every attempt of one
    tick and a different value by the time the project is due again.
    """
    return str(uuid5(NAMESPACE_URL, f"{LOW_ACTIVITY_SKIP_REASON}:{team_id}:{requested_at}"))


def _record_low_activity(
    team_id: int, *, activity: TeamActivity, settings: SuggestionSettings, tier: int | None
) -> None:
    row = mark_low_activity(team_id)
    team = Team.objects.select_related("organization").filter(id=team_id).first()
    if team is None:
        return
    capture_suggestions_generated(
        team,
        status="skipped",
        skip_reason=LOW_ACTIVITY_SKIP_REASON,
        tier=tier,
        event_uuid=_skip_event_uuid(team_id, requested_at=row.last_requested_at),
        extra_properties={
            "activity_window_days": settings.activity_window_days,
            "activity_event_count": activity.event_count,
            "activity_active_days": activity.active_days,
        },
    )


def capture_suggestions_generated(
    team: Team,
    *,
    status: str,
    skip_reason: str | None = None,
    suggestion_count: int = 0,
    runtime_s: float = 0.0,
    task_run_id: str | None = None,
    tier: int | None = None,
    model: str | None = None,
    triggered_by: str = "schedule",
    event_uuid: str | None = None,
    extra_properties: dict[str, Any] | None = None,
) -> None:
    """The one emitter of `$scout_suggestions_generated`, so a completed run and a skipped one
    are read from the same event and the daily roll-up needs no new column.

    `event_uuid` dedupes the emitters that can run twice for one decision. A completed run needs
    none: its activity runs at most once.
    """
    try:
        posthoganalytics.capture(
            event="$scout_suggestions_generated",
            distinct_id=str(team.uuid),
            uuid=event_uuid,
            properties={
                "team_id": team.id,
                "status": status,
                "skip_reason": skip_reason,
                "suggestion_count": suggestion_count,
                "runtime_s": round(runtime_s, 1),
                "task_run_id": task_run_id,
                "tier": tier,
                "model": model,
                "triggered_by": triggered_by,
                **(extra_properties or {}),
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.warning("scout_suggestions: failed to capture generated event", team_id=team.id)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


@frozen
class FleetContext:
    enabled_skill_names: tuple[str, ...]
    available_canonical: tuple[tuple[str, str], ...]  # (name, description) not yet enabled
    # Names a custom draft may not take: every scout config on the project (enabled or not) and
    # every `signals-scout-*` skill already stored, since create returns 409 when a name's stored
    # definition differs from the draft.
    reserved_names: frozenset[str] = frozenset()


def enabled_skill_names(team_id: int) -> list[str]:
    """The project's enabled scout skill names, sorted, as `fleet_snapshot` stores them."""
    return sorted(SignalScoutConfig.objects.for_team(team_id).filter(enabled=True).values_list("skill_name", flat=True))


def reserved_scout_names(team_id: int) -> frozenset[str]:
    """Names a custom draft may not take: every scout config on the project (enabled or not) and
    every stored skill, since create answers a differing definition with 409.

    A scout may carry any valid skill name, so every skill name is a possible collision — the
    scan is no longer narrowed to the `signals-scout-*` prefix."""
    reserved = set(SignalScoutConfig.objects.for_team(team_id).values_list("skill_name", flat=True))
    reserved.update(
        LLMSkill.objects.filter(
            team_id=resolve_effective_team_id(team_id),
            is_latest=True,
            deleted=False,
        ).values_list("name", flat=True)
    )
    return frozenset(reserved)


def fleet_context(team_id: int) -> FleetContext:
    enabled = tuple(enabled_skill_names(team_id))
    try:
        canonical = discover_canonical_skills()
    except CanonicalSkillParseError:
        canonical = ()
    enabled_set = set(enabled)
    # A held-back canonical scout is not seeded by the sync path and the config API refuses to
    # enable it, so offering it would surface an unreleased scout behind a Create that must fail.
    withheld = withheld_skills_for_team(resolve_effective_team_id(team_id))
    available = tuple(
        (skill.name, skill.description)
        for skill in canonical
        if skill.name not in enabled_set and skill.name not in withheld
    )
    return FleetContext(
        enabled_skill_names=enabled, available_canonical=available, reserved_names=reserved_scout_names(team_id)
    )


def build_suggestions_prompt(fleet: FleetContext) -> str:
    schema = json.dumps(ScoutSuggestionBatch.model_json_schema(), indent=2)
    enabled_lines = "\n".join(f"- {name}" for name in fleet.enabled_skill_names) or "- (none yet)"
    canonical_lines = (
        "\n".join(f"- `{name}`: {description}" for name, description in fleet.available_canonical) or "- (none)"
    )
    return f"""You are preparing the "Suggested for this project" list for the PostHog scouts tab. Nobody is in the chat with you: work headlessly and end your turn with the JSON object described at the bottom.

First, {SCOUT_PROJECT_SCAN_GUIDANCE} Use the read-data, insight, dashboard, and signals-scout MCP tools (config list for the fleet, recent runs and reports for what the scouts already surface). Read the authoring-scouts skill from the PostHog MCP (`skill-get`) before drafting any custom scout; if it is unavailable, write the draft in the same shape as the canonical scout bodies.

Scouts currently enabled on this project:
{enabled_lines}

PostHog-authored scouts available to turn on (suggest these by exact name with kind "canonical"):
{canonical_lines}

Produce {MIN_SUGGESTIONS_PER_BATCH}-{MAX_SUGGESTIONS_PER_BATCH} suggestions, best first:
- Mix "canonical" picks (cheap, high-confidence "turn this on") with at least one or two "custom" drafts tailored to what you found (a specific funnel, a custom event, an error or latency spike, a churn, activation, or revenue signal), so the set is project-specific rather than a template list.
- Every `why_here` must cite concrete evidence you actually saw: event names, insight or dashboard names, report titles, volumes. Never suggest something the project has no data for.
- Do not suggest a scout that is already enabled, and set `gap` only when nothing in the fleet covers the same ground.
- A custom draft needs a `skill_name` starting with `signals-scout-`, a one-line `description`, and a complete `draft_body` following the authoring-scouts skill: what to check, thresholds, what counts as a finding, what to ignore, how to dedupe against prior runs. Keep the `description` under {MAX_DESCRIPTION_CHARS} characters and the body under {MAX_DRAFT_BODY_CHARS}.
- Leave Slack delivery out of `proposed_config`; the person choosing the suggestion picks the destination.
- If the project genuinely has too little data to suggest anything, return an empty list and say why in `notes`.

End your turn with ONLY a JSON object matching this schema (no prose before or after it):

{schema}
"""


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _item_record(item: ScoutSuggestionItem, *, prior: dict[str, Any] | None) -> dict[str, Any]:
    prior = prior or {}
    record = item.model_dump()
    record["id"] = prior.get("id") or str(uuid7())
    # A dismissed suggestion must not resurrect on the next refresh; carry the flag by skill_name.
    record["dismissed_at"] = prior.get("dismissed_at")
    record["dismissed_by_id"] = prior.get("dismissed_by_id")
    record["created_config_id"] = prior.get("created_config_id")
    return record


def _is_tombstone(record: dict[str, Any]) -> bool:
    """A record `_tombstone` compacted: dismissal bookkeeping with none of the item fields left."""
    return "kind" not in record


def _tombstone(record: dict[str, Any]) -> dict[str, Any]:
    """A dismissed suggestion the new batch dropped, reduced to what a later batch needs to know.
    Carrying the whole record would keep a 20,000-character draft body in the row forever, and
    every read, dismissal and refresh pays to load and rewrite it under the row lock."""
    return {
        "id": record.get("id"),
        "skill_name": record.get("skill_name"),
        "dismissed_at": record.get("dismissed_at"),
        "dismissed_by_id": record.get("dismissed_by_id"),
        "created_config_id": record.get("created_config_id"),
    }


def _lock_row(team_id: int, *, create: bool) -> SignalScoutSuggestionSet | None:
    """The team's row, locked for the enclosing transaction. Every write to `items` is a
    read-modify-write of one JSON column, so a dismissal racing a refresh (or two dismissals)
    serializes here instead of the later save dropping the earlier change."""
    team_id = resolve_effective_team_id(team_id)
    if create:
        SignalScoutSuggestionSet.all_teams.get_or_create(team_id=team_id)
    return SignalScoutSuggestionSet.objects.for_team(team_id, canonical=True).select_for_update().first()


def persist_suggestion_batch(
    team_id: int,
    items: list[ScoutSuggestionItem],
    *,
    task_run_id: str | None,
    model: str | None,
    fleet_snapshot: list[str],
    now: datetime | None = None,
) -> SignalScoutSuggestionSet:
    """Replace the team's batch with `items`, carrying forward per-item dismissal and created
    state for any suggestion that survives by `skill_name`. Dismissed suggestions the new batch
    does not repeat stay as hidden tombstones, so a skill dismissed two refreshes ago does not
    resurface the next time the model proposes it."""
    now = now or timezone.now()
    with transaction.atomic():
        row = _lock_row(team_id, create=True)
        assert row is not None
        prior_by_name = {record.get("skill_name"): record for record in (row.items or []) if isinstance(record, dict)}
        records = [_item_record(item, prior=prior_by_name.get(item.skill_name)) for item in items]
        suggested = {item.skill_name for item in items}
        records.extend(
            _tombstone(record)
            for name, record in prior_by_name.items()
            if record.get("dismissed_at") and name not in suggested
        )
        row.items = records
        row.fleet_snapshot = sorted(fleet_snapshot)
        # The fleet can move while the scan runs; a batch generated against the old fleet is
        # stored, but reported as stale, the same as the config receiver would flag it later.
        # Fleet first: "nothing to suggest" reached against a fleet that has since moved is as
        # stale as any other conclusion, and nothing would revisit it before the next refresh.
        if enabled_skill_names(row.team_id) != row.fleet_snapshot:
            row.status = SignalScoutSuggestionSet.Status.STALE
        elif not items:
            row.status = SignalScoutSuggestionSet.Status.EMPTY
        else:
            row.status = SignalScoutSuggestionSet.Status.FRESH
        row.generated_at = now
        row.last_completed_at = now
        row.task_run_id = UUID(task_run_id) if task_run_id else None
        row.model = model or ""
        row.consecutive_failures = 0
        row.save(
            update_fields=[
                "items",
                "status",
                "generated_at",
                "last_completed_at",
                "task_run_id",
                "model",
                "fleet_snapshot",
                "consecutive_failures",
                "updated_at",
            ]
        )
    return row


def mark_generation_failed(team_id: int, *, task_run_id: str | None) -> SignalScoutSuggestionSet:
    """A failed generation keeps the prior items readable and counts toward the breaker."""
    with transaction.atomic():
        row = _lock_row(team_id, create=True)
        assert row is not None
        row.status = SignalScoutSuggestionSet.Status.FAILED
        row.consecutive_failures += 1
        row.last_completed_at = timezone.now()
        if task_run_id:
            row.task_run_id = UUID(task_run_id)
        row.save(update_fields=["status", "consecutive_failures", "last_completed_at", "task_run_id", "updated_at"])
    return row


def mark_low_activity(team_id: int) -> SignalScoutSuggestionSet:
    """A project too quiet to scan. The prior items stay readable, the same as a failed
    generation, and the failure breaker is left alone: a quiet project is not a broken one. The
    planner re-checks it once the refresh window passes, so traffic picked up in the meantime
    costs at most one window."""
    with transaction.atomic():
        row = _lock_row(team_id, create=True)
        assert row is not None
        row.status = SignalScoutSuggestionSet.Status.LOW_ACTIVITY
        row.last_completed_at = timezone.now()
        row.save(update_fields=["status", "last_completed_at", "updated_at"])
    return row


# A generated conclusion, with or without items; `failed` and `stale` already say what they are.
_EXPIRING_STATUSES = (SignalScoutSuggestionSet.Status.FRESH, SignalScoutSuggestionSet.Status.EMPTY)


def effective_status(row: SignalScoutSuggestionSet, *, refresh_days: int) -> str:
    """The row's status with expiry applied. Only the fleet-change receiver writes `STALE`, so a
    batch that simply aged past its refresh window would otherwise keep reporting `fresh` (or a
    "nothing to suggest" conclusion `empty`) for as long as the planner does not reach it, which
    is forever while scheduling is off."""
    if row.status not in _EXPIRING_STATUSES or row.generated_at is None:
        return row.status
    if timezone.now() - row.generated_at >= timedelta(days=refresh_days):
        return SignalScoutSuggestionSet.Status.STALE
    return row.status


def visible_items(
    row: SignalScoutSuggestionSet,
    *,
    enabled_skill_names: Collection[str] = (),
    reserved_names: Collection[str] = (),
) -> list[dict[str, Any]]:
    """The batch minus dismissed, already-created, and already-enabled items, in stored
    (best-first) order. Pass the project's enabled names so a scout someone turned on through the
    normal config API disappears without waiting for `mark_suggestion_created`, and its reserved
    names so a custom draft whose name was since taken (a stored skill or a disabled config, which
    Create answers with 409) is hidden too. Canonical items ignore `reserved_names` — a disabled
    canonical scout is exactly what those items offer to enable."""
    enabled = set(enabled_skill_names)
    reserved = set(reserved_names)
    return [
        record
        for record in (row.items or [])
        if isinstance(record, dict)
        and not record.get("dismissed_at")
        and not record.get("created_config_id")
        and record.get("skill_name") not in enabled
        and not (record.get("kind") == "custom" and record.get("skill_name") in reserved)
    ]


def find_suggestion(team_id: int, suggestion_id: str) -> dict[str, Any] | None:
    """One stored suggestion by id, or None when the batch never held it or has compacted it away.

    Unlike `visible_items` this keeps dismissed and created records, so a caller acting on an id it
    was handed a moment ago still resolves it after a concurrent dismiss.
    """
    row = SignalScoutSuggestionSet.objects.for_team(team_id, canonical=True).first()
    if row is None:
        return None
    for record in row.items or []:
        if isinstance(record, dict) and record.get("id") == suggestion_id and not _is_tombstone(record):
            return record
    return None


def _update_item(team_id: int, suggestion_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    with transaction.atomic():
        row = _lock_row(team_id, create=False)
        if row is None:
            return None
        updated: dict[str, Any] | None = None
        items = []
        for record in row.items or []:
            # A compacted tombstone keeps its id but is no longer a suggestion, so a duplicate
            # dismiss of one reads as gone rather than returning a record with no item fields.
            if isinstance(record, dict) and record.get("id") == suggestion_id and not _is_tombstone(record):
                record = {**record, **changes}
                updated = record
            items.append(record)
        if updated is None:
            return None
        row.items = items
        row.save(update_fields=["items", "updated_at"])
    return updated


def dismiss_suggestion(team_id: int, suggestion_id: str, *, user_id: int | None) -> dict[str, Any] | None:
    return _update_item(
        team_id,
        suggestion_id,
        {"dismissed_at": timezone.now().isoformat(), "dismissed_by_id": user_id},
    )


def mark_suggestion_created(team_id: int, suggestion_id: str, *, config_id: str) -> dict[str, Any] | None:
    return _update_item(team_id, suggestion_id, {"created_config_id": config_id})


def mark_stale_if_fleet_changed(team_id: int) -> None:
    """Called when a scout is created or deleted: a batch generated against a different fleet is
    marked stale so the UI can say so; regeneration waits for the normal refresh."""
    with transaction.atomic():
        row = _lock_row(team_id, create=False)
        if row is None or row.status not in (
            SignalScoutSuggestionSet.Status.FRESH,
            SignalScoutSuggestionSet.Status.EMPTY,
        ):
            return
        if enabled_skill_names(team_id) != list(row.fleet_snapshot or []):
            row.status = SignalScoutSuggestionSet.Status.STALE
            row.save(update_fields=["status", "updated_at"])


__all__ = [
    "ACTIVITY_READ_MAX_ROWS",
    "LOW_ACTIVITY_SKIP_REASON",
    "MAX_SUGGESTIONS_PER_BATCH",
    "SIGNALS_SCOUT_SUGGESTIONS_FLAG",
    "SUGGESTIONS_ACTIVITY_SLACK_S",
    "SUGGESTIONS_AI_STAGE",
    "SUGGESTIONS_MAX_RUNTIME_S",
    "ActivitySelection",
    "PlannedSuggestionRun",
    "ScoutSuggestionBatch",
    "ScoutSuggestionItem",
    "SuggestionSettings",
    "TeamActivity",
    "activity_check_enabled",
    "build_suggestions_prompt",
    "canonical_team_ids",
    "capture_suggestions_generated",
    "dismiss_suggestion",
    "enabled_skill_names",
    "find_suggestion",
    "fleet_context",
    "mark_generation_failed",
    "mark_low_activity",
    "mark_stale_if_fleet_changed",
    "mark_suggestion_created",
    "parse_suggestion_settings",
    "persist_suggestion_batch",
    "plan_suggestion_runs",
    "read_suggestion_settings",
    "read_team_activity",
    "reserved_scout_names",
    "select_teams_to_scan",
    "stamp_requested",
    "suggestions_allowed_for_team",
    "team_is_active_enough",
    "visible_items",
]
