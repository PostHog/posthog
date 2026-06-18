from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import structlog
import temporalio
from temporalio.common import RetryPolicy

from posthog.temporal.common.heartbeat import Heartbeater

from products.signals.backend.scout_harness.limits import WORKFLOW_HARD_CEILING_S
from products.signals.backend.scout_harness.runner import RunResult, arun_signals_scout

logger = structlog.get_logger(__name__)


@dataclass
class RunSignalsScoutInput:
    team_id: int
    skill_name: str
    skill_version: int | None = None
    repository: str | None = None


@dataclass
class RunSignalsScoutOutput:
    run_id: str | None
    task_run_id: str | None
    status: str | None
    runtime_s: float
    skill_name: str
    skill_version: int
    skip_reason: str | None = None


def _to_output(result: RunResult) -> RunSignalsScoutOutput:
    return RunSignalsScoutOutput(
        run_id=result.run_id,
        task_run_id=result.task_run_id,
        status=result.status,
        runtime_s=result.runtime_s,
        skill_name=result.skill_name,
        skill_version=result.skill_version,
        skip_reason=result.skip_reason,
    )


@temporalio.activity.defn
async def run_signals_scout_activity(input: RunSignalsScoutInput) -> RunSignalsScoutOutput:
    """One scheduled scout run for a (team, skill) pair.

    Genuine failures are persisted on the run row and the workflow sees a `status='failed'`
    outcome — the "fail safe and silent" rule: a bad skill / prompt does not retry blindly.
    The one exception is a *transient* timeout, which the harness re-raises as
    `TransientScoutTimeoutError` so the workflow's bounded RetryPolicy can rerun the sweep
    rather than dropping the whole scheduled run until the next interval.
    """
    async with Heartbeater():
        result = await arun_signals_scout(
            team_id=input.team_id,
            skill_name=input.skill_name,
            skill_version=input.skill_version,
            repository=input.repository,
        )
    logger.info(
        "signals_scout activity finished",
        team_id=input.team_id,
        skill_name=input.skill_name,
        run_id=result.run_id,
        status=result.status,
        runtime_s=result.runtime_s,
        skip_reason=result.skip_reason,
    )
    return _to_output(result)


@temporalio.workflow.defn
class RunSignalsScoutWorkflow:
    """Drives one scheduled scout run.

    The activity owns the run-row lifecycle (insert/update). The workflow's job is just
    to spawn the activity with the right timeout and retry posture, and surface the
    outcome to the scheduler.
    """

    @temporalio.workflow.run
    async def run(self, input: RunSignalsScoutInput) -> RunSignalsScoutOutput:
        return await temporalio.workflow.execute_activity(
            run_signals_scout_activity,
            input,
            start_to_close_timeout=timedelta(seconds=WORKFLOW_HARD_CEILING_S),
            heartbeat_timeout=timedelta(minutes=2),
            # Bounded retry-with-backoff for *transient* timeouts only: the activity's own
            # start_to_close / heartbeat expiry (Temporal raises a retryable timeout), and the
            # agent poll-budget exhaustion the harness re-raises as `TransientScoutTimeoutError`.
            # Each retry is a fresh activity attempt with its own start_to_close budget, and the
            # prior attempt's TaskRun is already terminal (MultiTurnSession marks it failed before
            # the error propagates), so the runner's single-flight guard lets the retry proceed.
            # Genuine permanent failures fail fast — a missing/stale skill (`SkillNotFoundError`)
            # or a missing team / config row (`DoesNotExist`) would fail identically every attempt;
            # other genuine skill / prompt errors stay on the swallow-into-`failed` path and never
            # raise, so they don't trigger a retry at all.
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=30),
                backoff_coefficient=2.0,
                maximum_interval=timedelta(minutes=2),
                maximum_attempts=3,
                non_retryable_error_types=["SkillNotFoundError", "DoesNotExist"],
            ),
        )
