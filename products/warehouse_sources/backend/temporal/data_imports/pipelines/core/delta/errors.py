from django.db import InterfaceError, OperationalError

import botocore.exceptions
import deltalake.exceptions

# Substrings of the object-store errors raised talking to our own S3-backed data-warehouse bucket
# that are transient and self-recovering, not a bug in our code or a customer credential problem:
# - the first three come from delta-rs's Rust `object_store` crate inside `DeltaTable.is_deltatable()`
#   (IMDS/STS blips, dispatch timeouts)
# - "Please reduce your request rate" is S3's SlowDown throttling response, surfaced by s3fs/aiobotocore
#   when a bulk operation (e.g. `_purge_s3_prefix`'s list-then-delete) outruns the bucket's request-rate limit
# A retry (of the same idempotent operation) clears these, so they shouldn't be treated the same as a
# bug in our logic.
TRANSIENT_OBJECT_STORE_ERRORS = (
    "an error occurred while loading credentials",
    "the credential provider was not enabled",
    "Generic S3 error",
    "Please reduce your request rate",
)


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
    if isinstance(error, botocore.exceptions.NoCredentialsError):
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
TRANSIENT_DELTA_MAINTENANCE_ERRORS = ("Optimize selected-file scan failed",)


def is_transient_delta_maintenance_error(error: BaseException) -> bool:
    return isinstance(error, deltalake.exceptions.DeltaError) and any(
        needle in str(error) for needle in TRANSIENT_DELTA_MAINTENANCE_ERRORS
    )


def is_transient_maintenance_error(error: BaseException) -> bool:
    """Infra blips seen during delta maintenance that aren't a maintenance bug.

    Covers S3/object-store hiccups reaching our own data-warehouse bucket (see
    `is_transient_object_store_error` above), racy concurrent-maintenance DeltaErrors (see
    `is_transient_delta_maintenance_error` above), and app-DB connection blips (DNS, pooler drops) hit
    while resolving `job.folder_path()` on a pooled connection — the same `OperationalError`/`InterfaceError`
    classification used for this failure class in `repartition_table.py`'s `_is_transient_infra_error`.
    """
    if isinstance(error, OperationalError | InterfaceError):
        return True
    return is_transient_object_store_error(error) or is_transient_delta_maintenance_error(error)
