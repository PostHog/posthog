"""Client helper for the one-shot proactive outcome readout workflow."""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.client import async_connect

from products.subscriptions.backend.temporal.outcomes import (
    PROACTIVE_OUTCOME_READOUT_WORKFLOW_NAME,
    ProactiveOutcomeReadoutInput,
)

logger = logging.getLogger(__name__)


@async_to_sync
async def start_proactive_outcome_readout(*, team_id: int, outcome_id: UUID, due_at: datetime) -> None:
    """Start the single readout; a duplicate start is the same logical delivery."""
    temporal_client = await async_connect()
    try:
        await temporal_client.start_workflow(
            PROACTIVE_OUTCOME_READOUT_WORKFLOW_NAME,
            ProactiveOutcomeReadoutInput(team_id=team_id, outcome_id=outcome_id, due_at=due_at),
            id=f"proactive-outcome-{outcome_id}",
            task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
        )
    except WorkflowAlreadyStartedError:
        logger.info(
            "proactive_outcome_readout_already_started",
            extra={"team_id": team_id, "outcome_id": str(outcome_id)},
        )
