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
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from django.db.models import F, Max, Q
from django.utils import timezone

import structlog
from pydantic import BaseModel, Field

from posthog.dataclasses import frozen
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
from products.signals.backend.scout_harness.team_limits import read_flag_payload

logger = structlog.get_logger(__name__)

SIGNALS_SCOUT_SUGGESTIONS_FLAG = "signals-scout-suggestions"

# A scan plus 3-5 suggestions is a fraction of a scout run; the ceiling exists so a wedged
# sandbox cannot hold a worker slot for a scout-length run.
SUGGESTIONS_MAX_RUNTIME_S = 10 * 60
SUGGESTIONS_ACTIVITY_SLACK_S = 60

MAX_SUGGESTIONS_PER_BATCH = 5
MIN_SUGGESTIONS_PER_BATCH = 3
MAX_DRAFT_BODY_CHARS = 20_000

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
    # The planner includes every tier <= this (see `_candidate_teams_by_tier`). 1 = engaged
    # self-driving projects only; 4 = every AI-approved team.
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
        eligibility_tier=_int_in(payload, "eligibility_tier", 1, low=1, high=4),
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


@frozen
class _Candidate:
    team_id: int
    tier: int
    never_generated: bool
    overdue_s: float
    engagement_recency_s: float

    @property
    def sort_key(self) -> tuple[int, int, float, float]:
        # Tier first, never-generated before generated, most overdue first, then the project
        # someone looked at most recently, so when the cap bites the teams who will see the strip
        # get refreshed first.
        return (self.tier, 0 if self.never_generated else 1, -self.overdue_s, self.engagement_recency_s)


def _root_team_q() -> Q:
    # `TeamScopedRootMixin` rows canonicalize to the parent project, so child environments are
    # never planned; their parent's batch is what their inbox reads.
    return Q(parent_team_id__isnull=True) | Q(parent_team_id=F("id"))


def _engagement_by_team(cutoff: datetime) -> dict[int, datetime]:
    """Most recent inbox engagement per team inside the window: report views/ratings or a scout
    config someone touched. Aggregated in Postgres so the transfer is one row per team."""
    latest: dict[int, datetime] = {}
    for queryset in (
        SignalReportAction.all_teams.filter(last_at__gte=cutoff).values("team_id").annotate(latest=Max("last_at")),
        SignalScoutConfig.all_teams.filter(updated_at__gte=cutoff, status_changed_by__isnull=False)
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
    cutoff = now - timedelta(days=settings.engagement_window_days)
    engagement = _engagement_by_team(cutoff)

    approved_root_teams = Team.objects.filter(_root_team_q(), organization__is_ai_data_processing_approved=True)
    set_up = Q(id__in=SignalSourceConfig.objects.filter(enabled=True).values("team_id")) | Q(
        id__in=SignalScoutConfig.all_teams.filter(enabled=True).values("team_id")
    )

    tiers: dict[int, int] = {}
    for team_id in approved_root_teams.filter(set_up).values_list("id", flat=True):
        tiers[team_id] = 1 if team_id in engagement else 2
    if settings.eligibility_tier >= 3:
        active_member_teams = (
            approved_root_teams.exclude(set_up)
            .filter(organization__memberships__user__last_login__gte=cutoff)
            .values_list("id", flat=True)
            .distinct()
        )
        for team_id in active_member_teams:
            tiers[team_id] = 3
    if settings.eligibility_tier >= 4:
        for team_id in approved_root_teams.exclude(set_up).values_list("id", flat=True):
            tiers.setdefault(team_id, 4)
    tiers = {team_id: tier for team_id, tier in tiers.items() if tier <= settings.eligibility_tier}
    return tiers, engagement


def plan_suggestion_runs(settings: SuggestionSettings, now: datetime | None = None) -> list[PlannedSuggestionRun]:
    """The teams to refresh this tick, best first, capped at `max_children_per_tick`.

    The queue is recomputed from DB state every tick (no stored queue), so changing eligibility is a
    payload edit, never a migration of queued work. Allowlisted teams are always candidates
    (dogfood / support), blocklisted teams never are, and a team past the failure breaker waits out
    its cooldown so a broken project cannot hold a slot every tick.
    """
    now = now or timezone.now()
    if not settings.enabled or settings.max_children_per_tick == 0:
        return []
    tiers, engagement = _candidate_teams_by_tier(settings, now)
    for team_id in settings.team_allowlist:
        tiers.setdefault(team_id, 0)
    for team_id in settings.team_blocklist:
        tiers.pop(team_id, None)
    if not tiers:
        return []

    # One row per ever-planned team, so loading the table beats an IN list the size of the fleet.
    state_by_team = {
        row.team_id: row
        for row in SignalScoutSuggestionSet.all_teams.only(
            "team_id", "last_requested_at", "consecutive_failures", "updated_at"
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
            overdue_s = (now - state.last_requested_at).total_seconds() - refresh_s
            if overdue_s < 0:
                continue
        if (
            state is not None
            and state.consecutive_failures >= settings.failure_breaker_threshold
            and state.updated_at >= now - cooldown
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


def fleet_context(team_id: int) -> FleetContext:
    enabled = tuple(
        sorted(SignalScoutConfig.all_teams.filter(team_id=team_id, enabled=True).values_list("skill_name", flat=True))
    )
    try:
        canonical = discover_canonical_skills()
    except CanonicalSkillParseError:
        canonical = ()
    enabled_set = set(enabled)
    available = tuple((skill.name, skill.description) for skill in canonical if skill.name not in enabled_set)
    return FleetContext(enabled_skill_names=enabled, available_canonical=available)


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
- A custom draft needs a `skill_name` starting with `signals-scout-`, a one-line `description`, and a complete `draft_body` following the authoring-scouts skill: what to check, thresholds, what counts as a finding, what to ignore, how to dedupe against prior runs. Keep it under {MAX_DRAFT_BODY_CHARS} characters.
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
    state for any suggestion that survives by `skill_name`."""
    now = now or timezone.now()
    row, _ = SignalScoutSuggestionSet.all_teams.get_or_create(team_id=team_id)
    prior_by_name = {record.get("skill_name"): record for record in (row.items or []) if isinstance(record, dict)}
    row.items = [_item_record(item, prior=prior_by_name.get(item.skill_name)) for item in items]
    row.status = SignalScoutSuggestionSet.Status.FRESH if items else SignalScoutSuggestionSet.Status.EMPTY
    row.generated_at = now
    row.last_completed_at = now
    row.task_run_id = UUID(task_run_id) if task_run_id else None
    row.model = model or ""
    row.fleet_snapshot = sorted(fleet_snapshot)
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
    row, _ = SignalScoutSuggestionSet.all_teams.get_or_create(team_id=team_id)
    row.status = SignalScoutSuggestionSet.Status.FAILED
    row.consecutive_failures += 1
    row.last_completed_at = timezone.now()
    if task_run_id:
        row.task_run_id = UUID(task_run_id)
    row.save(update_fields=["status", "consecutive_failures", "last_completed_at", "task_run_id", "updated_at"])
    return row


def visible_items(row: SignalScoutSuggestionSet) -> list[dict[str, Any]]:
    """The batch minus dismissed and already-created items, in stored (best-first) order."""
    return [
        record
        for record in (row.items or [])
        if isinstance(record, dict) and not record.get("dismissed_at") and not record.get("created_config_id")
    ]


def _update_item(team_id: int, suggestion_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    row = SignalScoutSuggestionSet.all_teams.filter(team_id=team_id).first()
    if row is None:
        return None
    updated: dict[str, Any] | None = None
    items = []
    for record in row.items or []:
        if isinstance(record, dict) and record.get("id") == suggestion_id:
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
    row = SignalScoutSuggestionSet.all_teams.filter(team_id=team_id).first()
    if row is None or row.status != SignalScoutSuggestionSet.Status.FRESH:
        return
    enabled = sorted(
        SignalScoutConfig.all_teams.filter(team_id=team_id, enabled=True).values_list("skill_name", flat=True)
    )
    if enabled != list(row.fleet_snapshot or []):
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
    "dismiss_suggestion",
    "fleet_context",
    "mark_generation_failed",
    "mark_stale_if_fleet_changed",
    "mark_suggestion_created",
    "parse_suggestion_settings",
    "persist_suggestion_batch",
    "plan_suggestion_runs",
    "read_suggestion_settings",
    "stamp_requested",
    "visible_items",
]
