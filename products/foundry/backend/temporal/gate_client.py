"""Temporal client helper for starting a bet's foundry-run-gate workflow.

Modeled on ``client.py`` (the foundry-run-bet equivalent): a thin fire-and-forget bridge from
Django into Temporal. The workflow reports back purely through BetEvents — a ``note`` per
check, one final ``gate.result`` — so callers never need to await or poll it.
"""

from __future__ import annotations

import uuid
import logging
from typing import Any

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.temporal.common.client import async_connect

logger = logging.getLogger(__name__)

FOUNDRY_RUN_GATE_WORKFLOW = "foundry-run-gate"


@async_to_sync
async def execute_foundry_run_gate_workflow(
    *,
    bet_id: str,
    team_id: int,
    bet_slug: str,
    created_by_id: int | None,
    gate_config: dict[str, Any],
    artifact: dict[str, Any],
) -> None:
    # Deferred so the workflow module (and the temporalio workflow sandbox it drags in) stays
    # off the Celery/web import path that this client rides on.
    from products.foundry.backend.temporal.gate_workflow import GateRunInput  # noqa: PLC0415

    client = await async_connect()
    workflow_id = f"foundry-gate-{bet_id}-{uuid.uuid4().hex[:12]}"
    await client.start_workflow(
        FOUNDRY_RUN_GATE_WORKFLOW,
        GateRunInput(
            bet_id=bet_id,
            team_id=team_id,
            bet_slug=bet_slug,
            created_by_id=created_by_id,
            gate_config=gate_config,
            artifact=artifact,
        ),
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        task_queue=settings.FOUNDRY_TASK_QUEUE,
        # Single attempt at the workflow level: a workflow-level retry would re-provision the
        # sandbox and re-run every check from scratch, paying for the gauntlet twice.
        retry_policy=RetryPolicy(maximum_attempts=1),
    )
    logger.info("foundry_run_gate_workflow_started", extra={"bet_id": bet_id, "workflow_id": workflow_id})
