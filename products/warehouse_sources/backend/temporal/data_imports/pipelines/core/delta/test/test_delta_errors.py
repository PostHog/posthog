from django.db import InterfaceError, OperationalError

import deltalake
import botocore.exceptions
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (
    is_transient_delta_maintenance_error,
    is_transient_maintenance_error,
    is_transient_object_store_error,
)


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
                # s3fs/aiobotocore's own credential resolution (distinct from delta-rs's Rust
                # object_store crate) can raise this bare, unwrapped — same IMDS/STS blip
                # hitting our own instance-role-authenticated bucket, different client library.
                "bare_no_credentials_error",
                botocore.exceptions.NoCredentialsError(),
                True,
            ),
            ("unrelated_exception_type", ValueError("some other unrelated failure"), False),
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
            ("genuine_bug", RuntimeError("maintenance blew up"), False),
        ]
    )
    def test_classifies_transient_errors(self, _name: str, error: Exception, expected: bool):
        assert is_transient_maintenance_error(error) is expected
