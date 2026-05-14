"""Public Python facade for live investigations.

Single source of truth for starting an investigation. Both the in-process callers
(anomaly investigation's toolkit, future agents) and the future MCP viewset
delegate here.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import transaction

import temporalio.exceptions

from posthog.temporal.ai.live_investigation.schemas import (
    LiveInvestigationWorkflowInput,
    StartLiveInvestigationArgs,
)
from posthog.temporal.common.client import async_connect

from products.live_debugger.backend.models import LiveDebuggerProgram, LiveInvestigation

if TYPE_CHECKING:
    from posthog.models import Team

logger = logging.getLogger(__name__)

MAX_CHAIN_DEPTH = 3


class ChainDepthExceeded(Exception):
    """Raised when a chained investigation would exceed MAX_CHAIN_DEPTH."""


class ParentInvestigationNotFound(Exception):
    """Raised when a parent_investigation_id is given but the row doesn't exist
    or doesn't belong to the calling team."""


def _create_program_and_investigation(
    *,
    team: "Team",
    args: StartLiveInvestigationArgs,
    signal_source_type: str,
    signal_source_id: str,
    workflow_id: str,
) -> LiveInvestigation:
    """Sync helper that does the DB writes inside one transaction.

    Validates chain_depth against the parent (if any) before creating either row.
    """
    chain_depth = 0
    parent: LiveInvestigation | None = None

    if args.parent_investigation_id is not None:
        try:
            parent = LiveInvestigation.objects.get(
                id=args.parent_investigation_id,
                team=team,
            )
        except LiveInvestigation.DoesNotExist as err:
            raise ParentInvestigationNotFound(
                f"Parent investigation {args.parent_investigation_id} not found for team {team.id}"
            ) from err
        if parent.chain_depth + 1 > MAX_CHAIN_DEPTH:
            raise ChainDepthExceeded(
                f"Chain depth {parent.chain_depth + 1} exceeds cap {MAX_CHAIN_DEPTH}"
            )
        chain_depth = parent.chain_depth + 1

    with transaction.atomic():
        program = LiveDebuggerProgram.objects.create(
            team=team,
            code=args.hogtrace_code,
            description=args.brief.hypothesis[:200],
        )
        investigation = LiveInvestigation.objects.create(
            team=team,
            program=program,
            parent=parent,
            chain_depth=chain_depth,
            workflow_id=workflow_id,
            min_events=args.min_events,
            max_duration_seconds=args.max_duration_minutes * 60,
            signal_source_type=signal_source_type,
            signal_source_id=signal_source_id,
            brief=args.brief.model_dump(mode="json"),
        )

    return investigation


async def start_live_investigation(
    *,
    team: "Team",
    signal_source_type: str,
    signal_source_id: str,
    args: StartLiveInvestigationArgs,
) -> str:
    """Start a durable live investigation. Returns the investigation_id.

    Creates a LiveDebuggerProgram (so probe events start flowing immediately),
    creates a LiveInvestigation row in WATCHING state, and starts a
    LiveInvestigationWorkflow that owns the rest of the lifecycle.

    Raises ChainDepthExceeded if parent_investigation_id leads to a chain depth
    greater than MAX_CHAIN_DEPTH.
    """
    # Pre-allocate the workflow ID so the row records it before the workflow exists.
    workflow_id = f"live-investigation-{uuid4()}"

    investigation = await sync_to_async(_create_program_and_investigation, thread_sensitive=False)(
        team=team,
        args=args,
        signal_source_type=signal_source_type,
        signal_source_id=signal_source_id,
        workflow_id=workflow_id,
    )

    client = await async_connect()

    try:
        await client.start_workflow(
            "live-investigation",
            LiveInvestigationWorkflowInput(
                investigation_id=str(investigation.id),
                program_id=str(investigation.program_id),
                max_duration_seconds=investigation.max_duration_seconds,
            ),
            id=workflow_id,
            task_queue=settings.MAX_AI_TASK_QUEUE,
            execution_timeout=timedelta(seconds=investigation.max_duration_seconds + 30 * 60),
        )
    except temporalio.exceptions.WorkflowAlreadyStartedError:
        # Idempotent — the same workflow_id has already been started, which means a
        # retry of this facade call. The first call won; we just return the same ID.
        logger.info("live_investigation.workflow_already_started", extra={"workflow_id": workflow_id})

    return str(investigation.id)
