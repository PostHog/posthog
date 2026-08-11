import asyncio
from collections.abc import Callable
from typing import TypeVar

from django.conf import settings

import deltalake
import deltalake.exceptions
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import is_invalid_version_race

T = TypeVar("T")


def delta_merge_spill_kwargs() -> dict[str, int]:
    """delta-rs `merge` kwargs that let DataFusion spill to disk instead of OOMing on large merges.

    A merge decompresses the target partition into an Arrow working set that can exceed the pod's
    memory limit and take down every co-tenant activity. When the byte budgets are configured (and the
    worker mounts a scratch disk at its TMPDIR), delta-rs bounds DataFusion's memory pool: bytes past
    `max_spill_size` spill to disk, capped at `max_temp_directory_size`. Unset → omit the kwargs so
    DataFusion keeps its unbounded default (today's behavior), which also keeps this compatible with
    deltalake versions predating the parameters.
    """
    kwargs: dict[str, int] = {}
    if settings.DATA_WAREHOUSE_DELTA_MERGE_MAX_SPILL_SIZE_BYTES is not None:
        kwargs["max_spill_size"] = settings.DATA_WAREHOUSE_DELTA_MERGE_MAX_SPILL_SIZE_BYTES
    if settings.DATA_WAREHOUSE_DELTA_MERGE_MAX_TEMP_DIRECTORY_SIZE_BYTES is not None:
        kwargs["max_temp_directory_size"] = settings.DATA_WAREHOUSE_DELTA_MERGE_MAX_TEMP_DIRECTORY_SIZE_BYTES
    return kwargs


# Delta's conflict checker raises CommitFailedError the moment a concurrent commit invalidates what
# a committing operation read — a merge predicate, optimize.compact's file-rewrite plan, or vacuum's
# tombstone list — unlike a plain version-bump race, delta-rs does not consume max_commit_retries or
# retry this itself (see
# delta-rs kernel/transaction/conflict_checker.rs), because resolving it safely requires re-reading
# the table and re-running the operation, which is exactly what its "must be rerun" error message
# asks the caller to do.
DELTA_MERGE_CONFLICT_RETRIES = 3


async def execute_with_conflict_retry(
    table: deltalake.DeltaTable,
    operation_fn: Callable[[], T],
    operation_name: str,
    logger: FilteringBoundLogger,
) -> T:
    """Run a Delta operation that commits (merge, overwrite, append, optimize.compact, vacuum, ...),
    refreshing the table and re-running it on a commit conflict.

    See DELTA_MERGE_CONFLICT_RETRIES for why this can't rely on delta-rs's own retry budget. Also
    retries `is_invalid_version_race` — the same race surfacing as a plain `DeltaError` rather than
    `CommitFailedError` because delta-rs's Python binding doesn't give that variant its own class.
    """
    attempt = 0
    while True:
        try:
            return await asyncio.to_thread(operation_fn)
        except deltalake.exceptions.DeltaError as e:
            if not isinstance(e, deltalake.exceptions.CommitFailedError) and not is_invalid_version_race(e):
                raise
            if attempt >= DELTA_MERGE_CONFLICT_RETRIES:
                raise
            attempt += 1
            await logger.awarning(
                f"{operation_name}: commit conflict, retrying with refreshed table "
                f"(attempt {attempt}/{DELTA_MERGE_CONFLICT_RETRIES})"
            )
            await asyncio.to_thread(table.update_incremental)
