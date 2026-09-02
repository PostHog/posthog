"""Pre-computed scout suggestions: the push-side twin of the "Suggest a scout" chat.

The chat button mints a `SIGNALS_CHAT` task the user then waits on while the agent scans the
project. This module runs the same scan ahead of time, headless, for every eligible project and
stores 3-5 structured suggestions on `SignalScoutSuggestionSet`, so the scouts tab can offer them
with zero wait. Three pieces live here, all temporalio-free and cheap to import:

- the structured-output contract the headless run returns (`ScoutSuggestionBatch`)
- the planner: which teams to refresh this tick, in priority order (`plan_suggestion_runs`)
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
from uuid import UUID

from django.db import transaction
from django.db.models import F, Max, Q
from django.utils import timezone

import structlog
from pydantic import BaseModel, Field

from posthog.dataclasses import frozen
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
from products.signals.backend.scout_harness.skill_loader import SIGNALS_SCOUT_SKILL_PREFIX
from products.signals.backend.scout_harness.team_limits import read_flag_payload, withheld_skills_for_team
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
# Mirrors `SignalScoutCreateSerializer.description`: a longer one stores fine but fails the
# create it is supposed to be ready for.
MAX_DESCRIPTION_CHARS = 4_096

# Tags every $ai_generation a suggestion run makes, so its spend is splittable out of the
# `ai_product='signals'` bucket next to `scout:<skill>` (see `runner._ai_stage`).
SUGGESTIONS_AI_STAGE = "scout_suggestions"

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
    max_children_per_tick: int = 10
    team_allowlist: frozenset[int] = frozenset()
    team_blocklist: frozenset[int] = frozenset()
    failure_breaker_threshold: int = 3
    failure_cooldown_hours: int = 24
    max_runtime_s: int = SUGGESTIONS_MAX_RUNTIME_S


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
        max_children_per_tick=_int_in(payload, "max_children_per_tick", 10, low=0, high=500),
        team_allowlist=_team_id_set(payload, "team_allowlist"),
        team_blocklist=_team_id_set(payload, "team_blocklist"),
        failure_breaker_threshold=_int_in(payload, "failure_breaker_threshold", 3, low=1, high=100),
        failure_cooldown_hours=_int_in(payload, "failure_cooldown_hours", 24, low=1, high=24 * 30),
        max_runtime_s=_int_in(payload, "max_runtime_s", SUGGESTIONS_MAX_RUNTIME_S, low=60, high=30 * 60),
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

    approved_root_teams = Team.objects.filter(_root_team_q(), organization__is_ai_data_processing_approved=True)
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


def plan_suggestion_runs(settings: SuggestionSettings, now: datetime | None = None) -> list[PlannedSuggestionRun]:
    """The teams to refresh this tick, best first, capped at `max_children_per_tick`.

    The queue is recomputed from DB state every tick (no stored queue), so changing eligibility is a
    payload edit, never a migration of queued work. Allowlisted teams are always candidates
    (dogfood / support), blocklisted teams never are, and a team past the failure breaker backs off
    geometrically so a broken project cannot hold a slot every refresh period.
    """
    now = now or timezone.now()
    if not settings.enabled or settings.max_children_per_tick == 0:
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
            "team_id", "last_requested_at", "consecutive_failures", "last_completed_at"
        )
    }
    refresh_s = settings.refresh_days * 86400
    cooldown = timedelta(hours=settings.failure_cooldown_hours)
    candidates: list[_Candidate] = []
    for team_id, tier in tiers.items():
        state = state_by_team.get(team_id)
        if state is None or state.last_requested_at is None:
            never_generated, overdue_s = True, float("inf")
        else:
            never_generated = False
            overdue_s = (now - state.last_requested_at).total_seconds() - _wait_s(
                state.consecutive_failures, settings, refresh_s=refresh_s
            )
            if overdue_s < 0:
                continue
        # The cooldown runs from the last attempt, not `updated_at`: a dismissal on the prior
        # batch touches the row too and must not push recovery out. It floors the wait; the
        # backoff above is what actually holds a repeatedly failing project back, since the
        # cooldown is shorter than the refresh window it would have to outlast.
        if (
            state is not None
            and state.consecutive_failures >= settings.failure_breaker_threshold
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
    return [
        PlannedSuggestionRun(team_id=candidate.team_id, tier=candidate.tier)
        for candidate in candidates[: settings.max_children_per_tick]
    ]


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
    every stored `signals-scout-*` skill, since create answers a differing definition with 409."""
    reserved = set(SignalScoutConfig.objects.for_team(team_id).values_list("skill_name", flat=True))
    reserved.update(
        LLMSkill.objects.filter(
            team_id=resolve_effective_team_id(team_id),
            is_latest=True,
            deleted=False,
            name__startswith=SIGNALS_SCOUT_SKILL_PREFIX,
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
    "MAX_SUGGESTIONS_PER_BATCH",
    "SIGNALS_SCOUT_SUGGESTIONS_FLAG",
    "SUGGESTIONS_ACTIVITY_SLACK_S",
    "SUGGESTIONS_AI_STAGE",
    "SUGGESTIONS_MAX_RUNTIME_S",
    "PlannedSuggestionRun",
    "ScoutSuggestionBatch",
    "ScoutSuggestionItem",
    "SuggestionSettings",
    "build_suggestions_prompt",
    "canonical_team_ids",
    "dismiss_suggestion",
    "enabled_skill_names",
    "fleet_context",
    "mark_generation_failed",
    "mark_stale_if_fleet_changed",
    "mark_suggestion_created",
    "parse_suggestion_settings",
    "persist_suggestion_batch",
    "plan_suggestion_runs",
    "read_suggestion_settings",
    "reserved_scout_names",
    "stamp_requested",
    "suggestions_allowed_for_team",
    "visible_items",
]
