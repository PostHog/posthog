import asyncio
from collections.abc import Callable

import deltalake
import deltalake.exceptions
from structlog.types import FilteringBoundLogger

# Delta's conflict checker raises CommitFailedError the moment a concurrent commit invalidates what
# a committing operation read — a merge predicate, or optimize.compact's file-rewrite plan — unlike a
# plain version-bump race, delta-rs does not consume max_commit_retries or retry this itself (see
# delta-rs kernel/transaction/conflict_checker.rs), because resolving it safely requires re-reading
# the table and re-running the operation, which is exactly what its "must be rerun" error message
# asks the caller to do.
DELTA_MERGE_CONFLICT_RETRIES = 3


async def execute_with_conflict_retry(
    table: deltalake.DeltaTable,
    operation_fn: Callable[[], dict],
    operation_name: str,
    logger: FilteringBoundLogger,
) -> dict:
    """Run a Delta operation that commits (merge, optimize.compact, ...), refreshing the table
    and re-running it on a commit conflict.

    See DELTA_MERGE_CONFLICT_RETRIES for why this can't rely on delta-rs's own retry budget.
    """
    attempt = 0
    while True:
        try:
            return await asyncio.to_thread(operation_fn)
        except deltalake.exceptions.CommitFailedError:
            if attempt >= DELTA_MERGE_CONFLICT_RETRIES:
                raise
            attempt += 1
            await logger.awarning(
                f"{operation_name}: commit conflict, retrying with refreshed table "
                f"(attempt {attempt}/{DELTA_MERGE_CONFLICT_RETRIES})"
            )
            await asyncio.to_thread(table.update_incremental)
