from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import structlog
import temporalio
from temporalio.common import RetryPolicy

from posthog.temporal.common.heartbeat import LivenessHeartbeater

from products.signals.backend.scout_harness.limits import DEFAULT_MAX_RUNTIME_S
from products.signals.backend.scout_harness.runner import RunResult, arun_signals_scout

logger = structlog.get_logger(__name__)

# Hard activity timeout = budget runtime + slack so heartbeat-based failures surface
# before Temporal's own timeout fires.
_ACTIVITY_SLACK_S = 60


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

    The activity itself never raises — failures are persisted on the run row and the
    workflow sees a `status='failed'` outcome. This matches the spec's "fail safe and
    silent" rule: a bad run does not retry blindly.
    """
    # LivenessHeartbeater (not the plain Heartbeater): this is a long-lived (~30 min)
    # activity, so its heartbeats must also refresh the worker's LivenessTracker —
    # otherwise the health server's idle window elapses mid-run and k8s restarts the pod.
    async with LivenessHeartbeater():
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
            start_to_close_timeout=timedelta(seconds=DEFAULT_MAX_RUNTIME_S + _ACTIVITY_SLACK_S),
            heartbeat_timeout=timedelta(minutes=2),
            # No retries: failures are persisted as `status='failed'` on the run row and
            # we don't want a bad skill / prompt to spin retry loops. The next scheduled
            # tick will try again.
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
