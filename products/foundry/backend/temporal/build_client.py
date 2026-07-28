"""Temporal client helper for starting a managed bet's foundry-build-bet workflow.

Modeled on ``client.py`` (the plain foundry-run-bet equivalent): a thin fire-and-forget
bridge from Django into Temporal. The workflow owns the run's BetEvents/BetNodes from here
on, and triggers the (unchanged) gauntlet the same way any other artifact.ready would.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.temporal.common.client import async_connect

logger = logging.getLogger(__name__)

FOUNDRY_BUILD_BET_WORKFLOW = "foundry-build-bet"


@async_to_sync
async def execute_foundry_build_bet_workflow(
    *,
    bet_id: str,
    team_id: int,
    bet_slug: str,
    hypothesis: str,
    success_metric: dict[str, Any],
    protected_paths: list[str],
    target_repo_url: str,
    target_repo_base_ref: str,
    builder: dict[str, Any],
    max_gate_iterations: int,
    memory_repo_url: str | None,
    test_writer: dict[str, Any] | None,
) -> None:
    """Start a managed bet's build-loop run. Fire-and-forget: the workflow drives the rest
    of the run and reports back purely through BetEvents/BetNodes."""
    # Deferred so the workflow module (and the temporalio workflow sandbox it drags in)
    # stays off the Celery/web import path that this client rides on.
    from products.foundry.backend.temporal.build_workflow import (  # noqa: PLC0415
        BuildLoopNodeSpec,
        FoundryBuildBetInput,
    )

    client = await async_connect()
    workflow_id = f"foundry-build-{bet_id}"
    input = FoundryBuildBetInput(
        bet_id=bet_id,
        team_id=team_id,
        bet_slug=bet_slug,
        hypothesis=hypothesis,
        success_metric=success_metric,
        protected_paths=protected_paths,
        target_repo_url=target_repo_url,
        target_repo_base_ref=target_repo_base_ref,
        builder=BuildLoopNodeSpec(command=builder.get("command", ""), env=builder.get("env") or {}),
        max_gate_iterations=max_gate_iterations,
        memory_repo_url=memory_repo_url,
        test_writer=(
            BuildLoopNodeSpec(command=test_writer.get("command", ""), env=test_writer.get("env") or {})
            if test_writer
            else None
        ),
    )
    await client.start_workflow(
        FOUNDRY_BUILD_BET_WORKFLOW,
        input,
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=settings.FOUNDRY_TASK_QUEUE,
        # Single attempt at the workflow level: a workflow-level retry would rerun the
        # entire test-writer/builder-loop choreography, paying for sandboxes/agent calls
        # twice — the same reasoning as foundry-run-bet's root node.
        retry_policy=RetryPolicy(maximum_attempts=1),
    )
    logger.info("foundry_build_bet_workflow_started", extra={"bet_id": bet_id, "workflow_id": workflow_id})
