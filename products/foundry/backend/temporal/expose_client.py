"""Temporal client helper for starting a bet's foundry-expose-bet workflow.

Modeled on ``build_client.py``/``client.py``: a thin fire-and-forget bridge from Django
into Temporal. The workflow reports back purely through BetEvents
(``exposure.advanced``/``exposure.halted``) — callers never need to await or poll it.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.temporal.common.client import async_connect

logger = logging.getLogger(__name__)

FOUNDRY_EXPOSE_BET_WORKFLOW = "foundry-expose-bet"


@async_to_sync
async def execute_foundry_expose_bet_workflow(
    *,
    bet_id: str,
    team_id: int,
    bet_slug: str,
    flag_id: int,
    guardrails: list[dict[str, Any]],
    steps: list[dict[str, Any]],
) -> None:
    """Start a bet's exposure ramp. Fire-and-forget: the workflow drives the ramp from
    here on and reports back purely through BetEvents."""
    # Deferred so the workflow module (and the temporalio workflow sandbox it drags in)
    # stays off the Celery/web import path that this client rides on.
    from products.foundry.backend.temporal.expose_workflow import (  # noqa: PLC0415
        ExposureStepSpec,
        FoundryExposeBetInput,
    )

    client = await async_connect()
    workflow_id = f"foundry-expose-{bet_id}"
    input = FoundryExposeBetInput(
        bet_id=bet_id,
        team_id=team_id,
        bet_slug=bet_slug,
        flag_id=flag_id,
        guardrails=guardrails,
        steps=[
            ExposureStepSpec(
                rollout_pct=float(step["rollout_pct"]),
                min_hours=float(step["min_hours"]),
                halt_on_guardrail_breach=bool(step.get("halt_on_guardrail_breach", True)),
            )
            for step in steps
        ],
    )
    await client.start_workflow(
        FOUNDRY_EXPOSE_BET_WORKFLOW,
        input,
        id=workflow_id,
        # Same reasoning as build_client.py: a second exposure.started can't normally
        # reach this point anyway (the state machine rejects it once the bet has left
        # GATED), but ALLOW_DUPLICATE_FAILED_ONLY keeps a retry-from-scratch safe if the
        # first attempt's workflow itself failed to start.
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=settings.FOUNDRY_TASK_QUEUE,
        retry_policy=RetryPolicy(maximum_attempts=1),
    )
    logger.info("foundry_expose_bet_workflow_started", extra={"bet_id": bet_id, "workflow_id": workflow_id})
