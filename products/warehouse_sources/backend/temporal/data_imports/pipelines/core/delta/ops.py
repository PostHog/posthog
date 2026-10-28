import asyncio
from collections.abc import Callable
from typing import TypedDict, TypeVar

from django.conf import settings

import pyarrow as pa
import deltalake
import pyarrow.compute as pc
import botocore.exceptions
import deltalake.exceptions
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (
    TransientObjectStoreError,
    is_invalid_version_race,
    is_missing_scan_file_race,
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
#   Denied")`, and an `InvalidAccessKeyId` response (the worker's own access key no longer exists,
#   e.g. a rotated or revoked credential) into `PermissionError("The AWS Access Key Id you provided
#   does not exist in our records.")` — s3fs always uses the response's own `Message` field, so both
#   collapse to the same `PermissionError` type but keep their own fixed text.
# `AccessDenied` means the bucket policy or the worker's role refuses the call on that key;
# `InvalidAccessKeyId` means AWS doesn't recognize the worker's access key at all. Neither is a race,
# so running the same call again returns the same refusal either way. A bodyless 403 is deliberately
# not matched: AWS omits the error code from a HEAD response, so s3fs raises
# `PermissionError("Forbidden")` for a brief credential-resolution race as well as for a real
# refusal, and `_purge_s3_prefix` still retries it.
OBJECT_STORE_PERMISSION_DENIED_ERRORS = (
    "The operation lacked the necessary privileges to complete",
    "Access Denied",
    "The AWS Access Key Id you provided does not exist in our records.",
)

# Codes s3fs also maps onto PermissionError (see ERROR_CODE_TO_EXCEPTION in its errors module) but
# whose s3fs-translated message isn't the fixed, matchable text the needles above rely on — our
# backend returns a generic "Invalid argument." Message for SignatureDoesNotMatch instead of AWS's
# usual signature-mismatch sentence. The code itself still names a definitive, non-racy refusal
# (unlike a bodyless 403, see is_object_store_permission_denied), so it's read off the chained
# ClientError instead of guessed from message text.
_PERMISSION_DENIED_CLIENT_ERROR_CODES = ("SignatureDoesNotMatch",)

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
    cause = error.__cause__
    if (
        isinstance(error, OSError)
        and isinstance(cause, botocore.exceptions.ClientError)
        and cause.response.get("Error", {}).get("Code") in _PERMISSION_DENIED_CLIENT_ERROR_CODES
    ):
        return True
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
    *,
    conflict_retries: int = DELTA_MERGE_CONFLICT_RETRIES,
) -> T:
    """Run a Delta operation that commits (merge, overwrite, append, optimize.compact, vacuum, ...),
    refreshing the table and re-running it on a commit conflict.

    See DELTA_MERGE_CONFLICT_RETRIES for why this can't rely on delta-rs's own retry budget. Also
    retries `is_invalid_version_race` — the same race surfacing as a plain `DeltaError` rather than
    `CommitFailedError` because delta-rs's Python binding doesn't give that variant its own class —
    and `is_missing_scan_file_race`, where a concurrent vacuum deletes a file the operation's stale
    handle still plans to scan.

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
            if (
                not isinstance(e, deltalake.exceptions.CommitFailedError)
                and not is_invalid_version_race(e)
                and not is_missing_scan_file_race(e)
            ):
                raise
            if attempt >= conflict_retries:
                raise
            attempt += 1
            await logger.awarning(
                f"{operation_name}: commit conflict, retrying with refreshed table "
                f"(attempt {attempt}/{conflict_retries})"
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

MiB = 1024 * 1024
TARGET_FILE_SIZE_PROPERTY = "delta.targetFileSize"
#: deltalite and delta-rs both write files up to this size when a table does not set the property.
DEFAULT_TARGET_FILE_SIZE_BYTES = 100 * MiB

# A merge rewrites every file that holds a matched row, and deltalite writes each file as a single
# row group. When rows are wide, a default-size file holds few rows, so a small update set touches
# almost every file and copies many unchanged rows. A large row group also leaves the memory
# governor room for fewer readers and partition workers in one upsert's slice, often only one of
# each. Smaller files for these tables lower both costs.
#: Stored bytes per row at or above which a merge table counts as wide. A default-size file of such
#: rows holds at most 12,800 rows.
WIDE_ROW_MIN_STORED_BYTES_PER_ROW = 8 * 1024
#: Rows that one file of a wide-row table holds, before the size band below applies.
WIDE_ROW_TARGET_ROWS_PER_FILE = 1024
#: Smaller files cost more footer probes and log entries than they save on a rewrite.
WIDE_ROW_MIN_TARGET_FILE_SIZE_BYTES = 16 * MiB
#: Small enough that the governor can plan several readers and partition workers per upsert.
WIDE_ROW_MAX_TARGET_FILE_SIZE_BYTES = 32 * MiB
#: A smaller table fits in one file at either target, and its per-row estimate still includes the
#: Parquet footer overhead, so the decision waits until the table holds this much data.
WIDE_ROW_MIN_TABLE_BYTES = WIDE_ROW_MAX_TARGET_FILE_SIZE_BYTES


def table_target_file_size(table: deltalake.DeltaTable) -> int:
    """The table's `delta.targetFileSize` in bytes, or the writers' default when it is absent or invalid."""
    raw = (table.metadata().configuration or {}).get(TARGET_FILE_SIZE_PROPERTY)
    if not isinstance(raw, str) or not raw.strip().isdigit() or int(raw) <= 0:
        return DEFAULT_TARGET_FILE_SIZE_BYTES
    return int(raw)


def wide_row_target_file_size(add_actions: pa.Table) -> int | None:
    """A smaller `delta.targetFileSize` for a table of wide rows, or None to keep the default.

    Bytes per row come from the add actions: the stored size and the row count of each file that
    records its row count. The result is a whole number of MiB, so the same table always gets the same value.
    """
    if add_actions.num_rows == 0 or not {"size_bytes", "num_records"} <= set(add_actions.column_names):
        return None
    counted = add_actions.filter(pc.greater(add_actions["num_records"], pa.scalar(0)))
    stored_bytes = pc.sum(counted["size_bytes"]).as_py() or 0
    rows = pc.sum(counted["num_records"]).as_py() or 0
    if rows == 0 or stored_bytes < WIDE_ROW_MIN_TABLE_BYTES:
        return None
    bytes_per_row = stored_bytes / rows
    if bytes_per_row < WIDE_ROW_MIN_STORED_BYTES_PER_ROW:
        return None
    target_mib = round(WIDE_ROW_TARGET_ROWS_PER_FILE * bytes_per_row / MiB)
    return max(WIDE_ROW_MIN_TARGET_FILE_SIZE_BYTES, min(WIDE_ROW_MAX_TARGET_FILE_SIZE_BYTES, target_mib * MiB))


def _may_hold_wide_rows(batch: pa.Table) -> bool:
    # Arrow holds a row in at least as many bytes as Parquet stores it in, so a narrow batch rules
    # out a wide table without the add-action read, which costs O(files) on every write.
    return batch.num_rows > 0 and batch.nbytes / batch.num_rows >= WIDE_ROW_MIN_STORED_BYTES_PER_ROW


def _wide_row_table_properties(table: deltalake.DeltaTable) -> dict[str, str]:
    add_actions = pa.table(table.get_add_actions(flatten=False)).select(["size_bytes", "num_records"])
    target = wide_row_target_file_size(add_actions)
    return {} if target is None else {TARGET_FILE_SIZE_PROPERTY: str(target)}


async def ensure_table_properties(
    table: deltalake.DeltaTable, logger: FilteringBoundLogger, *, merge_batch: pa.Table | None = None
) -> bool:
    """Apply DELTA_TABLE_PROPERTIES to a table that was created without them.

    A metadata-only commit, made once per table: the check reads the handle's own snapshot, and
    `set_table_properties` refreshes that snapshot, so a table that already carries the values costs
    nothing here. Never raises, because the data write has already committed and a property that
    fails to land only waits for the next write. Returns True when it committed.

    `merge_batch` is the batch just merged into a table that loads by merging on a primary key, and
    None for every other write. Such a table of wide rows also gets a smaller `delta.targetFileSize`
    (see `wide_row_target_file_size`). The value is set only when the table has none, so it never
    changes after that and never replaces a value set by hand.
    """
    try:
        # The metadata read is in the same best-effort boundary as the write below: it touches the
        # same table handle (and, on a lazily-loaded snapshot, can hit the same object store), and
        # the data commit has already landed either way, so a failure here must not propagate either.
        current = table.metadata().configuration or {}
        missing = {key: value for key, value in DELTA_TABLE_PROPERTIES.items() if current.get(key) != value}
        if merge_batch is not None and TARGET_FILE_SIZE_PROPERTY not in current and _may_hold_wide_rows(merge_batch):
            missing.update(await asyncio.to_thread(_wide_row_table_properties, table))
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
