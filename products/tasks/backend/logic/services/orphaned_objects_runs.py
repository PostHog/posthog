import json
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings

import structlog
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.dataclasses import frozen
from posthog.temporal.common.client import async_connect, sync_connect

from products.tasks.backend.logic.services.orphaned_objects import OrphanedObjectsTotals

logger = structlog.get_logger(__name__)

WORKFLOW_NAME = "delete-orphaned-task-objects"
TOTALS_MEMO_KEY = "totals"
RECENT_RUNS = 10
TEMPORAL_READ_TIMEOUT = timedelta(seconds=5)


@frozen
class OrphanedObjectsInput:
    kinds: list[str]
    max_prefixes: int
    execute: bool
    requested_by: str


@frozen
class OrphanedObjectsRun:
    workflow_id: str
    run_id: str
    status: str
    execute: bool
    kinds: tuple[str, ...]
    max_prefixes: int
    started: datetime | None
    totals: OrphanedObjectsTotals | None


def orphaned_objects_workflow_id(form_nonce: uuid.UUID, *, execute: bool, kinds: list[str], max_prefixes: int) -> str:
    run_key = uuid.uuid5(form_nonce, json.dumps([execute, sorted(kinds), max_prefixes]))
    return f"{WORKFLOW_NAME}-{run_key}"


def start_orphaned_objects_run(
    form_nonce: uuid.UUID, *, execute: bool, kinds: list[str], max_prefixes: int, requested_by: str
) -> str | None:
    assert kinds
    assert max_prefixes >= 1
    workflow_id = orphaned_objects_workflow_id(form_nonce, execute=execute, kinds=kinds, max_prefixes=max_prefixes)
    start = sync_connect().start_workflow(
        WORKFLOW_NAME,
        OrphanedObjectsInput(kinds=kinds, max_prefixes=max_prefixes, execute=execute, requested_by=requested_by),
        id=workflow_id,
        task_queue=settings.TASKS_TASK_QUEUE,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        memo={"execute": execute, "kinds": kinds, "max_prefixes": max_prefixes},
    )
    try:
        asyncio.run(start)
    except WorkflowAlreadyStartedError:
        return None
    logger.info(
        "orphaned_task_objects.started",
        workflow_id=workflow_id,
        execute=execute,
        kinds=kinds,
        max_prefixes=max_prefixes,
        requested_by=requested_by,
    )
    return workflow_id


def _run_from_memo(
    workflow_id: str, run_id: str, status: str, started: datetime | None, memo: Any
) -> OrphanedObjectsRun:
    totals = memo.get(TOTALS_MEMO_KEY)
    return OrphanedObjectsRun(
        workflow_id=workflow_id,
        run_id=run_id,
        status=status,
        execute=bool(memo.get("execute")),
        kinds=tuple(memo.get("kinds") or ()),
        max_prefixes=int(memo.get("max_prefixes") or 0),
        started=started,
        totals=OrphanedObjectsTotals(**totals) if isinstance(totals, dict) else None,
    )


def recent_orphaned_objects_runs() -> list[OrphanedObjectsRun] | None:
    query = f'WorkflowType = "{WORKFLOW_NAME}"'

    async def fetch() -> list[OrphanedObjectsRun]:
        client = await async_connect()
        runs: list[OrphanedObjectsRun] = []
        async for execution in client.list_workflows(query=query, limit=RECENT_RUNS, rpc_timeout=TEMPORAL_READ_TIMEOUT):
            status = execution.status.name if execution.status else "UNKNOWN"
            memo = await execution.memo()
            runs.append(_run_from_memo(execution.id, execution.run_id, status, execution.start_time, memo))
        return runs

    try:
        return asyncio.run(asyncio.wait_for(fetch(), timeout=TEMPORAL_READ_TIMEOUT.total_seconds()))
    except Exception:
        logger.warning("orphaned_task_objects.runs_unavailable", exc_info=True)
        return None
