from django.db import InterfaceError, InternalError, OperationalError

import deltalake
import psycopg.errors
import botocore.exceptions
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (
    TransientObjectStoreError,
    is_invalid_version_race,
    is_offset_overflow_compaction_error,
    is_transient_delta_maintenance_error,
    is_transient_maintenance_error,
    is_transient_object_store_error,
)


def _internal_error_with_cause(cause: BaseException) -> InternalError:
    """Mirrors how Django's DatabaseErrorWrapper re-raises a psycopg error: `raise dj_exc_value ... from exc_value`."""
    error = InternalError("cannot execute SELECT FOR UPDATE in a read-only transaction")
    error.__cause__ = cause
    return error


class TestIsTransientObjectStoreError:
    @parameterized.expand(
        [
            (
                "credential_provider_not_enabled_os_error",
                OSError(
                    "Operation not supported: the credential provider was not enabled: "
                    "no providers in chain provided credentials"
                ),
                True,
            ),
            ("unrelated_os_error", OSError("Permission denied: bucket policy forbids this operation"), False),
            (
                # s3fs wraps a CopyObject/PutObject 5xx as a plain OSError once boto's own retries
                # are exhausted - S3's fixed InternalError message, not a bug in our code.
                "s3_internal_error_os_error",
                OSError("[Errno 121] We encountered an internal error. Please try again."),
                True,
            ),
            (
                # s3fs/aiobotocore's own credential resolution (distinct from delta-rs's Rust
                # object_store crate) can raise this bare, unwrapped — same IMDS/STS blip
                # hitting our own instance-role-authenticated bucket, different client library.
                "bare_no_credentials_error",
                botocore.exceptions.NoCredentialsError(),
                True,
            ),
            ("unrelated_exception_type", ValueError("some other unrelated failure"), False),
            # `get_delta_table` re-raises a recognized transient blip as this wrapper (see
            # `_capture_unless_transient`) instead of the original OSError/DeltaError. A caller
            # further up the stack that catches broadly and re-runs this classifier on the caught
            # exception sees the wrapper, not the original — it must still read as transient.
            ("already_wrapped_transient_error", TransientObjectStoreError("Please reduce your request rate"), True),
        ]
    )
    def test_classifies_transient_errors(self, _name: str, error: Exception, expected: bool):
        assert is_transient_object_store_error(error) is expected


class TestIsTransientDeltaMaintenanceError:
    @parameterized.expand(
        [
            # A concurrent optimize/vacuum losing the race on a file scan: safe to skip and retry.
            (
                "optimize_scan_file_not_found",
                deltalake.exceptions.DeltaError(
                    "Failed to parse parquet: Optimize selected-file scan failed while scanning data: "
                    "Object at location .../part-0.parquet not found: 404 Not Found"
                ),
                True,
            ),
            # execute_with_conflict_retry already retries a CommitFailedError, but a still-running
            # concurrent maintenance pass can exhaust that budget too — same race, just losing at
            # commit time instead of during the scan. Covers all three delta-rs conflict-checker
            # variants that share this class of race.
            (
                "compact_commit_conflict_concurrent_delete_read",
                deltalake.exceptions.CommitFailedError(
                    "Commit failed: a concurrent transaction deleted data this operation read."
                ),
                True,
            ),
            (
                "vacuum_commit_conflict_concurrent_append",
                deltalake.exceptions.CommitFailedError("Commit failed: a concurrent transactions added new data."),
                True,
            ),
            (
                "commit_conflict_concurrent_delete_delete",
                deltalake.exceptions.CommitFailedError(
                    "Commit failed: a concurrent transaction deleted the same data your transaction deletes."
                ),
                True,
            ),
            # A commit failure from a metadata/protocol change isn't the same-pass race above — a
            # genuine conflict worth capturing, not silently retried away next pass.
            (
                "commit_conflict_metadata_changed",
                deltalake.exceptions.CommitFailedError("Metadata changed since last commit."),
                False,
            ),
            # A concurrent `reset_table` purging the whole table prefix (a full_refresh sync) out from
            # under a still-running maintenance pass takes `_delta_log` with it, so the vacuum reading
            # the commit history loses a log file mid-read: same race, safe to skip and retry.
            (
                "missing_delta_log_commit_file",
                deltalake.exceptions.DeltaError(
                    "Generic error: Kernel error: File not found: "
                    "dlt/team_1_source_2/table/_delta_log/00000000000000000001.json"
                ),
                True,
            ),
            # The same race can take a checkpoint instead of a commit JSON, surfaced through delta-rs's
            # Arrow/object_store kernel message shape (a plain 404/NoSuchKey GET failure) rather than the
            # older "File not found: ..." shape above — both mean the same thing when scoped to `_delta_log/`.
            (
                "missing_delta_log_checkpoint_object_store_kernel_message",
                deltalake.exceptions.DeltaError(
                    "Kernel error: Arrow error: External: Object at location "
                    "dlt/team_1_source_2/table/_delta_log/00000000000000000099.checkpoint.parquet not found: "
                    "Error performing GET https://s3.example.com/bucket/.../00000000000000000099.checkpoint.parquet "
                    "in 10.9ms - Server returned non-2xx status code: 404 Not Found: NoSuchKey"
                ),
                True,
            ),
            # "not found" outside the log directory must not match, because a data file missing for some
            # other reason is a real failure to capture, not this specific log-commit race.
            ("file_not_found_outside_delta_log", deltalake.exceptions.DeltaError("File not found: some/file"), False),
            # Other DeltaErrors are real failures (e.g. a genuinely corrupt log) and must still be captured.
            ("unrelated_delta_error", deltalake.exceptions.DeltaError("no protocol found in delta log"), False),
            # Same message shape but not the DeltaError type delta-rs actually raises for it.
            ("wrong_exception_type", RuntimeError("Optimize selected-file scan failed"), False),
        ]
    )
    def test_classifies_transient_delta_maintenance_errors(self, _name: str, error: Exception, expected: bool):
        assert is_transient_delta_maintenance_error(error) is expected


class TestIsTransientMaintenanceError:
    @parameterized.expand(
        [
            # A DNS/pooler blip hit while resolving `job.folder_path()` on a pooled app-DB
            # connection (e.g. inside `_get_delta_table_uri`) isn't a maintenance bug.
            ("dns_resolution_failure", OperationalError("[Errno -2] Name or service not known"), True),
            ("pooler_dropped_connection", InterfaceError("connection already closed"), True),
            # The object-store and concurrent-maintenance classifiers must stay folded in — vacuum()
            # and optimize.compact() surface both shapes through this single maintenance check.
            (
                "object_store_blip",
                OSError("Generic S3 error: Error getting list response body: operation timed out"),
                True,
            ),
            (
                "concurrent_maintenance_race",
                deltalake.exceptions.DeltaError("Optimize selected-file scan failed while scanning data"),
                True,
            ),
            # A commit-conflict retry budget exhausted by sustained contention from another
            # concurrent maintenance pass — see TestIsTransientDeltaMaintenanceError above.
            (
                "commit_conflict_retries_exhausted",
                deltalake.exceptions.CommitFailedError(
                    "Commit failed: a concurrent transaction deleted data this operation read."
                ),
                True,
            ),
            # A full_refresh `reset_table` purging `_delta_log` out from under a concurrent
            # vacuum. The maintenance call sites only consult this folded-in classifier, so the
            # signature has to reach them through here too.
            (
                "missing_delta_log_commit_file",
                deltalake.exceptions.DeltaError(
                    "Generic error: Kernel error: File not found: "
                    "dlt/team_1_source_2/table/_delta_log/00000000000000000001.json"
                ),
                True,
            ),
            ("genuine_bug", RuntimeError("maintenance blew up"), False),
            # A primary failover briefly turns the write connection into a read-only standby mid
            # watermark-persist — Postgres raises ReadOnlySqlTransaction (25006), which psycopg
            # classifies under InternalError rather than OperationalError.
            (
                "watermark_persist_during_failover",
                _internal_error_with_cause(
                    psycopg.errors.ReadOnlySqlTransaction("cannot execute SELECT FOR UPDATE in a read-only transaction")
                ),
                True,
            ),
            # Other InternalError subtypes (e.g. real corruption) must not be swept up by the
            # ReadOnlySqlTransaction check just because they share the same Django exception class.
            (
                "internal_error_unrelated_cause_not_matched",
                _internal_error_with_cause(psycopg.errors.DataCorrupted("index is corrupted")),
                False,
            ),
        ]
    )
    def test_classifies_transient_errors(self, _name: str, error: Exception, expected: bool):
        assert is_transient_maintenance_error(error) is expected


class TestIsInvalidVersionRace:
    @parameterized.expand(
        [
            # Two writers racing to commit the very first version of a brand-new table: the loser's
            # conflict check can't read back the winner's just-committed version 0 log entry.
            ("invalid_table_version_zero", deltalake.exceptions.DeltaError("Invalid table version: 0"), True),
            # The same race losing at a later version, not just table creation.
            ("invalid_table_version_nonzero", deltalake.exceptions.DeltaError("Invalid table version: 7"), True),
            # A distinct delta-rs error variant (`VersionDowngrade`, not `InvalidVersion`) with its own
            # message shape and a real bug to surface (a caller requesting an older version than
            # loaded) — must not be swept up by this race classifier.
            (
                "downgrade_error_not_matched",
                deltalake.exceptions.DeltaError("Cannot downgrade from version 5 to 2; use DeltaTable.load_version()"),
                False,
            ),
            ("unrelated_delta_error", deltalake.exceptions.DeltaError("no protocol found in delta log"), False),
            # `CommitFailedError` is a `DeltaError` subclass, but this classifier is deliberately exact-type
            # only — that variant already has its own dedicated handling via `CommitFailedError`.
            (
                "commit_failed_error_not_matched",
                deltalake.exceptions.CommitFailedError("Invalid table version: 0"),
                False,
            ),
            ("wrong_exception_type", RuntimeError("Invalid table version: 0"), False),
        ]
    )
    def test_classifies_invalid_version_race(self, _name: str, error: Exception, expected: bool):
        assert is_invalid_version_race(error) is expected


class TestIsOffsetOverflowCompactionError:
    @parameterized.expand(
        [
            # delta-rs's Rust task panicking mid-compaction, surfaced as a generic DeltaError
            # rather than a typed one — see errors.py for why binning already-safe files together
            # can still overflow a 32-bit string/binary column offset.
            (
                "byte_array_offset_overflow_panic",
                deltalake.exceptions.DeltaError(
                    'Generic error: task 1237385 panicked with message "byte array offset overflow"'
                ),
                True,
            ),
            ("unrelated_delta_error", deltalake.exceptions.DeltaError("no protocol found in delta log"), False),
            # Same message shape but not the DeltaError type delta-rs actually raises for it.
            ("wrong_exception_type", RuntimeError('panicked with message "byte array offset overflow"'), False),
        ]
    )
    def test_classifies_offset_overflow_errors(self, _name: str, error: Exception, expected: bool):
        assert is_offset_overflow_compaction_error(error) is expected
