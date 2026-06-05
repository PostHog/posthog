from __future__ import annotations

import json
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db.models import Q
from django.utils import timezone

import structlog
import posthoganalytics
from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater

from products.ai_observability.backend.models.skills import LLMSkill
from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.lazy_seed import sync_canonical_skills
from products.signals.backend.scout_harness.skill_loader import SIGNALS_SCOUT_SKILL_PREFIX
from products.signals.backend.temporal.agentic.scout_scheduler import RunSignalsScoutInput, RunSignalsScoutWorkflow

logger = structlog.get_logger(__name__)

# Team-level dogfood gate. The single team gate (no per-team model boolean): the flag's JSON
# payload picks which teams run scouts; per-scout SignalScoutConfig rows pick which
# scouts/schedules.
SIGNALS_SCOUT_DOGFOOD_FLAG = "signals-scout"

# Fixed distinct_id for the payload read — enrollment is team-list-in-payload, not per-user.
SIGNALS_SCOUT_DISCOVERY_DISTINCT_ID = "internal_signals_scout_team_discovery"

# Fail-safe allowlist used when the flag payload is missing or invalid, so a botched payload
# can never silently drop every team: 1 (local dev), 2 (internal), 148051 (dev project).
DEFAULT_ENROLLED_TEAM_IDS: list[int] = [1, 2, 148051]

# Hard cap on dispatches per tick. The cost bound: when more scouts are due than this,
# we run the most-overdue first and the rest catch up next tick (a poor-man's queue).
MAX_RUNS_PER_TICK = 50

# Coordinator tick cadence. Per-scout schedules are enforced via the due-check, so this is
# just the polling granularity — the floor on how often any scout can run.
COORDINATOR_INTERVAL_MINUTES = 15


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
        # Read the flag payload off the DB thread pool — the SDK call can block on a cold
        # cache, and database_sync_to_async's pool is sized for DB-bound work (mirrors the
        # asyncio.to_thread split in ai_observability/team_discovery.py).
        enrolled_team_ids = await asyncio.to_thread(_enrolled_team_ids)
        planned = await database_sync_to_async(_collect_planned_runs, thread_sensitive=False)(enrolled_team_ids)
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


def _collect_planned_runs(enrolled_team_ids: set[int]) -> list[PlannedRun]:
    """Sync DB scan. Runs in a worker thread via Django's per-thread connection mgmt.

    Takes the already-resolved enrolled team ids so the flag read stays off this DB pool.
    """
    now = timezone.now()
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
        live_skills = _register_missing_configs(team)
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

    # Cost bound: when more scouts are due than the cap, run the most-overdue first and let
    # the rest catch up next tick. Deterministic — no sampling.
    due.sort(key=lambda d: d.overdue_s, reverse=True)
    if len(due) > MAX_RUNS_PER_TICK:
        logger.warning(
            "signals_scout coordinator: more due than cap, deferring overflow",
            due=len(due),
            cap=MAX_RUNS_PER_TICK,
        )
        due = due[:MAX_RUNS_PER_TICK]

    planned = [PlannedRun(team_id=d.team_id, skill_name=d.skill_name) for d in due]
    # Stable order for predictable child-workflow ids within the tick.
    planned.sort(key=lambda p: (p.team_id, p.skill_name))
    return planned


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


def _enrolled_team_ids() -> set[int]:
    """Project ids enrolled in scouts, read from the `signals-scout` flag's JSON payload.

    Flag-driven enrollment, no deploy: edit `guaranteed_team_ids` in the flag UI to enroll (or
    drain) a team on the next tick; `skip_team_ids` is an override kill-switch. `match_value=True`
    asks for the flag's true-variant payload, so the team list lives in the payload rather than
    the release conditions. Fail-safe: a missing/invalid payload or a read error falls back to
    `DEFAULT_ENROLLED_TEAM_IDS`. Mirrors `posthog/temporal/ai_observability/team_discovery.py`.
    """
    try:
        payload = posthoganalytics.get_feature_flag_payload(
            SIGNALS_SCOUT_DOGFOOD_FLAG, SIGNALS_SCOUT_DISCOVERY_DISTINCT_ID, match_value=True
        )
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            return set(DEFAULT_ENROLLED_TEAM_IDS)

        # Absent key or malformed value → defaults (the fail-safe). An explicit empty list is
        # honored as an intentional "drain all teams" — not coerced to defaults.
        guaranteed = payload.get("guaranteed_team_ids", DEFAULT_ENROLLED_TEAM_IDS)
        if not isinstance(guaranteed, list) or not all(isinstance(t, int) for t in guaranteed):
            guaranteed = DEFAULT_ENROLLED_TEAM_IDS

        skip = payload.get("skip_team_ids", [])
        if not isinstance(skip, list) or not all(isinstance(t, int) for t in skip):
            skip = []

        return set(guaranteed) - set(skip)
    except Exception as error:
        capture_exception(error)
        return set(DEFAULT_ENROLLED_TEAM_IDS)


def _register_missing_configs(team: Team) -> set[str]:
    """Auto-create an enabled, default-schedule config for each scout skill lacking a row.

    The "author a skill, get a scout" path: a user-authored `signals-scout-foo` skill gets
    a row on the next tick with no further wiring. Returns the set of live `signals-scout-*`
    skill names for the team, so the caller can skip dispatching configs whose skill is gone.
    """
    skill_names = set(
        LLMSkill.objects.filter(
            team_id=team.id,
            name__startswith=SIGNALS_SCOUT_SKILL_PREFIX,
            is_latest=True,
            deleted=False,
        ).values_list("name", flat=True)
    )
    existing = set(SignalScoutConfig.all_teams.filter(team_id=team.id).values_list("skill_name", flat=True))
    for name in sorted(skill_names - existing):
        SignalScoutConfig.all_teams.get_or_create(team_id=team.id, skill_name=name)
    return skill_names


def _overdue_seconds(config: SignalScoutConfig, now: datetime) -> float | None:
    """Seconds past due, or None if not yet due. Never-run rows are maximally overdue."""
    if config.last_run_at is None:
        return float("inf")
    overdue = (now - config.last_run_at).total_seconds() - config.run_interval_minutes * 60
    return overdue if overdue >= 0 else None


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
