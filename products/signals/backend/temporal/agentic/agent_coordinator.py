from __future__ import annotations

import json
import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.heartbeat import Heartbeater

from products.llm_analytics.backend.models.skills import LLMSkill
from products.signals.backend.agent_harness.lazy_seed import seed_canonical_skills
from products.signals.backend.agent_harness.skill_loader import SIGNALS_AGENT_SKILL_PREFIX
from products.signals.backend.models import SignalAgentConfig
from products.signals.backend.temporal.agentic.agent_scheduler import (
    RunSignalsAgentInput,
    RunSignalsAgentOutput,
    RunSignalsAgentWorkflow,
)

logger = structlog.get_logger(__name__)

# Stagger between consecutive child launches inside one coordinator tick. With the hourly
# schedule and a 30-min runtime cap, ~12 min between starts gives space for one team's
# runs to mostly serialize via skip-if-running while letting different teams run in
# parallel. Tunable later from telemetry.
DEFAULT_STAGGER_MINUTES = 12

# Hard cap on planned runs per coordinator tick. Defends against a config explosion
# (e.g. someone seeds 50 skills) overwhelming the worker pool. If we exceed this we
# truncate after sorting; the next tick picks up where we left off because the runner
# is idempotent on (team, skill).
MAX_RUNS_PER_TICK = 50

# Default schedule cadence. v1 spec: "stagger schedule, ~1 run per agent per hour".
# TODO: revert to 60 before merge — temporarily 15 for chaos→agent dev iteration.
COORDINATOR_INTERVAL_MINUTES = 15


@dataclass
class PlannedRun:
    """One unit of fan-out: a single (team, skill) pair the coordinator will trigger."""

    team_id: int
    skill_name: str
    budget_overrides: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchEnabledRunsInput:
    """No fields today; placeholder for future filters (team allowlist, dry-run flags)."""

    pass


@dataclass
class FetchEnabledRunsOutput:
    planned_runs: list[PlannedRun]


@dataclass
class CoordinatorWorkflowInput:
    stagger_minutes: int = DEFAULT_STAGGER_MINUTES


@dataclass
class CoordinatorWorkflowOutput:
    planned_count: int
    triggered_count: int
    skipped_count: int
    failed_count: int


@activity.defn
async def fetch_enabled_signals_agent_runs_activity(
    _input: FetchEnabledRunsInput,
) -> FetchEnabledRunsOutput:
    """Resolve the set of (team, skill) runs to trigger this tick.

    Reads enabled `SignalAgentConfig` rows; for each one, expands to the configured
    skill list, falling back to a glob over the team's `signals-agent-*` skills when
    `enabled_skill_names` is null. Skips configs where the resulting skill list is empty.
    """
    async with Heartbeater():
        planned = await asyncio.to_thread(_collect_planned_runs)
    logger.info("signals_agent coordinator: planned runs", count=len(planned))
    return FetchEnabledRunsOutput(planned_runs=planned)


def _collect_planned_runs() -> list[PlannedRun]:
    """Sync DB scan. Runs in a worker thread via `asyncio.to_thread`."""
    # TODO(phase 4): gate behind the `signals-agent-dogfood` feature flag once it
    # exists. For now the `enabled=False` default on `SignalAgentConfig` is the gate.
    configs = list(SignalAgentConfig.objects.filter(enabled=True).select_related("team").order_by("team__id"))
    planned: list[PlannedRun] = []
    for config in configs:
        team = config.team
        team_id = team.id
        # Lazy-seed canonical signals-agent-* skills before we resolve the skill list.
        # Without this, a brand-new team with `enabled_skill_names=None` and zero
        # LLMSkill rows would produce an empty planned set, no child runs would fan
        # out, and the runner-level lazy seed would never be reached — the cadence
        # path would silently never start. No-op when the team already has any
        # signals-agent-* row. Failures don't abort the tick: log and continue.
        try:
            seed_canonical_skills(team)
        except Exception:
            logger.exception(
                "signals_agent coordinator: lazy seed failed for team; continuing",
                extra={"team_id": team_id},
            )
        skill_names = _resolve_skill_names_for_config(config, team_id=team_id)
        for skill_name in skill_names:
            planned.append(
                PlannedRun(
                    team_id=team_id,
                    skill_name=skill_name,
                    budget_overrides=dict(config.budget_overrides or {}),
                )
            )
    # Stable order: team_id then skill_name. Keeps stagger assignment deterministic
    # across ticks and makes child workflow IDs predictable.
    planned.sort(key=lambda p: (p.team_id, p.skill_name))
    if len(planned) > MAX_RUNS_PER_TICK:
        logger.warning(
            "signals_agent coordinator: truncating planned runs above hard cap",
            planned=len(planned),
            cap=MAX_RUNS_PER_TICK,
        )
        planned = planned[:MAX_RUNS_PER_TICK]
    return planned


def _resolve_skill_names_for_config(config: SignalAgentConfig, *, team_id: int) -> list[str]:
    """Return the ordered list of skill names to run for this team's config.

    `enabled_skill_names = None` → glob all `signals-agent-*` skills on the team.
    `enabled_skill_names = [list]` → use the list verbatim, but still validate each
    name actually exists on the team so the activity output is grounded in reality.
    """
    available = set(
        LLMSkill.objects.filter(
            team_id=team_id,
            name__startswith=SIGNALS_AGENT_SKILL_PREFIX,
            is_latest=True,
            deleted=False,
        ).values_list("name", flat=True)
    )
    if config.enabled_skill_names is None:
        return sorted(available)
    requested = list(config.enabled_skill_names)
    resolved = [name for name in requested if name in available]
    missing = [name for name in requested if name not in available]
    if missing:
        logger.warning(
            "signals_agent coordinator: configured skill names not found on team",
            team_id=team_id,
            missing=missing,
        )
    return resolved


@workflow.defn(name="run-signals-agent-coordinator")
class SignalsAgentCoordinatorWorkflow:
    """Hourly coordinator: scans enabled configs, fans out per-(team, skill) child runs.

    Single coordinator workflow per tick; child workflows own their own run-row lifecycle
    via `RunSignalsAgentWorkflow`. Failures are isolated: one failing child does not abort
    siblings or future ticks.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> CoordinatorWorkflowInput:
        if not inputs:
            return CoordinatorWorkflowInput()
        loaded = json.loads(inputs[0])
        return CoordinatorWorkflowInput(**loaded)

    @workflow.run
    async def run(self, input: CoordinatorWorkflowInput) -> CoordinatorWorkflowOutput:
        fetch_result = await workflow.execute_activity(
            fetch_enabled_signals_agent_runs_activity,
            FetchEnabledRunsInput(),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        planned_runs = fetch_result.planned_runs
        if not planned_runs:
            return CoordinatorWorkflowOutput(0, 0, 0, 0)

        stagger_seconds = max(0, int(input.stagger_minutes)) * 60
        tick_id = workflow.info().workflow_id
        tasks = [
            asyncio.create_task(
                _launch_child_with_stagger(
                    idx=idx,
                    stagger_seconds=stagger_seconds,
                    planned=planned,
                    tick_id=tick_id,
                )
            )
            for idx, planned in enumerate(planned_runs)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return _summarize_results(planned_runs, results)


async def _launch_child_with_stagger(
    *,
    idx: int,
    stagger_seconds: int,
    planned: PlannedRun,
    tick_id: str,
) -> RunSignalsAgentOutput:
    """Sleep for our stagger slot, then synchronously execute the child workflow.

    Using `execute_child_workflow` (vs `start_child_workflow`) keeps the coordinator
    waiting on completion so we can surface aggregate counts. With the hourly tick and
    `ScheduleOverlapPolicy.SKIP`, a slow batch just delays the next tick — better than
    fire-and-forget which would lose visibility into failures.
    """
    if idx > 0 and stagger_seconds > 0:
        await workflow.sleep(idx * stagger_seconds)
    child_id = _child_workflow_id(planned, tick_id, idx)
    return await workflow.execute_child_workflow(
        RunSignalsAgentWorkflow.run,
        RunSignalsAgentInput(
            team_id=planned.team_id,
            skill_name=planned.skill_name,
            budget_overrides=planned.budget_overrides or None,
        ),
        id=child_id,
    )


def _child_workflow_id(planned: PlannedRun, tick_id: str, idx: int) -> str:
    # Tick_id makes the ID unique across coordinator runs; idx disambiguates if a team
    # somehow ends up with the same skill twice in a tick (defense-in-depth — the
    # planning step already dedupes via sorted unique).
    safe_skill = planned.skill_name.replace(" ", "_")[:60]
    return f"signals-agent-run-{planned.team_id}-{safe_skill}-{tick_id}-{idx}"


def _summarize_results(planned: list[PlannedRun], results: list[Any]) -> CoordinatorWorkflowOutput:
    triggered = 0
    skipped = 0
    failed = 0
    failures: list[tuple[str, str]] = []
    for plan, outcome in zip(planned, results):
        label = f"{plan.team_id}:{plan.skill_name}"
        if isinstance(outcome, BaseException):
            failed += 1
            failures.append((label, f"{type(outcome).__name__}: {outcome}"))
            continue
        # outcome is `RunSignalsAgentOutput`. Skip-if-running surfaces as `skip_reason` set.
        if outcome.skip_reason is not None:
            skipped += 1
        else:
            triggered += 1
    if failures:
        workflow.logger.warning(
            "signals_agent coordinator: child workflow errors",
            extra={"failed_count": len(failures), "failures": failures},
        )
    return CoordinatorWorkflowOutput(
        planned_count=len(planned),
        triggered_count=triggered,
        skipped_count=skipped,
        failed_count=failed,
    )
