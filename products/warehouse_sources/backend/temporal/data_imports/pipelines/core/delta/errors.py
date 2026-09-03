from django.db import InterfaceError, InternalError, OperationalError

import psycopg.errors
import botocore.exceptions
import deltalake.exceptions

from posthog.temporal.common.errors import NonReportableError

# Substrings of the object-store errors raised talking to our own S3-backed data-warehouse bucket
# that are transient and self-recovering, not a bug in our code or a customer credential problem:
# - the first three come from delta-rs's Rust `object_store` crate inside `DeltaTable.is_deltatable()`
#   (IMDS/STS blips, dispatch timeouts)
# - "Please reduce your request rate" is S3's SlowDown throttling response, surfaced by s3fs/aiobotocore
#   when a bulk operation (e.g. `_purge_s3_prefix`'s list-then-delete) outruns the bucket's request-rate limit
# - "We encountered an internal error. Please try again." is S3's fixed message for its InternalError
#   (500) response, surfaced by s3fs/aiobotocore as an OSError once its own request retries are exhausted
# A retry (of the same idempotent operation) clears these, so they shouldn't be treated the same as a
# bug in our logic.
TRANSIENT_OBJECT_STORE_ERRORS = (
    "an error occurred while loading credentials",
    "the credential provider was not enabled",
    "Generic S3 error",
    "Please reduce your request rate",
    "We encountered an internal error. Please try again.",
)


class TransientObjectStoreError(NonReportableError):
    """A known-transient object-store blip (see is_transient_object_store_error), re-raised as this
    type instead of the original OSError/DeltaError. Skipping the inline capture_exception call
    alone isn't enough: the raw error still escapes the activity uncaught and reaches the Temporal
    activity interceptor (posthog/temporal/common/posthog_client.py), which reports every activity
    exception to error tracking unless it's a NonReportableError — so it minted a fresh issue per
    blip anyway. Wrapping keeps it out of tracking at that boundary too. Temporal's retry policy is
    unaffected either way, since NonReportableError only suppresses reporting, not retries."""


def is_transient_object_store_error(error: BaseException) -> bool:
    """True for a transient object-store error, however it happened to surface.

    `DeltaTable.is_deltatable()` raises these as a plain `OSError`, but table-level operations
    (e.g. `vacuum()`, `optimize.compact()`) wrap the identical underlying object-store error text in
    `deltalake.exceptions.DeltaError` instead — same blip, different exception type depending on
    which delta-rs entry point hit it. `_purge_s3_prefix`'s s3fs/aiobotocore calls can also raise a
    bare `botocore.exceptions.NoCredentialsError` unwrapped — the same IMDS/STS credential-provider
    blip, just surfaced by aiobotocore's own credential resolution instead of delta-rs's Rust
    `object_store` crate. `NoCredentialsError`'s message is a fixed, generic string (no needle to
    match), but hitting our own instance-role-authenticated bucket always means the same transient
    resolution hiccup, so it's recognized by type rather than by message.
    """
    if isinstance(error, TransientObjectStoreError | botocore.exceptions.NoCredentialsError):
        # Already classified and wrapped by a prior call to this same function (see
        # `_capture_unless_transient`) — a caller further up the stack that catches broadly and
        # re-runs this classifier on the wrapper, rather than the original OSError/DeltaError it
        # wraps, must still treat it as transient.
        return True
    return isinstance(error, OSError | deltalake.exceptions.DeltaError) and any(
        needle in str(error) for needle in TRANSIENT_OBJECT_STORE_ERRORS
    )


# `optimize.compact` plans its rewrite against the file list at the start of its scan, then reads
# those files. A concurrent maintenance pass on the same table (e.g. a Temporal activity attempt that
# heartbeat-timed-out but keeps running as a zombie — see this package's README on the equivalent
# unfenced race for repartition) can vacuum one of those files out from under the scan before it gets
# read, which delta-rs surfaces as this DeltaError. The scan failing here means the optimize aborted
# before committing anything — the table is left exactly as it was, just still fragmented — so this is
# safe to skip and retry on the next maintenance pass, not a bug in our logic.
#
# The same concurrent maintenance pass can instead lose the race at commit time rather than during the
# scan: `execute_with_conflict_retry` already refreshes and retries a `CommitFailedError`
# (DELTA_MERGE_CONFLICT_RETRIES times), but sustained contention from another still-running pass can
# exhaust that budget too, and the error then propagates out here. Delta's conflict checker raises this
# for its three concurrent-writer race variants — ConcurrentAppend ("a concurrent transactions added new
# data"), ConcurrentDeleteRead ("a concurrent transaction deleted data this operation read"), and
# ConcurrentDeleteDelete ("a concurrent transaction deleted the same data") — all sharing the "a
# concurrent transaction" substring below. A failed commit never partially applies, so the table is left
# exactly as it was, same as the scan-failure case above: safe to skip and retry on the next maintenance
# pass. Deliberately narrower than matching CommitFailedError outright — MetadataChanged/ProtocolChanged
# commit failures aren't a same-pass race and should still be captured.
TRANSIENT_DELTA_MAINTENANCE_ERRORS = (
    "Optimize selected-file scan failed",
    "Commit failed: a concurrent transaction",
)


def is_transient_delta_maintenance_error(error: BaseException) -> bool:
    if not isinstance(error, deltalake.exceptions.DeltaError):
        return False

    text = str(error)
    if any(needle in text for needle in TRANSIENT_DELTA_MAINTENANCE_ERRORS):
        return True

    # The same race can also take a transaction-log commit file or checkpoint, not just a data file:
    # `reset_table` (full_refresh) purges the whole table prefix, `_delta_log` included, out from under
    # a still-running maintenance pass that opened the table before the purge landed — or out from under
    # a concurrent `DeltaTableRef.get_delta_table()` open reading `_last_checkpoint` and then fetching the
    # checkpoint file it points to. Neither `vacuum()` nor `optimize.compact()` ever deletes a
    # `_delta_log/*.json` commit file or a `*.checkpoint.parquet` itself, so a missing one here means
    # something else raced the read rather than the table being corrupt. Matched on the log directory
    # specifically rather than on "not found" alone, which a genuinely missing data file or a truly
    # corrupt table can also raise, and those stay captured. Covers both delta-rs's older
    # `FileNotFoundError`-style message ("File not found: ...") and its Arrow/object_store kernel message
    # for the same underlying condition ("Object at location ... not found: ... 404 Not Found").
    return "_delta_log/" in text and "not found" in text


# `optimize.compact` bins files to rewrite by their on-disk (compressed) size, targeting
# `target_size` bytes per bin, then reads every file in a bin into memory as Arrow batches before
# writing them back out as one file. `Batcher` (pipelines/core/batcher.py) already keeps each
# *written* file's string/binary columns under its 32-bit-offset limit, so no single file can
# overflow on its own — but that guard doesn't cover compaction, which can bin together several
# already-safe files whose combined column bytes cross the 2^31 (~2.1 GB) offset limit, especially
# for highly-compressible text (e.g. JSON payloads) where on-disk size understates decompressed
# size by a wide margin. delta-rs surfaces this as a Rust task panic wrapped in a generic DeltaError
# rather than a typed error. Retrying the same bin changes nothing, so this isn't transient — the
# caller instead retries compaction with a smaller `target_size` to shrink the bins.
DELTA_OFFSET_OVERFLOW_ERROR_NEEDLE = "byte array offset overflow"


def is_offset_overflow_compaction_error(error: BaseException) -> bool:
    return isinstance(error, deltalake.exceptions.DeltaError) and DELTA_OFFSET_OVERFLOW_ERROR_NEEDLE in str(error)


# The optimistic-concurrency conflict checker raises this when the loser of a race to commit the
# very next version can't read back the winner's just-committed log entry (delta-rs
# `kernel/transaction/conflict_checker.rs`'s `WinningCommitSummary::try_new`) — most commonly two
# writers racing to create the very first version of the same brand-new table, where the version in
# the message is 0. Unlike `CommitFailedError` (mapped from `DeltaTableError::Transaction`), this
# variant falls through delta-rs's Python binding as a plain `DeltaError` (see its `python/src/error.rs`
# catch-all), so callers need to recognize it by message to retry it the same way as a commit conflict.
DELTA_INVALID_VERSION_RACE_NEEDLE = "Invalid table version:"


def is_invalid_version_race(error: BaseException) -> bool:
    return type(error) is deltalake.exceptions.DeltaError and DELTA_INVALID_VERSION_RACE_NEEDLE in str(error)


def is_transient_maintenance_error(error: BaseException) -> bool:
    """Infra blips seen during delta maintenance that aren't a maintenance bug.

    Covers S3/object-store hiccups reaching our own data-warehouse bucket (see
    `is_transient_object_store_error` above), racy concurrent-maintenance DeltaErrors (see
    `is_transient_delta_maintenance_error` above), and app-DB connection blips (DNS, pooler drops) hit
    while resolving `job.folder_path()` on a pooled connection — the same `OperationalError`/`InterfaceError`
    classification used for this failure class in `repartition_table.py`'s `_is_transient_infra_error`.

    Also covers a primary-DB failover briefly routing the watermark's `select_for_update()` onto a
    connection that has become a read-only standby: Postgres raises `ReadOnlySqlTransaction`
    (SQLSTATE 25006) for that, which psycopg classifies under `InternalError` rather than
    `OperationalError`, so it needs its own check — a bare `InternalError` isinstance check would be
    too broad and swallow real corruption errors (e.g. `DataCorrupted`) that share the same base class.
    """
    if isinstance(error, OperationalError | InterfaceError):
        return True
    if isinstance(error, InternalError) and isinstance(error.__cause__, psycopg.errors.ReadOnlySqlTransaction):
        return True
    return is_transient_object_store_error(error) or is_transient_delta_maintenance_error(error)
