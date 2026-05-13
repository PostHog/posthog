from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import structlog
from temporalio import activity

from posthog.temporal.common.heartbeat import Heartbeater

logger = structlog.get_logger(__name__)

POLL_ACTIVITY_HEARTBEAT_TIMEOUT_SECONDS = 2 * 60  # 2 minutes


@dataclass
class InstallProgramInput:
    team_id: int
    code: str
    description: str


@dataclass
class PollProgramEventsInput:
    team_id: int
    program_id: str
    min_events: int = 10
    max_duration_seconds: int = 30 * 60  # 30 minutes
    poll_interval_seconds: int = 60


@dataclass
class PollProgramEventsOutput:
    program_id: str
    events: list[dict[str, Any]]
    event_count: int
    timed_out: bool
    duration_seconds: float


@dataclass
class UninstallProgramInput:
    team_id: int
    program_id: str


@activity.defn
async def install_program_activity(input: InstallProgramInput) -> str:
    """Create a LiveDebuggerProgram row and return its id."""
    from products.live_debugger.backend.models import LiveDebuggerProgram

    program = await LiveDebuggerProgram.objects.acreate(
        team_id=input.team_id,
        code=input.code,
        description=input.description,
    )
    logger.info("live_debugger.program_installed", program_id=str(program.id), team_id=input.team_id)
    return str(program.id)


@activity.defn
async def poll_program_events_activity(input: PollProgramEventsInput) -> PollProgramEventsOutput:
    """Poll ClickHouse for probe events until min_events is reached or max_duration_seconds elapses.

    Heartbeats regularly so Temporal knows the activity is alive during the wait.
    Set maximum_attempts=1 on the workflow side — this activity is not safe to retry
    because the elapsed-time accounting restarts from zero on each attempt.
    """
    from asgiref.sync import sync_to_async

    from posthog.models import Team
    from products.live_debugger.backend.models import LiveDebuggerProgram

    team = await Team.objects.aget(id=input.team_id)
    started_at = time.monotonic()

    async with Heartbeater():
        while True:
            elapsed = time.monotonic() - started_at

            if elapsed >= input.max_duration_seconds:
                logger.info(
                    "live_debugger.poll_timed_out",
                    program_id=input.program_id,
                    elapsed_seconds=elapsed,
                )
                events = await sync_to_async(LiveDebuggerProgram.get_program_events, thread_sensitive=False)(
                    team=team,
                    program_id=input.program_id,
                    limit=1000,
                )
                return PollProgramEventsOutput(
                    program_id=input.program_id,
                    events=[e.to_json() for e in events],
                    event_count=len(events),
                    timed_out=True,
                    duration_seconds=elapsed,
                )

            events = await sync_to_async(LiveDebuggerProgram.get_program_events, thread_sensitive=False)(
                team=team,
                program_id=input.program_id,
                limit=1000,
            )

            logger.info(
                "live_debugger.poll_tick",
                program_id=input.program_id,
                event_count=len(events),
                min_events=input.min_events,
                elapsed_seconds=elapsed,
            )

            if len(events) >= input.min_events:
                return PollProgramEventsOutput(
                    program_id=input.program_id,
                    events=[e.to_json() for e in events],
                    event_count=len(events),
                    timed_out=False,
                    duration_seconds=time.monotonic() - started_at,
                )

            await asyncio.sleep(input.poll_interval_seconds)


@activity.defn
async def uninstall_program_activity(input: UninstallProgramInput) -> None:
    """Flip the program status to uninstalled. Idempotent."""
    from products.live_debugger.backend.models import LiveDebuggerProgram

    try:
        program = await LiveDebuggerProgram.objects.aget(id=input.program_id, team_id=input.team_id)
    except LiveDebuggerProgram.DoesNotExist:
        logger.warning("live_debugger.uninstall_noop", program_id=input.program_id)
        return
    if program.status != LiveDebuggerProgram.Status.UNINSTALLED:
        program.status = LiveDebuggerProgram.Status.UNINSTALLED
        await program.asave(update_fields=["status", "updated_at"])
        logger.info("live_debugger.program_uninstalled", program_id=input.program_id)
    else:
        logger.info("live_debugger.uninstall_already_uninstalled", program_id=input.program_id)
