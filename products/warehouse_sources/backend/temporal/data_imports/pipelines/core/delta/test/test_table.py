from typing import cast

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

import deltalake
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (
    TransientObjectStoreError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import (
    _PURGE_S3_PREFIX_MAX_ATTEMPTS,
    DeltaTableRef,
    _purge_s3_prefix,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.test.helpers import make_logger


def table_ref():
    return DeltaTableRef(resource_name="test_resource", job=MagicMock(), logger=make_logger())


class TestStorageOptionsCommitSafety:
    # Re-adding AWS_S3_ALLOW_UNSAFE_RENAME unconditionally would silently restore
    # the legacy rename backend, which has no commit-conflict detection.
    @parameterized.expand(
        [
            ("production_default_safe", False, False),
            ("production_rollback_escape_hatch", False, True),
            ("local_default_safe", True, False),
        ]
    )
    def test_conditional_put_on_unsafe_rename_gated(
        self, _case: str, use_local_setup: bool, allow_unsafe: bool
    ) -> None:
        table_ref = DeltaTableRef(resource_name="t", job=MagicMock(), logger=make_logger())

        with (
            override_settings(
                USE_LOCAL_SETUP=use_local_setup,
                DATA_WAREHOUSE_DELTA_S3_ALLOW_UNSAFE_RENAME=allow_unsafe,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table.ensure_bucket_exists"
            ),
        ):
            options = table_ref.get_storage_options()

        assert options["conditional_put"] == "etag"
        assert ("AWS_S3_ALLOW_UNSAFE_RENAME" in options) is allow_unsafe

    # The proxy bypass and the commit-safety options are assembled in the same dict; dropping either
    # while editing the other is silent (S3 traffic quietly returns to the egress proxy, or commits
    # lose conflict detection).
    def test_proxy_bypass_options_merge_with_commit_safety(self) -> None:
        table_ref = DeltaTableRef(resource_name="t", job=MagicMock(), logger=make_logger())

        # Patch the facade seam get_storage_options calls, so this stays a merge-point test and does
        # not reach into another product's internals. What the bypass dict itself contains is covered
        # by products/data_warehouse/backend/tests/test_s3_proxy.py.
        proxy_options = {
            "proxy_url": "http://egress-proxy.test:4750",
            "proxy_excludes": "posthog-s3-datawarehouse-us-east-1.s3.us-east-1.amazonaws.com",
            "AWS_S3_ADDRESSING_STYLE": "virtual",
            "virtual_hosted_style_request": "true",
        }
        with (
            override_settings(USE_LOCAL_SETUP=False),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table.delta_proxy_storage_options",
                return_value=proxy_options,
            ),
        ):
            options = table_ref.get_storage_options()

        assert options["conditional_put"] == "etag"
        assert options["proxy_excludes"] == "posthog-s3-datawarehouse-us-east-1.s3.us-east-1.amazonaws.com"


class TestGetDeltaTableUnrecoverableErrors:
    # (case_name, error_message, expect_heal) — heal = wipe the table and fall back to first-sync mode
    _ERROR_CASES: list[tuple[str, str, bool]] = [
        (
            "orphaned_delta_log",
            "Kernel error: No table metadata or protocol found in delta log.",
            True,
        ),
        (
            "empty_log_segment",
            "Generic delta kernel error: No files in log segment",
            True,
        ),
        ("bugged_decimal_data", "parse decimal overflow at column x", True),
        ("other_errors_reraise", "Generic DeltaTable error: something else went wrong", False),
    ]

    @parameterized.expand(_ERROR_CASES)
    @pytest.mark.asyncio
    async def test_open_failure_handling(self, _name: str, error_message: str, expect_heal: bool):
        table_ref = DeltaTableRef(resource_name="t", job=MagicMock(), logger=make_logger())
        delta_uri = "s3://bucket/team_id/job_id/t"

        s3 = MagicMock()
        s3_cm = MagicMock()
        s3_cm.__aenter__ = AsyncMock(return_value=s3)
        s3_cm.__aexit__ = AsyncMock(return_value=False)
        mock_aget_s3_client = MagicMock(return_value=s3_cm)

        module = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table"
        with (
            patch.object(table_ref, "_get_delta_table_uri", AsyncMock(return_value=delta_uri)),
            patch(f"{module}.deltalake.DeltaTable") as mock_delta_table,
            patch(f"{module}.aget_s3_client", mock_aget_s3_client),
            patch(f"{module}._purge_s3_prefix", AsyncMock()) as mock_purge,
            patch(f"{module}.capture_exception"),
        ):
            mock_delta_table.is_deltatable.return_value = True
            mock_delta_table.side_effect = Exception(error_message)

            if expect_heal:
                result = await table_ref.get_delta_table()
                assert result is None
                assert table_ref.is_first_sync is True
                # Regression guard: a bare recursive `_rm` (instead of the enumerate-then-delete
                # `_purge_s3_prefix`) can leave `_delta_log` strays on S3-compatible stores and
                # recreate this exact corruption on the next sync.
                mock_purge.assert_awaited_once_with(s3, delta_uri)
                mock_aget_s3_client.assert_called_once_with(fresh_instance=True)
            else:
                with pytest.raises(Exception, match="something else went wrong"):
                    await table_ref.get_delta_table()
                mock_purge.assert_not_awaited()
                assert table_ref.is_first_sync is False

    @pytest.mark.asyncio
    async def test_open_failure_heals_even_if_prefix_already_gone(self):
        """A concurrent purge (e.g. a retried Temporal attempt) can already have cleared the
        prefix by the time this one runs `_purge_s3_prefix`, which surfaces as `FileNotFoundError`.
        That's still a successful heal, not a failure to propagate."""
        table_ref = DeltaTableRef(resource_name="t", job=MagicMock(), logger=make_logger())
        delta_uri = "s3://bucket/team_id/job_id/t"

        s3_cm = MagicMock()
        s3_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        s3_cm.__aexit__ = AsyncMock(return_value=False)

        module = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table"
        with (
            patch.object(table_ref, "_get_delta_table_uri", AsyncMock(return_value=delta_uri)),
            patch(f"{module}.deltalake.DeltaTable") as mock_delta_table,
            patch(f"{module}.aget_s3_client", MagicMock(return_value=s3_cm)),
            patch(f"{module}._purge_s3_prefix", AsyncMock(side_effect=FileNotFoundError)),
            patch(f"{module}.capture_exception"),
        ):
            mock_delta_table.is_deltatable.return_value = True
            mock_delta_table.side_effect = Exception("Kernel error: No table metadata or protocol found in delta log.")

            result = await table_ref.get_delta_table()
            assert result is None
            assert table_ref.is_first_sync is True

    @pytest.mark.asyncio
    async def test_is_deltatable_failure_is_captured_and_reraised(self):
        """The `is_deltatable` existence check is a separate S3 call from the DeltaTable() open
        handled above, and callers span best-effort maintenance to the main write path, so a
        failure here can't be swallowed as "no table" (that would trip should_overwrite_table and
        wipe an existing table) — it must be captured for visibility and reraised."""
        table_ref = DeltaTableRef(resource_name="t", job=MagicMock(), logger=make_logger())
        delta_uri = "s3://bucket/team_id/job_id/t"

        module = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table"
        with (
            patch.object(table_ref, "_get_delta_table_uri", AsyncMock(return_value=delta_uri)),
            patch(f"{module}.deltalake.DeltaTable") as mock_delta_table,
            patch(f"{module}.capture_exception") as mock_capture,
        ):
            mock_delta_table.is_deltatable.side_effect = OSError("Access Denied: not authorized to list bucket")

            with pytest.raises(OSError, match="Access Denied"):
                await table_ref.get_delta_table()

            mock_capture.assert_called_once()
            assert table_ref.is_first_sync is False

    @pytest.mark.asyncio
    async def test_is_deltatable_transient_error_is_not_captured_but_still_reraised(self):
        """A known-transient object-store blip (e.g. an S3 LIST request timing out) must not be
        reported to error tracking as a defect — it's a self-recovering network hiccup, not a bug.
        It must still propagate (as TransientObjectStoreError, not the raw OSError) so Temporal's
        activity retry policy retries the sync. Wrapping matters, not just suppressing the inline
        capture_exception call here: a bare OSError would still reach the activity interceptor
        (posthog_client.py), which reports any uncaught activity exception that isn't a
        NonReportableError, minting a fresh error-tracking issue per blip anyway."""
        table_ref = DeltaTableRef(resource_name="t", job=MagicMock(), logger=make_logger())
        delta_uri = "s3://bucket/team_id/job_id/t"

        original_error = OSError(
            "Generic S3 error\nError getting list response body\nHTTP error\n"
            "request or response body error\noperation timed out"
        )
        module = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table"
        with (
            patch.object(table_ref, "_get_delta_table_uri", AsyncMock(return_value=delta_uri)),
            patch(f"{module}.deltalake.DeltaTable") as mock_delta_table,
            patch(f"{module}.capture_exception") as mock_capture,
        ):
            mock_delta_table.is_deltatable.side_effect = original_error

            with pytest.raises(TransientObjectStoreError, match="operation timed out") as exc_info:
                await table_ref.get_delta_table()

            assert exc_info.value.__cause__ is original_error
            mock_capture.assert_not_called()
            cast(AsyncMock, table_ref._logger.awarning).assert_awaited_once()
            assert table_ref.is_first_sync is False

    @pytest.mark.asyncio
    async def test_open_transient_delta_log_race_is_not_captured_but_still_reraised(self):
        """A concurrent `reset_table` purge (a full_refresh sync, or this same open racing another
        attempt) can take a `_delta_log` checkpoint file out from under this open between `_last_checkpoint`
        pointing to it and delta-rs fetching it, surfacing as a DeltaError for a missing checkpoint object
        (see is_transient_delta_maintenance_error). That's not table corruption, so it must not be
        captured or trigger the unrecoverable-table wipe — it must propagate as TransientObjectStoreError
        so Temporal retries the sync."""
        table_ref = DeltaTableRef(resource_name="t", job=MagicMock(), logger=make_logger())
        delta_uri = "s3://bucket/team_id/job_id/t"

        checkpoint_race_error = deltalake.exceptions.DeltaError(
            "Kernel error: Arrow error: External: Object at location "
            "dlt/team_1_source_2/table/_delta_log/00000000000000000099.checkpoint.parquet not found: "
            "Error performing GET https://s3.example.com/... - Server returned non-2xx status code: "
            "404 Not Found: NoSuchKey"
        )
        module = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table"
        with (
            patch.object(table_ref, "_get_delta_table_uri", AsyncMock(return_value=delta_uri)),
            patch(f"{module}.deltalake.DeltaTable") as mock_delta_table,
            patch(f"{module}._purge_s3_prefix", AsyncMock()) as mock_purge,
            patch(f"{module}.capture_exception") as mock_capture,
        ):
            mock_delta_table.is_deltatable.return_value = True
            mock_delta_table.side_effect = checkpoint_race_error

            with pytest.raises(TransientObjectStoreError):
                await table_ref.get_delta_table()

            mock_capture.assert_not_called()
            mock_purge.assert_not_awaited()
            assert table_ref.is_first_sync is False


class TestIsTableCorrupted:
    _MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table"

    def _table_ref(self) -> DeltaTableRef:
        return DeltaTableRef("t", MagicMock(), MagicMock(adebug=AsyncMock()), False)

    @parameterized.expand(
        [
            # (is_deltatable, open_exception, expected_corrupt) — only DeltaError/FileNotFoundError on a
            # table whose _delta_log exists count as corrupt; a missing table or an unknown error must NOT,
            # so we never trigger a destructive revive on a non-existent table or a transient failure.
            ("not_a_delta_table", False, None, False),
            ("opens_fine", True, None, False),
            ("delta_error_is_corrupt", True, deltalake.exceptions.DeltaError("no protocol"), True),
            ("file_not_found_is_corrupt", True, FileNotFoundError("missing data file"), True),
            ("unknown_error_not_corrupt", True, ValueError("transient"), False),
            # A concurrent purge racing this same open (see is_transient_delta_maintenance_error) is a
            # DeltaError too, but must not read as corrupt — that would trigger a needless destructive
            # revive (full non-billable resync) for what a plain retry would have resolved on its own.
            (
                "transient_delta_log_race_not_corrupt",
                True,
                deltalake.exceptions.DeltaError(
                    "Kernel error: Arrow error: External: Object at location "
                    "dlt/team_1_source_2/table/_delta_log/00000000000000000099.checkpoint.parquet not found: "
                    "Error performing GET https://s3.example.com/... - Server returned non-2xx status code: "
                    "404 Not Found: NoSuchKey"
                ),
                False,
            ),
        ]
    )
    @pytest.mark.asyncio
    async def test_is_table_corrupted(self, _name: str, is_delta: bool, open_exc: Exception | None, expected: bool):
        table_ref = self._table_ref()
        with (
            patch.object(table_ref, "_get_delta_table_uri", new=AsyncMock(return_value="s3://b/t")),
            patch.object(table_ref, "_get_credentials", return_value={}),
            patch(f"{self._MODULE}.deltalake.DeltaTable") as mock_dt,
        ):
            mock_dt.is_deltatable = MagicMock(return_value=is_delta)
            if open_exc is not None:
                mock_dt.side_effect = open_exc
            result = await table_ref.is_table_corrupted()

        assert result is expected


class TestPurgeS3PrefixRetriesPermissionError:
    _MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table"

    # A HeadObject 403 never carries the underlying S3 error code in its body (AWS omits it for HEAD
    # requests), so a fresh client's brief IMDS/STS credential-resolution race surfaces identically to a
    # genuine permission problem: a bare PermissionError("Forbidden"). Before this fix, `_purge_s3_prefix`
    # only retried the needles in `is_transient_object_store_error` and raised immediately on any
    # PermissionError, failing the whole sync for what was actually a transient, self-healing race.
    @pytest.mark.asyncio
    async def test_retries_permission_error_and_succeeds_once_it_clears(self):
        with (
            patch(
                f"{self._MODULE}._purge_s3_prefix_once",
                new=AsyncMock(side_effect=[PermissionError("Forbidden"), None]),
            ) as mock_once,
            patch(f"{self._MODULE}.asyncio.sleep", new=AsyncMock()),
        ):
            await _purge_s3_prefix(MagicMock(), "s3://bucket/prefix")

        assert mock_once.await_count == 2

    @pytest.mark.asyncio
    async def test_gives_up_after_max_attempts_on_persistent_permission_error(self):
        with (
            patch(
                f"{self._MODULE}._purge_s3_prefix_once",
                new=AsyncMock(side_effect=PermissionError("Forbidden")),
            ) as mock_once,
            patch(f"{self._MODULE}.asyncio.sleep", new=AsyncMock()),
        ):
            with pytest.raises(PermissionError):
                await _purge_s3_prefix(MagicMock(), "s3://bucket/prefix")

        assert mock_once.await_count == _PURGE_S3_PREFIX_MAX_ATTEMPTS
