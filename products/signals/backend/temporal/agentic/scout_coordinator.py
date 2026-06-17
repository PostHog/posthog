from __future__ import annotations

import json
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

import structlog
import posthoganalytics
from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.cloud_utils import is_cloud
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.config_registry import register_missing_configs
from products.signals.backend.scout_harness.lazy_seed import sync_canonical_skills
from products.signals.backend.temporal.agentic.scout_scheduler import RunSignalsScoutInput, RunSignalsScoutWorkflow

logger = structlog.get_logger(__name__)

# Team-level dogfood gate. The single team gate (no per-team model boolean): the flag's JSON
# payload picks which teams run scouts; per-scout SignalScoutConfig rows pick which
# scouts/schedules.
SIGNALS_SCOUT_DOGFOOD_FLAG = "signals-scout"

# Fixed distinct_id for the payload read — enrollment is team-list-in-payload, not per-user.
SIGNALS_SCOUT_DISCOVERY_DISTINCT_ID = "internal_signals_scout_team_discovery"

# Fail-safe allowlist used when the flag payload is missing/invalid — but only on PostHog
# Cloud or local dev (see `_fallback_team_ids`). 1 (local dev), 2 (internal), 148051 (dev).
DEFAULT_ENROLLED_TEAM_IDS: list[int] = [1, 2, 148051]

# Hard cap on dispatches per tick. The cost bound: when more scouts are due than this,
# we run the most-overdue first and the rest catch up next tick (a poor-man's queue).
# Set generously for now while scouts roll out to more teams — the per-team tick cap and
# round-robin allocation do the day-to-day fairness work; this is the global ceiling.
MAX_RUNS_PER_TICK = 1000

# Per-team slice of the tick budget. Bounds what one team can consume per tick (and thus
# per day: cap × ticks/day), so a team registering many scouts degrades its own cadence,
# not everyone else's. Sized well above the canonical fleet (~16 scouts) so a fully-enrolled
# team is never trimmed; round-robin allocation still keeps any one team from starving the
# others even when this is close to the global cap. This is the DEFAULT — a per-team override
# takes precedence when set in the `signals-scout` flag payload under `team_configs` (see
# `_team_configs`), to give an important dogfooder more headroom or hold a noisy one lower,
# no deploy.
MAX_RUNS_PER_TEAM_PER_TICK = 50

# Key inside a team's `team_configs` entry that overrides `MAX_RUNS_PER_TEAM_PER_TICK` for that
# team. `team_configs` is a forward-looking per-team override bag — add more keys here as other
# settings become per-team-tunable; each consumer reads + validates the key it cares about.
TEAM_CONFIG_MAX_RUNS_PER_TICK = "max_runs_per_tick"

# Coordinator tick cadence. Per-scout schedules are enforced via the due-check, so this is
# just the polling granularity — the floor on how often any scout can run.
COORDINATOR_INTERVAL_MINUTES = 30

# Slack on the due-check so a scout that's a few seconds short at a tick still counts as due —
# else stamp jitter makes it skip every other tick (a 60-min scout runs every 2h).
DUE_GRACE_SECONDS = 60


@dataclass
class PlannedRun:
    """One unit of fan-out: a single (team, skill) pair the coordinator will trigger."""

    team_id: int
    skill_name: str


@dataclass
class FetchEnabledRunsInput:
    """No fields today; placeholder for future filters (team allowlist, dry-run flags)."""

    pass


@dataclass
class FetchEnabledRunsOutput:
    planned_runs: list[PlannedRun]


@dataclass
class StampDispatchedRunsInput:
    """The (team, skill) runs whose child workflow was dispatched this tick."""

    dispatched_runs: list[PlannedRun]


@dataclass
class CoordinatorWorkflowInput:
    """Placeholder input for forward-compat (e.g. future dry-run / debug flags)."""

    pass


@dataclass
class CoordinatorWorkflowOutput:
    planned_count: int
    started_count: int
    skipped_count: int


@activity.defn
async def fetch_enabled_signals_scout_runs_activity(
    _input: FetchEnabledRunsInput,
) -> FetchEnabledRunsOutput:
    """Resolve the set of (team, skill) runs to dispatch this tick.

    Scans dogfood teams (gated by the `signals-scout` flag), auto-registers a config row
    for any `signals-scout-*` skill missing one, and dispatches each enabled scout whose
    schedule is due — most-overdue first, capped at MAX_RUNS_PER_TICK.
    """
    async with Heartbeater():
        # Read the flag payload once, off the DB thread pool — the SDK call can block on a cold
        # cache, and database_sync_to_async's pool is sized for DB-bound work (mirrors the
        # asyncio.to_thread split in ai_observability/team_discovery.py). Enrollment and per-team
        # configs are derived from the same snapshot so they can't disagree across two reads.
        payload = await asyncio.to_thread(_read_flag_payload)
        enrolled_team_ids = _enrolled_team_ids(payload)
        team_configs = _team_configs(payload)
        planned = await database_sync_to_async(_collect_planned_runs, thread_sensitive=False)(
            enrolled_team_ids, team_configs
        )
    logger.info("signals_scout coordinator: planned runs", count=len(planned))
    return FetchEnabledRunsOutput(planned_runs=planned)


@activity.defn
async def stamp_dispatched_signals_scout_runs_activity(
    stamp_input: StampDispatchedRunsInput,
) -> None:
    """Advance `last_run_at` for the configs whose child workflow was dispatched this tick.

    Split out of planning so the schedule only advances for scouts a child was actually
    launched for: if fan-out fails (or the coordinator dies) before dispatch, the config
    stays unstamped and re-dispatches next tick instead of being silently suppressed for a
    full interval. The trade is a rare double-run if this stamp fails after children started
    — far less harmful than a day of suppression, and bounded by the activity retry policy.
    """
    async with Heartbeater():
        await database_sync_to_async(_stamp_dispatched_runs, thread_sensitive=False)(stamp_input.dispatched_runs)


def _stamp_dispatched_runs(dispatched_runs: list[PlannedRun]) -> None:
    """Sync bulk stamp. `.update()` bypasses save(), so this per-tick write never hits the
    activity log."""
    if not dispatched_runs:
        return
    now = timezone.now()
    predicate = Q()
    for run in dispatched_runs:
        predicate |= Q(team_id=run.team_id, skill_name=run.skill_name)
    SignalScoutConfig.all_teams.filter(predicate).update(last_run_at=now)


@dataclass
class _DueRun:
    overdue_s: float
    config_pk: str
    team_id: int
    skill_name: str


def _collect_planned_runs(enrolled_team_ids: set[int], team_configs: dict[int, dict] | None = None) -> list[PlannedRun]:
    """Sync DB scan. Runs in a worker thread via Django's per-thread connection mgmt.

    Takes the already-resolved enrolled team ids (and optional per-team config overrides) so
    the flag reads stay off this DB pool.
    """
    now = timezone.now()
    team_configs = _canonicalize_team_config_keys(team_configs or {})
    due: list[_DueRun] = []
    for team in _participating_teams(enrolled_team_ids):
        # Sync canonical scouts so a freshly-enrolled team has skills to register on.
        # `prune=True`: the periodic tick is a deliberate reconciliation path, so it also
        # tombstones rows whose canonical was removed from disk (the runner cold-start sync
        # leaves prune off). The sync also propagates updates to canonical content for any
        # harness-seeded row the team hasn't edited, so a merged SKILL.md change rolls out
        # within one coordinator tick. Idempotent; a failure here doesn't abort the tick.
        try:
            sync_canonical_skills(team, prune=True)
        except Exception:
            logger.exception(
                "signals_scout coordinator: canonical skill sync failed for team; continuing",
                team_id=team.id,
            )
        live_skills = register_missing_configs(team.id)
        # Skip enabled configs whose `signals-scout-*` skill was deleted or is no longer the
        # latest version: dispatching them would spawn a child workflow that fails fast in
        # load_skill_for_run on every tick.
        for config in SignalScoutConfig.all_teams.filter(team_id=team.id, enabled=True, skill_name__in=live_skills):
            overdue_s = _overdue_seconds(config, now)
            if overdue_s is None:
                continue
            due.append(_DueRun(overdue_s, str(config.pk), team.id, config.skill_name))

    if not due:
        return []

    selected = _allocate_tick_budget(due, team_configs)
    planned = [PlannedRun(team_id=d.team_id, skill_name=d.skill_name) for d in selected]
    # Stable order for predictable child-workflow ids within the tick.
    planned.sort(key=lambda p: (p.team_id, p.skill_name))
    return planned


def _allocate_tick_budget(due: list[_DueRun], team_configs: dict[int, dict] | None = None) -> list[_DueRun]:
    """Apply the per-team and global tick caps fairly. Deterministic — no sampling.

    Each team's due runs are ordered most-overdue-first and trimmed to its per-team cap — the
    `max_runs_per_tick` from its `team_configs` flag override if set, else
    `MAX_RUNS_PER_TEAM_PER_TICK`; the global `MAX_RUNS_PER_TICK` budget is then filled
    round-robin across teams (one run per team per round) so a single team with many due scouts
    can't monopolize the tick. Deferred runs stay unstamped, so they're the most overdue next
    tick — a poor-man's queue, same catch-up semantics as before.
    """
    team_configs = team_configs or {}

    def _team_cap(team_id: int) -> int:
        # Per-team override takes precedence; validate the value here (the config blob is
        # arbitrary flag JSON) and fall back to the global default if absent or invalid.
        override = (team_configs.get(team_id) or {}).get(TEAM_CONFIG_MAX_RUNS_PER_TICK)
        if isinstance(override, int) and not isinstance(override, bool) and override > 0:
            return override
        return MAX_RUNS_PER_TEAM_PER_TICK

    by_team: dict[int, list[_DueRun]] = {}
    for d in due:
        by_team.setdefault(d.team_id, []).append(d)
    for team_id, runs in by_team.items():
        runs.sort(key=lambda d: (-d.overdue_s, d.skill_name))
        cap = _team_cap(team_id)
        if len(runs) > cap:
            logger.warning(
                "signals_scout coordinator: team over per-tick cap, deferring overflow",
                team_id=team_id,
                due=len(runs),
                cap=cap,
            )
            del runs[cap:]

    # Count after per-team trimming — that's the real candidate pool the global cap defers
    # against, so the warning doesn't fire on runs already dropped by the per-team caps.
    total_after_team_caps = sum(len(runs) for runs in by_team.values())
    if total_after_team_caps > MAX_RUNS_PER_TICK:
        logger.warning(
            "signals_scout coordinator: more due than cap, deferring overflow",
            due=total_after_team_caps,
            cap=MAX_RUNS_PER_TICK,
        )

    # Most-overdue team first, team id as the deterministic tiebreak.
    team_order = sorted(by_team, key=lambda t: (-by_team[t][0].overdue_s, t))
    selected: list[_DueRun] = []
    # Lists are already trimmed to each team's cap, so the longest list is exactly the number
    # of rounds needed — this naturally covers a team with a raised override too.
    max_rounds = max((len(runs) for runs in by_team.values()), default=0)
    for round_idx in range(max_rounds):
        if len(selected) >= MAX_RUNS_PER_TICK:
            break
        for team_id in team_order:
            runs = by_team[team_id]
            if round_idx >= len(runs):
                continue
            selected.append(runs[round_idx])
            if len(selected) >= MAX_RUNS_PER_TICK:
                break
    return selected


def _participating_teams(enrolled: set[int]) -> list[Team]:
    """Resolve enrolled team ids to canonical `Team`s to run scouts on.

    Enrollment is flag-driven: a team runs scouts iff its id is in the `signals-scout` flag
    payload allowlist (resolved by `_enrolled_team_ids`, passed in). Adding an id in the flag
    UI enrolls the team on the next tick with no manual seed — the tick body seeds canonical
    skills + registers configs for it; removing it (or listing it in `skip_team_ids`) drains
    it the next tick. Child envs canonicalize to their parent project so the per-project
    singleton config is found once.
    """
    if not enrolled:
        return []
    candidates = Team.objects.filter(id__in=enrolled)
    canonical_ids = {team.parent_team_id or team.id for team in candidates}
    return list(Team.objects.filter(id__in=canonical_ids).order_by("id"))


def _canonicalize_team_config_keys(team_configs: dict[int, dict]) -> dict[int, dict]:
    """Remap child-env config keys to their parent project id so per-team overrides line up with
    the canonical team ids planning uses — `_participating_teams` canonicalizes enrollment the
    same way, so an operator listing a child env id in both `guaranteed_team_ids` and
    `team_configs` keeps its override. If both a parent and one of its child envs are keyed, the
    explicit parent-keyed config wins regardless of dict order."""
    if not team_configs:
        return team_configs
    parent_of = {
        team_id: (parent_id or team_id)
        for team_id, parent_id in Team.objects.filter(id__in=team_configs.keys()).values_list("id", "parent_team_id")
    }
    canonical: dict[int, dict] = {}
    for team_id, config in team_configs.items():
        canonical_id = parent_of.get(team_id, team_id)
        # A parent/standalone key (team_id == canonical_id) always wins; a child remap only
        # fills in when no parent-keyed config is present for that project.
        if team_id == canonical_id or canonical_id not in canonical:
            canonical[canonical_id] = config
    return canonical


def _fallback_team_ids() -> list[int]:
    """Default allowlist when the flag payload is absent/unreadable — gated to PostHog Cloud
    and local dev. A self-hosted instance (where teams 1/2 exist but no one opted into scouts)
    fails closed instead, so the coordinator never starts LLM scout runs for an unintended
    tenant; a self-hoster opts in by setting the payload explicitly."""
    return list(DEFAULT_ENROLLED_TEAM_IDS) if (is_cloud() or settings.DEBUG) else []


def _read_flag_payload() -> dict | None:
    """Read + parse the `signals-scout` flag's JSON payload once.

    The flag must stay 100%-on so the payload is served for the synthetic discovery
    distinct_id — `match_value=True` additionally forces the true-variant payload under local
    evaluation. Returns the parsed dict, or `None` when the payload is absent / not an object /
    unreadable. A read error never breaks dispatch: callers apply their own fallback to `None`.
    Enrollment and per-team configs both derive from a single call to this so they always see
    the same snapshot. Mirrors `posthog/temporal/ai_observability/team_discovery.py`.
    """
    try:
        payload = posthoganalytics.get_feature_flag_payload(
            SIGNALS_SCOUT_DOGFOOD_FLAG, SIGNALS_SCOUT_DISCOVERY_DISTINCT_ID, match_value=True
        )
        if isinstance(payload, str):
            payload = json.loads(payload)
        return payload if isinstance(payload, dict) else None
    except Exception as error:
        capture_exception(error)
        return None


def _enrolled_team_ids(payload: dict | None) -> set[int]:
    """Project ids enrolled in scouts, parsed from the `signals-scout` flag payload.

    Flag-driven enrollment, no deploy: edit `guaranteed_team_ids` in the flag UI to enroll (or
    drain) a team on the next tick; `skip_team_ids` is an override kill-switch.
    Fail-safe: a missing/invalid payload (`None`) or malformed value falls back to
    `_fallback_team_ids`.
    """
    fallback = _fallback_team_ids()
    if payload is None:
        return set(fallback)

    # Absent key or malformed value → fallback. An explicit empty list is honored as an
    # intentional "drain all teams" — not coerced to the fallback.
    guaranteed = payload.get("guaranteed_team_ids", fallback)
    if not isinstance(guaranteed, list) or not all(isinstance(t, int) for t in guaranteed):
        guaranteed = fallback

    skip = payload.get("skip_team_ids", [])
    if not isinstance(skip, list) or not all(isinstance(t, int) for t in skip):
        skip = []

    return set(guaranteed) - set(skip)


def _team_configs(payload: dict | None) -> dict[int, dict]:
    """Optional per-team config overrides, parsed from the same `signals-scout` flag payload as
    enrollment. Returns `{team_id: config_dict}`.

    Payload key `team_configs` is a `{team_id: {…}}` map — a forward-looking per-team override
    bag. Today the only honored key is `max_runs_per_tick` (overrides `MAX_RUNS_PER_TEAM_PER_TICK`
    for that team — give an important dogfooder more headroom or hold a noisy one lower, no
    deploy); add more per-team settings under the same blob later. The override takes precedence
    over the global default for its team; teams not listed keep the global default.

    Absent/malformed (`None` payload included) → `{}` (everyone on the defaults). Defensive
    parse: JSON object keys arrive as strings so they're coerced to int; entries whose value
    isn't a dict are dropped. Each consumer validates the specific key it reads (see
    `_allocate_tick_budget._team_cap`). Keys are canonicalized to parent projects at planning
    time (see `_canonicalize_team_config_keys`).
    """
    if payload is None:
        return {}

    raw = payload.get("team_configs", {})
    if not isinstance(raw, dict):
        return {}

    configs: dict[int, dict] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        try:
            team_id = int(key)
        except (TypeError, ValueError):
            continue
        configs[team_id] = value
    return configs


def _overdue_seconds(config: SignalScoutConfig, now: datetime) -> float | None:
    """Seconds past due (down to `-DUE_GRACE_SECONDS`), or None if not yet due. Never-run rows are maximally overdue."""
    if config.last_run_at is None:
        return float("inf")
    overdue = (now - config.last_run_at).total_seconds() - config.run_interval_minutes * 60
    return overdue if overdue >= -DUE_GRACE_SECONDS else None


@workflow.defn(name="run-signals-scout-coordinator")
class SignalsScoutCoordinatorWorkflow:
    """Coordinator: scans dogfood teams, fans out per-(team, skill) child runs for due scouts.

    Dispatch is fire-and-forget: each child is started with `ParentClosePolicy.ABANDON`
    so it outlives this workflow, and the coordinator returns right after the last
    `start_child_workflow` call plus one fast bookkeeping activity that advances
    `last_run_at` for the children it dispatched. This keeps the coordinator's lifetime to
    seconds regardless of how many children are dispatched, so the schedule's `SKIP` overlap
    policy never collapses ticks at scale. Temporal's task queue + worker concurrency
    handles the throttling — if workers are saturated, the children just queue.

    The schedule advances only after dispatch (not during planning) so a fan-out failure
    re-dispatches next tick rather than silently suppressing a scout for a full interval.

    Idempotency: child workflow IDs are deterministic per `(team_id, skill_name, tick_id)`,
    so a retried coordinator can't double-launch within a single tick. A separate
    skip-if-running guard inside the runner protects against tick-over-tick collisions.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> CoordinatorWorkflowInput:
        if not inputs:
            return CoordinatorWorkflowInput()
        loaded = json.loads(inputs[0])
        return CoordinatorWorkflowInput(**loaded)

    @workflow.run
    async def run(self, _input: CoordinatorWorkflowInput) -> CoordinatorWorkflowOutput:
        fetch_result = await workflow.execute_activity(
            fetch_enabled_signals_scout_runs_activity,
            FetchEnabledRunsInput(),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        planned_runs = fetch_result.planned_runs
        if not planned_runs:
            return CoordinatorWorkflowOutput(0, 0, 0)

        # `workflow_id` (not `run_id`) is the correct per-tick key. Temporal appends the
        # scheduled time to a schedule-started workflow's id, so each tick gets a
        # distinct `workflow_id` (`signals-scout-coordinator-schedule-<scheduled-time>`) —
        # unique across ticks, which is what lets a later tick relaunch the same (team, skill).
        # It's also stable across a coordinator retry/replay within the same tick (only
        # `run_id` changes on retry), so the deterministic child ids below + REJECT_DUPLICATE
        # dedupe a retry without re-launching. `run_id` would break that: a retry would mint
        # new child ids and double-launch.
        tick_id = workflow.info().workflow_id
        started = 0
        skipped = 0
        dispatched: list[PlannedRun] = []
        for idx, planned in enumerate(planned_runs):
            if await _start_child(planned=planned, tick_id=tick_id, idx=idx):
                started += 1
            else:
                skipped += 1
            # Both branches mean a child for this (team, skill, tick) now exists (started, or
            # dedupe-skipped because a retry already started it) — so its schedule should
            # advance. A hard `start_child` error raises out of `_start_child` before reaching
            # here, leaving that config unstamped to re-dispatch next tick.
            dispatched.append(planned)

        # Stamp only after dispatch, so a fan-out failure can't suppress a scout for a day.
        await workflow.execute_activity(
            stamp_dispatched_signals_scout_runs_activity,
            StampDispatchedRunsInput(dispatched_runs=dispatched),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )
        return CoordinatorWorkflowOutput(
            planned_count=len(planned_runs),
            started_count=started,
            skipped_count=skipped,
        )


async def _start_child(*, planned: PlannedRun, tick_id: str, idx: int) -> bool:
    """Fire-and-forget child dispatch. Returns True if started, False if dedupe-skipped.

    `REJECT_DUPLICATE` makes a re-dispatch of an already-started child for the same
    deterministic `(team, skill, tick, idx)` id raise `WorkflowAlreadyStartedError`
    whether that prior child is still running OR already closed — so a coordinator
    retry/replay within the same tick skips it instead of re-running it (`ALLOW_DUPLICATE`
    would re-launch a child that finished before the retry, double-running that team for
    the tick). Any other exception bubbles up: the coordinator's `RetryPolicy` re-dispatches
    idempotently because workflow IDs are deterministic.
    """
    child_id = _child_workflow_id(planned, tick_id, idx)
    try:
        await workflow.start_child_workflow(
            RunSignalsScoutWorkflow.run,
            RunSignalsScoutInput(
                team_id=planned.team_id,
                skill_name=planned.skill_name,
            ),
            id=child_id,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            parent_close_policy=workflow.ParentClosePolicy.ABANDON,
        )
        return True
    except WorkflowAlreadyStartedError:
        workflow.logger.info(
            "signals_scout coordinator: child already running, skipping",
            team_id=planned.team_id,
            skill_name=planned.skill_name,
            child_id=child_id,
        )
        return False


def _child_workflow_id(planned: PlannedRun, tick_id: str, idx: int) -> str:
    # Tick_id makes the ID unique across coordinator runs; idx disambiguates if a team
    # somehow ends up with the same skill twice in a tick (defense-in-depth — the
    # planning step already dedupes via sorted unique).
    safe_skill = planned.skill_name.replace(" ", "_")[:60]
    return f"signals-scout-run-{planned.team_id}-{safe_skill}-{tick_id}-{idx}"
