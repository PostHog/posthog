"""Temporal client helper for starting a managed bet's foundry-run-bet workflow tree.

Modeled on ``products/stamphog/backend/temporal/client.py``: a thin fire-and-forget bridge
from Django into Temporal. The workflow tree owns the run's BetEvents/BetNodes from here on.
"""

from __future__ import annotations

import logging

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.temporal.common.client import async_connect

logger = logging.getLogger(__name__)

FOUNDRY_RUN_BET_WORKFLOW = "foundry-run-bet"


@async_to_sync
async def execute_foundry_run_bet_workflow(
    *,
    bet_id: str,
    team_id: int,
    command: str,
    env: dict[str, str],
    memory_repo_url: str | None,
    max_depth: int | None,
    max_children: int | None,
    max_cost: float | None,
) -> None:
    """Start the root node of a managed bet's run. Fire-and-forget: the workflow tree drives
    the rest of the run and reports back purely through BetEvents/BetNodes."""
    # Deferred so the workflow module (and the temporalio workflow sandbox it drags in) stays
    # off the Celery/web import path that this client rides on.
    from products.foundry.backend.temporal.workflow import FoundryNodeInput  # noqa: PLC0415

    client = await async_connect()
    workflow_id = f"foundry-node-{bet_id}-root"
    root_input = FoundryNodeInput(
        bet_id=bet_id,
        team_id=team_id,
        node_id="root",
        parent_node_id=None,
        depth=0,
        runner="",
        command=command,
        env=env,
        memory_repo_url=memory_repo_url,
        max_depth=max_depth,
        max_children=max_children,
        budget_remaining=max_cost,
        own_cost=None,
    )
    await client.start_workflow(
        FOUNDRY_RUN_BET_WORKFLOW,
        root_input,
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=settings.FOUNDRY_TASK_QUEUE,
        # Single attempt at the workflow level, same reasoning as stamphog: a workflow-level
        # retry would restart the whole tree after this node's activities already ran.
        retry_policy=RetryPolicy(maximum_attempts=1),
    )
    logger.info("foundry_run_bet_workflow_started", extra={"bet_id": bet_id, "workflow_id": workflow_id})
