import asyncio
from collections.abc import Callable
from typing import TypedDict, TypeVar

from django.conf import settings

import deltalake
import deltalake.exceptions
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (
    TransientObjectStoreError,
    is_invalid_version_race,
    is_transient_maintenance_error,
    is_transient_object_store_error,
)

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

# Same reasoning as OBJECT_STORE_PERMISSION_DENIED_MESSAGE: this is what a customer reads if every
# retry is exhausted, so it names neither the bucket nor the object key either.
OBJECT_STORE_TRANSIENT_MESSAGE = (
    "PostHog hit a temporary problem reading or writing this table's files in its own storage. "
    "The next scheduled run will try again."
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


class DeltaMergeSpillKwargs(TypedDict, total=False):
    max_spill_size: int
    max_temp_directory_size: int


def delta_merge_spill_kwargs() -> DeltaMergeSpillKwargs:
    """delta-rs `merge` kwargs that let DataFusion spill to disk instead of OOMing on large merges.

    A merge decompresses the target partition into an Arrow working set that can exceed the pod's
    memory limit and take down every co-tenant activity. When the byte budgets are configured (and the
    worker mounts a scratch disk at its TMPDIR), delta-rs bounds DataFusion's memory pool: bytes past
    `max_spill_size` spill to disk, capped at `max_temp_directory_size`. Unset → omit the kwargs so
    DataFusion keeps its unbounded default (today's behavior), which also keeps this compatible with
    deltalake versions predating the parameters.
    """
    kwargs: DeltaMergeSpillKwargs = {}
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
            if is_transient_object_store_error(e):
                # Same blip get_delta_table already classifies (see table.py's
                # _capture_unless_transient) - a bare re-raise here would still mint a fresh
                # error-tracking issue at the activity boundary, and burn the conflict-retry budget
                # on a call that isn't a commit conflict. The raw text (kept only on __cause__) can
                # name the bucket and the object key, so the wrapper's own message stays generic in
                # case every retry is exhausted and it reaches the customer as the sync's error text.
                await logger.awarning(f"{operation_name}: transient object-store error, not reporting: {e}")
                raise TransientObjectStoreError(OBJECT_STORE_TRANSIENT_MESSAGE) from e
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


# delta-rs replays every commit after the latest checkpoint when it opens a table, and it reads that
# uncheckpointed tail twice. Its default checkpoints every 100 commits, so a table that takes many
# small commits pays a long replay on every open. A checkpoint write itself is O(live file count),
# not O(commits since last checkpoint) — it serializes the table's whole current add-action listing —
# so dropping the interval too far raises checkpoint-write frequency on exactly the large/hot tables
# (hundreds to tens of thousands of files, see maintenance.py's documented p90/p99/pathological file
# counts) where that rewrite is most expensive. 25 shortens the uncheckpointed tail well below the
# default without quadrupling checkpoint-write frequency the way 10 would. deltalite reads the same
# property when it commits, so both writers checkpoint on the same cadence.
DELTA_TABLE_PROPERTIES: dict[str, str] = {"delta.checkpointInterval": "25"}


async def ensure_table_properties(table: deltalake.DeltaTable, logger: FilteringBoundLogger) -> bool:
    """Apply DELTA_TABLE_PROPERTIES to a table that was created without them.

    A metadata-only commit, made once per table: the check reads the handle's own snapshot, and
    `set_table_properties` refreshes that snapshot, so a table that already carries the values costs
    nothing here. Never raises, because the data write has already committed and a property that
    fails to land only waits for the next write. Returns True when it committed.
    """
    try:
        # The metadata read is in the same best-effort boundary as the write below: it touches the
        # same table handle (and, on a lazily-loaded snapshot, can hit the same object store), and
        # the data commit has already landed either way, so a failure here must not propagate either.
        current = table.metadata().configuration or {}
        missing = {key: value for key, value in DELTA_TABLE_PROPERTIES.items() if current.get(key) != value}
        if not missing:
            return False
        await execute_with_conflict_retry(
            table, lambda: table.alter.set_table_properties(missing), "set_table_properties", logger
        )
    except ObjectStorePermissionDeniedError as e:
        await logger.awarning(
            f"set_table_properties: could not apply table properties, will retry on the next write: {e}"
        )
        return False
    except Exception as e:  # noqa: BLE001 - best-effort; the data commit already landed
        if not is_transient_maintenance_error(e):
            # Not a known transient/permission case, so this commit can never succeed on its own —
            # every write would otherwise retry it forever with nothing surfacing to error tracking.
            capture_exception(e)
        await logger.awarning(
            f"set_table_properties: could not apply table properties, will retry on the next write: {e}"
        )
        return False
    return True
