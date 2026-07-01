from __future__ import annotations

import json
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db.models import Q
from django.utils import timezone

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.config_registry import live_scout_skill_names, register_missing_configs
from products.signals.backend.scout_harness.lazy_seed import sync_canonical_skills

# Per-team cap resolution + the flag-payload read live in the temporalio-free `team_limits` module
# so the HTTP metadata surface can share them. Imported by name so the planning code below calls
# them unqualified and tests can patch them on this module.
from products.signals.backend.scout_harness.team_limits import (
    DAILY_BUDGET_WINDOW,
    Enrollment,
    _canonicalize_team_config_keys,
    _default_team_config,
    _parse_enrollment,
    _read_flag_payload,
    _resolve_global_max_runs_per_tick,
    _resolve_max_runs_per_day,
    _resolve_max_runs_per_tick,
    _resolve_withheld_skills,
    _runs_today_by_team,
    _team_configs,
)
from products.signals.backend.temporal.agentic.scout_scheduler import RunSignalsScoutInput, RunSignalsScoutWorkflow

logger = structlog.get_logger(__name__)

# Hard cap on dispatches per tick. The cost bound: when more scouts are due than this,
# we run the most-overdue first and the rest catch up next tick (a poor-man's queue).
# Set generously for now while scouts roll out to more teams — the per-team tick cap and
# round-robin allocation do the day-to-day fairness work; this is the global ceiling.
MAX_RUNS_PER_TICK = 1000

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
        enrollment = _parse_enrollment(payload)
        team_configs = _team_configs(payload)
        default_team_config = _default_team_config(payload)
        # The global per-tick ceiling is flag-tunable (no deploy): resolve it here off the same
        # snapshot, falling back to the code constant. `MAX_RUNS_PER_TICK` is read at call time so
        # tests patching the module global still take effect.
        global_max_runs_per_tick = _resolve_global_max_runs_per_tick(payload, MAX_RUNS_PER_TICK)
        planned = await database_sync_to_async(_collect_planned_runs, thread_sensitive=False)(
            enrollment, team_configs, default_team_config, global_max_runs_per_tick
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


def _collect_planned_runs(
    enrollment: Enrollment,
    team_configs: dict[int, dict] | None = None,
    default_team_config: dict | None = None,
    max_runs_per_tick: int | None = None,
) -> list[PlannedRun]:
    """Sync DB scan. Runs in a worker thread via Django's per-thread connection mgmt.

    Takes the parsed enrollment (explicit allowlist + the `"*"` wildcard), the optional per-team
    config overrides, the fleet-wide default config, and the resolved global per-tick ceiling — so
    the flag reads all stay off this DB pool.
    """
    now = timezone.now()
    team_configs = _canonicalize_team_config_keys(team_configs or {})
    default_team_config = default_team_config or {}
    due: list[_DueRun] = []
    for team, needs_seed in _participating_teams(enrollment):
        # Scouts held back from this team via the `withheld_skills` denylist (resolved most-
        # specific-first from this team's `team_configs` entry, then the fleet `default_team_config`):
        # skip seeding the skill, skip seeding/enabling a config, and skip dispatch.
        withheld_for_team = _resolve_withheld_skills(team.id, team_configs, default_team_config)
        if needs_seed:
            # Explicitly enrolled (a pinned / force-provisioned id): seed from nothing. The periodic
            # tick is the reconciliation path. `sync_canonical_skills(prune=True)` tombstones rows
            # whose canonical was removed from disk and propagates merged SKILL.md updates to
            # harness-seeded rows the team hasn't edited, so a content change rolls out within one
            # tick. Idempotent; a failure here doesn't abort the tick.
            try:
                sync_canonical_skills(team, prune=True, withheld_skill_names=withheld_for_team)
            except Exception:
                logger.exception(
                    "signals_scout coordinator: canonical skill sync failed for team; continuing",
                    team_id=team.id,
                )
            # This team's seed posture resolves like the tick cap: its own `team_configs` override
            # layered over the fleet-wide `default_team_config`, most-specific first. Passing the
            # layers (not a shallow merge) lets `_resolve_seed_posture` fall back per key, so a
            # malformed per-team value doesn't clobber a valid fleet default.
            seed_config_layers = [team_configs.get(team.id) or {}, default_team_config]
            # `register_missing_configs` drops withheld skills from its return, so they're already
            # excluded from `live_skills` (and thus from dispatch below) as well as from seeding.
            live_skills = register_missing_configs(team.id, seed_config_layers, withheld_skill_names=withheld_for_team)
        else:
            # Wildcard-discovered (`"*"`): the team already self-seeded its configs through the
            # product-autonomy-gated UI / `sync` materialization, so skip the per-tick seed +
            # reconcile — that's what keeps the hot path cheap as self-enrollment scales to thousands
            # of teams. Read only the live scout skill names (cheap) so a config whose skill was
            # deleted/superseded isn't dispatched, and honor the holdback denylist. Central canonical
            # SKILL.md updates still reach these teams: the runner cold-starts with its own
            # `sync_canonical_skills` before loading the skill (runner.py), so a merged change lands
            # on the scout's NEXT RUN for any harness-seeded row the team hasn't forked. What the
            # per-tick skip drops is only the eager refresh on ticks where nothing dispatches, plus
            # the `prune=True` tombstoning of disk-deleted canonicals and first-appearance of
            # brand-new canonical scouts as rows — both rare, and both catch up on the team's next
            # `sync` (follow-up if needed: a slow fleet-wide prune/seed sweep off the dispatch path).
            live_skills = live_scout_skill_names(team.id, withheld_skill_names=withheld_for_team)
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

    # Only count runs for teams that actually have a resolved daily budget — for the default
    # rollout (no `max_runs_per_day` set anywhere) this skips the aggregate query entirely.
    capped_team_ids = {
        d.team_id for d in due if _resolve_max_runs_per_day(d.team_id, team_configs, default_team_config) is not None
    }
    runs_today = _runs_today_by_team(capped_team_ids, now - DAILY_BUDGET_WINDOW)
    selected = _allocate_tick_budget(due, team_configs, default_team_config, runs_today, max_runs_per_tick)
    planned = [PlannedRun(team_id=d.team_id, skill_name=d.skill_name) for d in selected]
    # Stable order for predictable child-workflow ids within the tick.
    planned.sort(key=lambda p: (p.team_id, p.skill_name))
    return planned


def _allocate_tick_budget(
    due: list[_DueRun],
    team_configs: dict[int, dict] | None = None,
    default_team_config: dict | None = None,
    runs_today: dict[int, int] | None = None,
    max_runs_per_tick: int | None = None,
) -> list[_DueRun]:
    """Apply the per-team and global tick caps fairly. Deterministic — no sampling.

    Each team's due runs are ordered most-overdue-first and trimmed to its effective per-team
    cap, then the global budget is filled round-robin across teams (one run per team per round) so
    a single team with many due scouts can't monopolize the tick. Deferred runs stay unstamped, so
    they're the most overdue next tick — a poor-man's queue, same catch-up semantics as before.

    The global budget is `max_runs_per_tick` (the flag-resolved ceiling the activity passes in),
    falling back to the `MAX_RUNS_PER_TICK` code constant for direct callers that don't supply one.

    The effective per-team cap is the tighter of two bounds: the per-tick cap
    (`_resolve_max_runs_per_tick`) and the day's remaining headroom under the per-team daily
    budget (`_resolve_max_runs_per_day` minus `runs_today`). The daily budget is what bounds a
    team to N runs/day regardless of how many scouts it enables or how short their intervals —
    the per-tick cap alone can only bound bursts (≤ cap × ticks/day).
    """
    team_configs = team_configs or {}
    default_team_config = default_team_config or {}
    runs_today = runs_today or {}
    global_cap = max_runs_per_tick if max_runs_per_tick is not None else MAX_RUNS_PER_TICK

    def _team_cap(team_id: int) -> int:
        per_tick = _resolve_max_runs_per_tick(team_id, team_configs, default_team_config)
        per_day = _resolve_max_runs_per_day(team_id, team_configs, default_team_config)
        if per_day is None:
            return per_tick
        # Day's remaining headroom caps this tick too: a team that's spent its daily budget gets
        # 0 this tick, no matter how many scouts are due. Counted runs exclude this tick's
        # not-yet-started dispatches; the per-tick cap bounds that brief window.
        remaining_today = max(0, per_day - runs_today.get(team_id, 0))
        return min(per_tick, remaining_today)

    by_team: dict[int, list[_DueRun]] = {}
    for d in due:
        by_team.setdefault(d.team_id, []).append(d)
    for team_id, runs in by_team.items():
        runs.sort(key=lambda d: (-d.overdue_s, d.skill_name))
        cap = _team_cap(team_id)
        if len(runs) > cap:
            if cap == 0:
                # The expected steady state once a team has spent its daily budget — info, not a
                # warning, so it doesn't read as a misconfiguration in alerting (it would otherwise
                # fire every tick for the rest of the 24h window).
                logger.info(
                    "signals_scout coordinator: team daily budget spent, deferring all due scouts",
                    team_id=team_id,
                    deferred=len(runs),
                )
            else:
                logger.warning(
                    "signals_scout coordinator: team over effective per-team cap, deferring overflow",
                    team_id=team_id,
                    due=len(runs),
                    cap=cap,
                )
            del runs[cap:]

    # Drop teams trimmed to zero (e.g. daily budget spent) so the round-robin's most-overdue-team
    # sort never indexes into an empty list.
    by_team = {team_id: runs for team_id, runs in by_team.items() if runs}

    # Count after per-team trimming — that's the real candidate pool the global cap defers
    # against, so the warning doesn't fire on runs already dropped by the per-team caps.
    total_after_team_caps = sum(len(runs) for runs in by_team.values())
    if total_after_team_caps > global_cap:
        logger.warning(
            "signals_scout coordinator: more due than cap, deferring overflow",
            due=total_after_team_caps,
            cap=global_cap,
        )

    # Most-overdue team first, team id as the deterministic tiebreak.
    team_order = sorted(by_team, key=lambda t: (-by_team[t][0].overdue_s, t))
    selected: list[_DueRun] = []
    # Lists are already trimmed to each team's cap, so the longest list is exactly the number
    # of rounds needed — this naturally covers a team with a raised override too.
    max_rounds = max((len(runs) for runs in by_team.values()), default=0)
    for round_idx in range(max_rounds):
        if len(selected) >= global_cap:
            break
        for team_id in team_order:
            runs = by_team[team_id]
            if round_idx >= len(runs):
                continue
            selected.append(runs[round_idx])
            if len(selected) >= global_cap:
                break
    return selected


def _canonicalize_team_ids(ids: set[int]) -> set[int]:
    """Map team ids to their canonical parent project id (child env → parent), dropping ids with no
    `Team` row. Mirrors `_canonicalize_team_config_keys` / `_is_team_enrolled` so enrollment,
    configs, and dispatch all key on the same project id."""
    if not ids:
        return set()
    return {
        (parent_id or team_id)
        for team_id, parent_id in Team.objects.filter(id__in=ids).values_list("id", "parent_team_id")
    }


def _participating_teams(enrollment: Enrollment) -> list[tuple[Team, bool]]:
    """Resolve enrollment to canonical `Team`s to run scouts on, each tagged `needs_seed`.

    Two ways a team participates:
    - explicit `guaranteed_team_ids` (skip removed) → force-provisioned: `needs_seed=True`, so the
      tick seeds canonical skills + registers configs from nothing (the pinned internal projects).
      Adding an id in the flag UI enrolls it on the next tick with no manual seed; removing it (or
      listing it in `skip_team_ids`) drains it.
    - the `"*"` wildcard → every team that already has an enabled `SignalScoutConfig`
      (`needs_seed=False`): it self-enrolled through the product-autonomy-gated UI, so it already
      has configs and the tick skips the expensive seed/reconcile for it. If a team is in both, the
      explicit tag wins (it gets the seed pass).
    Child envs canonicalize to their parent project; `skip_team_ids` is removed from both sets.
    Skip is subtracted AFTER canonicalizing both sides, so listing a child env in `guaranteed_team_ids`
    and its parent project in `skip_team_ids` (or the reverse) still hard-excludes the project — the
    raw ids differ but their canonical parent matches.
    """
    skip_canonical = _canonicalize_team_ids(enrollment.skip)
    explicit = _canonicalize_team_ids(enrollment.explicit) - skip_canonical

    wildcard_ids: set[int] = set()
    if enrollment.wildcard:
        # Config rows persist under the canonical parent team, so these ids are already canonical.
        wildcard_ids = set(
            SignalScoutConfig.all_teams.filter(enabled=True).values_list("team_id", flat=True).distinct()
        )
    wildcard_ids -= skip_canonical
    wildcard_ids -= explicit  # explicit wins the tag — it gets the seed pass below

    all_ids = explicit | wildcard_ids
    if not all_ids:
        return []
    teams = {team.id: team for team in Team.objects.filter(id__in=all_ids)}
    return [(teams[team_id], team_id in explicit) for team_id in sorted(all_ids) if team_id in teams]


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
