from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import structlog
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.live_debugger.backend.temporal.activities import (
        InstallProgramInput,
        PollProgramEventsInput,
        PollProgramEventsOutput,
        UninstallProgramInput,
        install_program_activity,
        poll_program_events_activity,
        uninstall_program_activity,
    )

logger = structlog.get_logger(__name__)

# Activity timeouts
_FAST_ACTIVITY_TIMEOUT = timedelta(seconds=30)
_FAST_ACTIVITY_RETRIES = RetryPolicy(maximum_attempts=3)
# No retries: elapsed-time accounting resets on retry, so a retried poll
# would wait up to max_duration_seconds again from scratch.
_POLL_ACTIVITY_RETRIES = RetryPolicy(maximum_attempts=1)


@dataclass
class LiveDebuggerWorkflowInput:
    team_id: int
    program_code: str
    description: str
    min_events: int = 10
    max_duration_seconds: int = 30 * 60  # 30 minutes
    poll_interval_seconds: int = 60


@dataclass
class LiveDebuggerWorkflowOutput:
    program_id: str
    events: list[dict[str, Any]]
    event_count: int
    timed_out: bool
    duration_seconds: float


@workflow.defn(name="live-debugger-investigation")
class LiveDebuggerWorkflow(PostHogWorkflow):
    """Child workflow: installs a hogtrace program, waits for probe events, then uninstalls.

    Designed to be called via execute_child_workflow() from investigative workflows
    (e.g. AnomalyInvestigationWorkflow, SignalReportSummaryWorkflow). The caller
    receives structured probe findings it can pass to its own Claude agent for analysis.

    The uninstall activity runs in a finally block, so the program is always removed
    even if the workflow is cancelled or the poll times out.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> LiveDebuggerWorkflowInput:
        loaded = json.loads(inputs[0])
        return LiveDebuggerWorkflowInput(**loaded)

    @workflow.run
    async def run(self, input: LiveDebuggerWorkflowInput) -> LiveDebuggerWorkflowOutput:
        program_id = await workflow.execute_activity(
            install_program_activity,
            InstallProgramInput(
                team_id=input.team_id,
                code=input.program_code,
                description=input.description,
            ),
            start_to_close_timeout=_FAST_ACTIVITY_TIMEOUT,
            retry_policy=_FAST_ACTIVITY_RETRIES,
        )

        poll_result: PollProgramEventsOutput | None = None
        try:
            poll_result = await workflow.execute_activity(
                poll_program_events_activity,
                PollProgramEventsInput(
                    team_id=input.team_id,
                    program_id=program_id,
                    min_events=input.min_events,
                    max_duration_seconds=input.max_duration_seconds,
                    poll_interval_seconds=input.poll_interval_seconds,
                ),
                # Give the activity a generous buffer beyond max_duration_seconds.
                start_to_close_timeout=timedelta(seconds=input.max_duration_seconds + 120),
                heartbeat_timeout=timedelta(seconds=2 * 60),
                retry_policy=_POLL_ACTIVITY_RETRIES,
            )
        finally:
            await workflow.execute_activity(
                uninstall_program_activity,
                UninstallProgramInput(team_id=input.team_id, program_id=program_id),
                start_to_close_timeout=_FAST_ACTIVITY_TIMEOUT,
                retry_policy=_FAST_ACTIVITY_RETRIES,
            )

        if poll_result is None:
            return LiveDebuggerWorkflowOutput(
                program_id=program_id,
                events=[],
                event_count=0,
                timed_out=True,
                duration_seconds=0,
            )

        return LiveDebuggerWorkflowOutput(
            program_id=poll_result.program_id,
            events=poll_result.events,
            event_count=poll_result.event_count,
            timed_out=poll_result.timed_out,
            duration_seconds=poll_result.duration_seconds,
        )
