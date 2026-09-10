"""Shared machinery for reaper activities that fail rows whose workflow is provably gone."""

import asyncio
from collections.abc import Sequence
from typing import Any

from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

_DESCRIBE_CONCURRENCY = 20


async def _workflow_is_open(temporal: Client, workflow_id: str) -> bool | None:
    """Whether the latest run of `workflow_id` is still open; `None` when Temporal couldn't answer."""
    try:
        desc = await temporal.get_workflow_handle(workflow_id).describe()
    except RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND:
            return False
        return None
    except Exception:
        return None
    return desc.status == WorkflowExecutionStatus.RUNNING


async def classify_stale_rows(
    temporal: Client, rows: Sequence[dict[str, Any]], workflow_id_key: str
) -> tuple[list[dict[str, Any]], int, int]:
    """Partition stale rows into provably-reapable vs skipped, describing workflows concurrently.

    Rows without a workflow id are reapable outright. Returns (reapable, skipped_open, skipped_temporal_error);
    rows whose status Temporal couldn't answer are left for the next tick rather than reaped on uncertainty.
    """
    semaphore = asyncio.Semaphore(_DESCRIBE_CONCURRENCY)

    async def _check(row: dict[str, Any]) -> bool | None:
        if not row[workflow_id_key]:
            return False
        async with semaphore:
            return await _workflow_is_open(temporal, row[workflow_id_key])

    # No return_exceptions: _workflow_is_open maps every failure to None, so _check never raises.
    results = await asyncio.gather(*(_check(row) for row in rows))
    reapable: list[dict[str, Any]] = []
    skipped_open = 0
    skipped_temporal_error = 0
    for row, is_open in zip(rows, results):
        if is_open:
            skipped_open += 1
        elif is_open is None:
            skipped_temporal_error += 1
        else:
            reapable.append(row)
    return reapable, skipped_open, skipped_temporal_error
