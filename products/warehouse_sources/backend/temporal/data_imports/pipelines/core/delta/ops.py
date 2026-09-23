import asyncio
from collections.abc import Callable
from typing import TypeVar

from django.conf import settings

import deltalake
import deltalake.exceptions
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import is_invalid_version_race

T = TypeVar("T")


# An object store that refuses a read, a write or a delete surfaces the refusal in two shapes,
# because two layers translate it:
# - delta-rs maps a 403 from its Rust `object_store` crate onto `io::ErrorKind::PermissionDenied`,
#   whose `Display` is this one fixed English sentence, and its Python binding hands that back as a
#   bare `OSError`. A refusal that happens while a commit is being written arrives instead as a
#   `CommitFailedError` wrapping the same sentence, because delta-rs maps every
#   `DeltaTableError::Transaction` onto that class regardless of what the transaction failed on.
# - s3fs translates an explicit S3 `AccessDenied` response code into `PermissionError("Access
#   Denied")`.
# Both mean the bucket policy or the worker's role refuses the call on that key, so running the same
# call again returns the same refusal. A bodyless 403 is deliberately not matched: AWS omits the
# error code from a HEAD response, so s3fs raises `PermissionError("Forbidden")` for a brief
# credential-resolution race as well as for a real refusal, and `_purge_s3_prefix` still retries it.
OBJECT_STORE_PERMISSION_DENIED_ERRORS = (
    "The operation lacked the necessary privileges to complete",
    "Access Denied",
)

# Reaches the customer as the sync run's error text, so it names neither the bucket nor the object
# key. The data warehouse bucket is PostHog's own and the worker authenticates to it with its own
# role, which means a refusal here is never caused by the customer's source or credentials.
OBJECT_STORE_PERMISSION_DENIED_MESSAGE = (
    "PostHog could not read or write this table's files in its own storage. This is a problem on "
    "PostHog's side, not with your source. Contact support if it keeps happening."
)


class ObjectStorePermissionDeniedError(Exception):
    """The data warehouse bucket refused a read, a write or a delete.

    Raised in place of the raw `OSError`/`PermissionError`/`CommitFailedError` so the delta layer
    can treat a refusal as its own outcome. It is not a commit conflict and not a transient blip, so
    every retry budget in this package must let it through on the first attempt instead of repeating
    a call that is already refused.
    """


def is_object_store_permission_denied(error: BaseException) -> bool:
    return isinstance(error, OSError | deltalake.exceptions.DeltaError) and any(
        needle in str(error) for needle in OBJECT_STORE_PERMISSION_DENIED_ERRORS
    )


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

    An object-store refusal (see is_object_store_permission_denied) is raised as
    `ObjectStorePermissionDeniedError` on the first attempt, so a refused vacuum or compaction can't
    be mistaken for a conflict and spend the budget on calls that are already refused.
    """
    attempt = 0
    while True:
        try:
            return await asyncio.to_thread(operation_fn)
        except (OSError, deltalake.exceptions.DeltaError) as e:
            if is_object_store_permission_denied(e):
                # The raw error names the object key it was refused on, which must stay out of the
                # customer-facing message, so it is kept only as the cause. The exception class
                # tells which layer translated the refusal, without repeating the key.
                await logger.awarning(f"{operation_name}: the object store denied the operation ({type(e).__name__})")
                raise ObjectStorePermissionDeniedError(OBJECT_STORE_PERMISSION_DENIED_MESSAGE) from e
            if not isinstance(e, deltalake.exceptions.DeltaError):
                raise
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
