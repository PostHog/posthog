from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import timedelta

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater

from products.llm_analytics.backend.models.skills import LLMSkill
from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.lazy_seed import seed_canonical_skills
from products.signals.backend.scout_harness.skill_loader import SIGNALS_SCOUT_SKILL_PREFIX
from products.signals.backend.temporal.agentic.scout_scheduler import RunSignalsScoutInput, RunSignalsScoutWorkflow

logger = structlog.get_logger(__name__)

# Hard cap on planned runs per coordinator tick. Defends against a config explosion
# (e.g. someone seeds 50 skills) overwhelming the worker pool. If we exceed this we
# truncate after sorting; the next tick picks up where we left off because the runner
# is idempotent on (team, skill).
MAX_RUNS_PER_TICK = 50

# Default schedule cadence. v1 spec: "stagger schedule, ~1 run per agent per hour".
COORDINATOR_INTERVAL_MINUTES = 60


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
    """Resolve the set of (team, skill) runs to trigger this tick.

    Reads enabled `SignalScoutConfig` rows; for each one, expands to the configured
    skill list, falling back to a glob over the team's `signals-scout-*` skills when
    `enabled_skill_names` is null. Skips configs where the resulting skill list is empty.
    """
    async with Heartbeater():
        planned = await database_sync_to_async(_collect_planned_runs, thread_sensitive=False)()
    logger.info("signals_scout coordinator: planned runs", count=len(planned))
    return FetchEnabledRunsOutput(planned_runs=planned)


def _collect_planned_runs() -> list[PlannedRun]:
    """Sync DB scan. Runs in a worker thread via Django's per-thread connection mgmt."""
    # TODO(phase 4): gate behind the `signals-scout-dogfood` feature flag once it
    # exists. For now the `enabled=False` default on `SignalScoutConfig` is the gate.
    # `.unscoped()` is intentional: the coordinator scans every team's config to plan
    # cross-team runs. The default `.objects` manager is fail-closed (TeamScopedRootMixin)
    # and would raise without an active team_scope — but this is the one caller for
    # which "every team" is the correct answer, not a footgun.
    configs = list(
        SignalScoutConfig.objects.unscoped().filter(enabled=True).select_related("team").order_by("team__id")
    )
    planned: list[PlannedRun] = []
    for config in configs:
        team = config.team
        team_id = team.id
        # Lazy-seed canonical signals-scout-* skills before we resolve the skill list.
        # Without this, a brand-new team with `enabled_skill_names=None` and zero
        # LLMSkill rows would produce an empty planned set, no child runs would fan
        # out, and the runner-level lazy seed would never be reached — the cadence
        # path would silently never start. No-op when the team already has any
        # signals-scout-* row. Failures don't abort the tick: log and continue.
        try:
            seed_canonical_skills(team)
        except Exception:
            logger.exception(
                "signals_scout coordinator: lazy seed failed for team; continuing",
                team_id=team_id,
            )
        skill_names = _resolve_skill_names_for_config(config, team_id=team_id)
        for skill_name in skill_names:
            planned.append(
                PlannedRun(
                    team_id=team_id,
                    skill_name=skill_name,
                )
            )
    if len(planned) > MAX_RUNS_PER_TICK:
        logger.warning(
            "signals_scout coordinator: sampling planned runs down to hard cap",
            planned=len(planned),
            cap=MAX_RUNS_PER_TICK,
        )
        # Randomly sample which runs make the cap rather than slicing a sorted prefix —
        # a deterministic cut by (team_id, skill_name) permanently starves the highest
        # team_ids whenever the plan exceeds the cap. This runs in an activity (not the
        # workflow), so non-deterministic sampling is allowed; per-tick child workflow ids
        # stay unique via tick_id regardless of order.
        planned = random.sample(planned, MAX_RUNS_PER_TICK)
    # Stable order (team_id, skill_name) for a predictable dispatch order + child-id idx
    # within the tick. Applied after sampling so the cap is a fair random subset.
    planned.sort(key=lambda p: (p.team_id, p.skill_name))
    return planned


def _resolve_skill_names_for_config(config: SignalScoutConfig, *, team_id: int) -> list[str]:
    """Return the ordered list of skill names to run for this team's config.

    `enabled_skill_names = None` → glob all `signals-scout-*` skills on the team.
    `enabled_skill_names = [list]` → use the list verbatim, but still validate each
    name actually exists on the team so the activity output is grounded in reality.
    Duplicates in the configured list are collapsed (preserving first-seen order) so
    a noisy config row can't fan out the same skill twice in one tick.
    """
    available = set(
        LLMSkill.objects.filter(
            team_id=team_id,
            name__startswith=SIGNALS_SCOUT_SKILL_PREFIX,
            is_latest=True,
            deleted=False,
        ).values_list("name", flat=True)
    )
    if config.enabled_skill_names is None:
        return sorted(available)
    requested = list(dict.fromkeys(config.enabled_skill_names))
    resolved = [name for name in requested if name in available]
    missing = [name for name in requested if name not in available]
    if missing:
        logger.warning(
            "signals_scout coordinator: configured skill names not found on team",
            team_id=team_id,
            missing=missing,
        )
    return resolved


@workflow.defn(name="run-signals-scout-coordinator")
class SignalsScoutCoordinatorWorkflow:
    """Hourly coordinator: scans enabled configs, fans out per-(team, skill) child runs.

    Dispatch is fire-and-forget: each child is started with `ParentClosePolicy.ABANDON`
    so it outlives this workflow, and the coordinator returns immediately after the
    last `start_child_workflow` call. This keeps the coordinator's lifetime to seconds
    regardless of how many children are dispatched, so the schedule's `SKIP` overlap
    policy never collapses ticks at scale. Temporal's task queue + worker concurrency
    handles the throttling — if workers are saturated, the children just queue.

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
        # scheduled time to a schedule-started workflow's id, so each hourly tick gets a
        # distinct `workflow_id` (`signals-scout-coordinator-schedule-<scheduled-time>`) —
        # unique across ticks, which is what lets a later tick relaunch the same (team, skill).
        # It's also stable across a coordinator retry/replay within the same tick (only
        # `run_id` changes on retry), so the deterministic child ids below + REJECT_DUPLICATE
        # dedupe a retry without re-launching. `run_id` would break that: a retry would mint
        # new child ids and double-launch.
        tick_id = workflow.info().workflow_id
        started = 0
        skipped = 0
        for idx, planned in enumerate(planned_runs):
            if await _start_child(planned=planned, tick_id=tick_id, idx=idx):
                started += 1
            else:
                skipped += 1
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
