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
            # Other DeltaErrors are real failures (e.g. a genuinely corrupt log) and must still be captured.
            ("unrelated_delta_error", deltalake.exceptions.DeltaError("no protocol found in delta log"), False),
            # Same message shape but not the DeltaError type delta-rs actually raises for it.
            ("wrong_exception_type", RuntimeError("Optimize selected-file scan failed"), False),
        ]
    )
    def test_matches_only_the_racy_optimize_scan_signature(self, _name: str, error: Exception, expected: bool):
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
            ("genuine_bug", RuntimeError("maintenance blew up"), False),
        ]
    )
    def test_classifies_transient_errors(self, _name: str, error: Exception, expected: bool):
        assert is_transient_maintenance_error(error) is expected
