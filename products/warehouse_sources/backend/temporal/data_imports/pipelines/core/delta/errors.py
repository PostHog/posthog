import re
import errno

from django.db import InterfaceError, InternalError, OperationalError

import psycopg.errors
import botocore.exceptions
import deltalake.exceptions

from posthog.temporal.common.errors import NonReportableError

# `errno` only defines EREMOTEIO on platforms that have it (Linux); referencing it directly breaks
# import on a Mac dev machine. s3fs's own translation table (s3fs/errors.py) falls back to EIO for
# the same reason, so matching with the identical fallback stays consistent with what s3fs actually
# sets there.
_EREMOTEIO = getattr(errno, "EREMOTEIO", errno.EIO)

# Substrings of the object-store errors raised talking to our own S3-backed data-warehouse bucket
# that are transient and self-recovering, not a bug in our code or a customer credential problem:
# - the first three come from delta-rs's Rust `object_store` crate inside `DeltaTable.is_deltatable()`
#   (IMDS/STS blips, dispatch timeouts)
# - "Please reduce your request rate" is S3's SlowDown throttling response, surfaced by s3fs/aiobotocore
#   when a bulk operation (e.g. `_purge_s3_prefix`'s list-then-delete) outruns the bucket's request-rate limit
# - "We encountered an internal error. Please try again." is S3's fixed message for its InternalError
#   (500) response, surfaced by s3fs/aiobotocore as an OSError once its own request retries are exhausted
# - "The difference between the request time and the current time is too large." is S3's fixed message
#   for RequestTimeTooSkewed, raised when the worker's clock has drifted from S3's. s3fs maps every 403
#   onto the same generic PermissionError (s3fs/errors.py::translate_boto_error), so this message - not
#   a permission denial - is the only way to tell the two apart. The worker's own clock resyncs and the
#   identical request succeeds moments later.
# - "connection closed before message completed" is delta-rs's own object_store crate (reqwest/hyper)
#   reporting a connection the remote end dropped mid-response - it already prefixes this with its own
#   "Unexpected (temporary)" classification before this classifier even runs, so a retry against a fresh
#   connection is exactly what self-heals it, the same as any other blip in this list.
# - "Connection timed out" is the bare OS-level message a dropped TCP handshake/response leaves behind
#   when our own bucket is a non-AWS S3-compatible store reached through delta-rs's generic S3 client
#   with a custom `endpoint_url` (e.g. Alibaba Cloud OSS's S3-compatible API, addressed virtual-hosted
#   per products/data_warehouse/backend/s3_proxy.py) rather than AWS's own endpoints - that path never
#   goes through s3fs/aiobotocore, so it can't surface as one of the typed botocore exceptions below.
# A retry (of the same idempotent operation) clears these, so they shouldn't be treated the same as a
# bug in our logic.
TRANSIENT_OBJECT_STORE_ERRORS = (
    "an error occurred while loading credentials",
    "the credential provider was not enabled",
    "Generic S3 error",
    "Please reduce your request rate",
    "We encountered an internal error. Please try again.",
    "The difference between the request time and the current time is too large.",
    "connection closed before message completed",
    "Connection timed out",
)

# pyarrow's S3FileSystem (the AWS SDK for C++) reports a response it can't classify as the fixed
# "UNKNOWN" error code, which happens whenever AWS replies with no parseable XML error body. A
# bodyless 5xx is always a transient server-side blip - the same class the named 5xx messages above
# cover - and clears on retry. But AWS also omits the body for a HeadObject 403 or 404 (it never
# includes one for HEAD requests, regardless of status), so the bare "AWS Error UNKNOWN" string alone
# can't tell a blip apart from a permanent permission or missing-object error. The HTTP status pyarrow
# puts in the message is the only thing that distinguishes them.
_BODYLESS_UNKNOWN_STATUS_RE = re.compile(r"AWS Error UNKNOWN \(HTTP status (\d{3})\)")


def _is_bodyless_5xx_unknown_error(error: BaseException) -> bool:
    match = _BODYLESS_UNKNOWN_STATUS_RE.search(str(error))
    return match is not None and match.group(1).startswith("5")


# A warehouse bucket backed by Aliyun OSS instead of S3 (see s3_proxy.py's module docstring on OSS as
# a supported backend) surfaces a 500 as this OSS-specific error shape instead of the S3 messages
# above - delta-rs's own object-store layer already marks it "(temporary)" before wrapping OSS's
# Debug-formatted source struct. Matched on the `code` field rather than the free-text `message`,
# which, unlike S3's fixed internal-error string, OSS's own InternalError responses don't keep fixed.
_OSS_INTERNAL_ERROR_NEEDLE = 'OssError { code: "InternalError"'


def _is_oss_internal_error(error: BaseException) -> bool:
    # `is_deltatable()` exposes the raw `OSError`, but table-level operations (vacuum, optimize,
    # commit) wrap the identical underlying object-store error in `deltalake.exceptions.DeltaError`
    # instead - same split the S3 needles above already account for.
    return isinstance(error, OSError | deltalake.exceptions.DeltaError) and _OSS_INTERNAL_ERROR_NEEDLE in str(error)


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

    `boto3`'s own client calls (e.g. `ensure_bucket_exists`'s `head_bucket`) can likewise raise a bare
    `botocore.exceptions.ConnectionError` — `EndpointConnectionError` (DNS not resolvable yet, or the
    endpoint refusing connections) and its siblings — when our own bucket endpoint isn't reachable
    yet, most commonly a local/self-hosted object store still bootstrapping. Never an `OSError`
    subclass, so the message-matched branch below never sees it; recognized by type for the same
    reason as `NoCredentialsError`.

    A read that times out or a connection the object store drops mid-response surfaces as a bare
    `botocore.exceptions.HTTPClientError` (`ReadTimeoutError`, `ConnectionClosedError`) the same way:
    s3fs's own retries only translate a *response* it got back into an `OSError`, and a request that
    never got one never does. `s3/writer.py`'s `_is_transient_s3_write_error` already retries this
    class on the write path; recognized by type here too so the copy/maintenance paths that share
    this classifier treat the same blip the same way instead of reporting it as a bug on the first
    occurrence.

    A bare `OSError` with errno `EMFILE`/`ENFILE` means this worker's (or the system's) file
    descriptor table is full — e.g. `aget_s3_client`'s aiobotocore session bootstrap opening
    botocore's own bundled `endpoints.json` fails with this errno before any network call is even
    made. Same transient-capacity class already recognized on the postgres connect path
    (`_is_too_many_open_files_error`): a descriptor frees the moment another connection/client in
    this worker closes, so it's fd pressure on our side, never an object-store or customer problem.

    A bare `OSError` with errno `EBUSY` is s3fs's translation of every S3 "back off" response
    (`SlowDown`, `ServiceUnavailable`, `OperationAborted`, a bare 503/409; see
    `s3fs/errors.py::translate_boto_error`), raised once s3fs's own retries are exhausted. The errno
    covers the 503 "Service Unavailable" case the message needles below miss, without matching on
    the vendor's free text.

    A bare `OSError` with errno `EREMOTEIO` is the same `translate_boto_error` table's entry for
    `InternalError`/bare "500" - the exact blip the "We encountered an internal error" needle below
    names, but recognized by errno instead so an S3-compatible provider that returns its own wording
    for that response code (self-hosted setups routing the data-warehouse bucket through a non-AWS
    endpoint) still matches without a needle per vendor.

    A bodyless 5xx that pyarrow's S3FileSystem reports as "AWS Error UNKNOWN" (see
    `_is_bodyless_5xx_unknown_error`) is also transient - but only once its status is confirmed to be
    5xx, because AWS omits the error body (and so reports the same UNKNOWN code) for a permanent
    HeadObject 403 or 404 too.

    A warehouse bucket backed by Aliyun OSS instead of S3 reports its own 500 "InternalError" as this
    OSS-specific error shape (see `_is_oss_internal_error`), already marked "(temporary)" by delta-rs's
    object-store layer before this classifier even runs.

    Deliberately does not cover `ensure_bucket_exists`'s own exhausted `HeadBucket` 403 retry (see
    `_is_exhausted_head_bucket_forbidden` below) — that check only runs under `USE_LOCAL_SETUP`,
    where the bucket credentials are operator-configured rather than our own IAM instance role, so an
    exhausted retry can genuinely mean a broken local setup, not just a boot race. Callers that must
    eventually give up and report a persistent failure (e.g. `repartition_table.py`'s
    `_is_transient_infra_error`, which bounds retries via `MAX_REPARTITION_ATTEMPTS`) call this
    function directly and so never see that shape as transient. Only the best-effort pre-extraction
    probe (`is_transient_maintenance_error`, which has no such give-up budget to bypass and whose
    failure is a silent no-op either way) folds it in.
    """
    if isinstance(
        error,
        TransientObjectStoreError
        | botocore.exceptions.NoCredentialsError
        | botocore.exceptions.ConnectionError
        | botocore.exceptions.HTTPClientError,
    ):
        # Already classified and wrapped by a prior call to this same function (see
        # `_capture_unless_transient`) — a caller further up the stack that catches broadly and
        # re-runs this classifier on the wrapper, rather than the original OSError/DeltaError it
        # wraps, must still treat it as transient.
        return True
    if isinstance(error, OSError) and error.errno in (errno.EMFILE, errno.ENFILE, errno.EBUSY, _EREMOTEIO):
        return True
    if isinstance(error, OSError) and _is_bodyless_5xx_unknown_error(error):
        return True
    if _is_oss_internal_error(error):
        return True
    return isinstance(error, OSError | deltalake.exceptions.DeltaError) and any(
        needle in str(error) for needle in TRANSIENT_OBJECT_STORE_ERRORS
    )


def _is_exhausted_head_bucket_forbidden(error: BaseException) -> bool:
    """True for the `ClientError` `ensure_bucket_exists` raises once its own `HeadBucket` 403 retries
    are exhausted (see its `_HEAD_BUCKET_MAX_ATTEMPTS` loop).

    The response carries no error body to tell a credential-bootstrap race (a local/self-hosted
    object store still starting up) apart from a genuine, persistent denial — same ambiguity as the
    sibling `HeadObject` case `_is_retryable_purge_error` documents. Unlike that case, an exhausted
    retry here isn't folded into `is_transient_object_store_error`: see that function's docstring for
    why only a caller with no give-up budget to bypass should treat this shape as transient.
    """
    return (
        isinstance(error, botocore.exceptions.ClientError)
        and error.operation_name == "HeadBucket"
        and error.response.get("Error", {}).get("Code") == "403"
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
    if "_delta_log/" in text and "not found" in text:
        return True

    # Yet another shape of the same reset-vs-stale-handle race: `DeltaTableRef._refresh_cached_table`
    # calls `update_incremental()` on a delta-rs handle that a prior write or `note_deltalite_commit`
    # already advanced to some version. If `reset_table` (or a repartition swap) replaces `_delta_log`
    # under this ref — most commonly the live attempt resyncing while a heartbeat-timed-out zombie
    # attempt still holds this older handle (see this package's README on the equivalent unfenced race
    # for repartition) — the log the refresh reads back is the fresh, lower-numbered one. Delta logs
    # are append-only, so the kernel refuses to apply that as an increment: "Unexpected state: the
    # newest version in the log {low} is older than the existing snapshot version {high}". The live
    # table itself is unaffected; only this stale handle's refresh failed, so the next reader (a
    # retried activity opens a fresh `DeltaTableRef`) reads the current log and succeeds.
    return "is older than the existing snapshot version" in text


# A fourth shape of the same reset-vs-concurrent-read race, caught by the kernel's log-segment
# listing instead of a single file lookup: `_purge_s3_prefix_once` lists the table's live
# `_delta_log` files once and bulk-deletes them in one `_rm` call, which S3 does not guarantee to
# apply in any particular order across keys. A concurrent open that lists the directory (or reads
# `_last_checkpoint` and fetches the checkpoint it names) mid-delete can see an arbitrary subset of
# that batch already gone — a run of consecutive commit files missing from the middle of the
# sequence ("Expected contiguous commit files, but found gap"), or a `_last_checkpoint` hint whose
# checkpoint file the same batch already removed ("Had a _last_checkpoint hint but didn't find any
# checkpoints"). Moments later the purge finishes and the next reader opens a fresh, consistent log.
#
# Deliberately NOT folded into `is_transient_delta_maintenance_error` above: that function also backs
# `DeltaTableRef.is_table_corrupted`, whose whole purpose is catching a log left genuinely broken by an
# interrupted repartition swap or an OOM-crashed merge (see its docstring) so `handle_corrupted_delta_log`
# can revive it — and unlike the single-file "not found" case, a missing *run* of commit files or a
# dangling checkpoint hint is exactly the shape that kind of interrupted write leaves behind too. Folding
# these in would make `is_table_corrupted` read a genuinely and permanently broken log as transient,
# silently skip the revive, and loop the sync forever with nothing reported. Scoped instead to the one
# call site (`DeltaTableRef._capture_unless_transient`) that only suppresses error-tracking noise on the
# common race, while `is_table_corrupted`'s own independent open keeps classifying a log that is still in
# this state on a later attempt as corrupt and reviving it.
DELTA_LOG_LISTING_RACE_ERRORS = (
    "Expected contiguous commit files",
    "Had a _last_checkpoint hint but didn't find any checkpoints",
)


def is_transient_delta_log_listing_race(error: BaseException) -> bool:
    return isinstance(error, deltalake.exceptions.DeltaError) and any(
        needle in str(error) for needle in DELTA_LOG_LISTING_RACE_ERRORS
    )


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


# `merge()` plans its scan against the target's file list from the `DeltaTable` handle it was given,
# then fetches each planned file's Parquet footer when the scan actually runs. A concurrent vacuum
# (most commonly a heartbeat-timed-out zombie attempt running the post-load maintenance pass — see
# this package's README on the equivalent race for repartition) can commit a REMOVE for one of those
# files and delete it from the object store in between: the handle's in-memory plan still names it,
# so the footer fetch 404s. delta-rs has no typed error for this — it surfaces as the same generic
# DeltaError every Parquet-level failure does, with the object store's 404 body folded into the
# message. Refreshing the handle (exactly what `execute_with_conflict_retry` already does for
# `CommitFailedError`) drops the vacuumed file from the next plan, so retrying succeeds once the
# handle reflects the version vacuum committed against. A file this names that is genuinely missing
# from a fresh snapshot is real corruption, not this race: the refreshed plan still names it, the
# retry fails the same way, and it still reaches error tracking once the retry budget is spent.
DELTA_MISSING_SCAN_FILE_NEEDLE = "Failed to fetch metadata for file"


def is_missing_scan_file_race(error: BaseException) -> bool:
    return (
        type(error) is deltalake.exceptions.DeltaError
        and DELTA_MISSING_SCAN_FILE_NEEDLE in str(error)
        and "not found" in str(error)
    )


def _is_too_many_open_files_error(error: BaseException) -> bool:
    """True if opening the app-DB connection failed because this worker is out of file descriptors.

    `update_sync_type_config_keys` (persisting the vacuum watermark) opens a fresh Django connection;
    its socket/selector setup raises a bare `OSError` — not a psycopg exception — when `socket()` hits
    EMFILE (this process's fd table is full) or ENFILE (the system-wide table is full), before libpq
    has anything to wrap into `OperationalError`. Same transient fd-pressure condition already handled
    for the source's own connect path (`postgres.py::_is_too_many_open_files_error`) and for
    `cdp_producer.py`'s own-DB check: a descriptor frees the moment another connection/handle in this
    worker closes, so it's never a customer or maintenance-logic problem.
    """
    return isinstance(error, OSError) and error.errno in (errno.EMFILE, errno.ENFILE)


def is_transient_maintenance_error(error: BaseException) -> bool:
    """Infra blips seen during delta maintenance that aren't a maintenance bug.

    Covers S3/object-store hiccups reaching our own data-warehouse bucket (see
    `is_transient_object_store_error` above), racy concurrent-maintenance DeltaErrors (see
    `is_transient_delta_maintenance_error` above), and app-DB connection blips (DNS, pooler drops, fd
    exhaustion) hit while resolving `job.folder_path()` or persisting the vacuum watermark on a pooled
    connection — the same `OperationalError`/`InterfaceError` classification used for this failure class
    in `repartition_table.py`'s `_is_transient_infra_error`, plus `_is_too_many_open_files_error` above
    for the fd-exhaustion variant that reaches here as a bare `OSError`.

    Also covers a primary-DB failover briefly routing the watermark's `select_for_update()` onto a
    connection that has become a read-only standby: Postgres raises `ReadOnlySqlTransaction`
    (SQLSTATE 25006) for that, which psycopg classifies under `InternalError` rather than
    `OperationalError`, so it needs its own check — a bare `InternalError` isinstance check would be
    too broad and swallow real corruption errors (e.g. `DataCorrupted`) that share the same base class.

    Also folds in an exhausted `ensure_bucket_exists` `HeadBucket` 403 (see
    `_is_exhausted_head_bucket_forbidden`) — safe here specifically because this function only backs
    the best-effort pre-extraction probe, which has no retry budget to bypass and already no-ops
    silently on any failure, transient or not.
    """
    if isinstance(error, OperationalError | InterfaceError):
        return True
    if isinstance(error, InternalError) and isinstance(error.__cause__, psycopg.errors.ReadOnlySqlTransaction):
        return True
    if _is_too_many_open_files_error(error):
        return True
    if _is_exhausted_head_bucket_forbidden(error):
        return True
    return is_transient_object_store_error(error) or is_transient_delta_maintenance_error(error)
