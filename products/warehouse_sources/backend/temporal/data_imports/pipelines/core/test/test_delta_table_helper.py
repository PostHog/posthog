from typing import cast

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

import pyarrow as pa
import deltalake
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import realign_decimal_buffers
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (
    TransientObjectStoreError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta_table_helper import DeltaTableHelper

_HELPER_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta_table_helper"


def _decimal_array(values: list, *, precision: int = 10, scale: int = 2, misaligned: bool) -> pa.Array:
    """Build a Decimal128 array. When `misaligned`, its data buffer is 8-byte but NOT
    16-byte aligned — the exact FFI case delta-rs (arrow-rs) aborts the worker on.

    pyarrow's allocator always returns 64-byte-aligned memory, so the only way to
    reproduce the bad case is to over-allocate and slice off 8 bytes, mimicking what
    arrives across the Arrow C Data Interface from polars / external producers.
    """
    aligned = pa.array(values, type=pa.decimal128(precision, scale))
    if not misaligned:
        return aligned

    data_buffer = aligned.buffers()[1]
    assert data_buffer is not None
    padded = pa.allocate_buffer(data_buffer.size + 16)
    memoryview(padded)[8 : 8 + data_buffer.size] = memoryview(data_buffer)
    misaligned_buffer = padded.slice(8, data_buffer.size)
    assert misaligned_buffer.address % 16 == 8
    # The validity buffer is legitimately None here (no nulls).
    buffers: list[pa.Buffer | None] = [None, misaligned_buffer]
    return pa.Array.from_buffers(pa.decimal128(precision, scale), len(values), buffers)


def _table_is_misaligned(table: pa.Table) -> bool:
    return any(
        pa.types.is_decimal(table.field(i).type)
        and any((b := chunk.buffers()[1]) is not None and b.address % 16 for chunk in table.column(i).chunks)
        for i in range(table.num_columns)
    )


def _make_logger():
    logger = MagicMock()
    logger.adebug = AsyncMock()
    logger.ainfo = AsyncMock()
    logger.awarning = AsyncMock()
    logger.aerror = AsyncMock()
    return logger


@pytest.fixture
def helper():
    return DeltaTableHelper(resource_name="test_resource", job=MagicMock(), logger=_make_logger())


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
        helper = DeltaTableHelper(resource_name="t", job=MagicMock(), logger=_make_logger())

        with (
            override_settings(
                USE_LOCAL_SETUP=use_local_setup,
                DATA_WAREHOUSE_DELTA_S3_ALLOW_UNSAFE_RENAME=allow_unsafe,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta_table_helper.ensure_bucket_exists"
            ),
        ):
            options = helper.get_storage_options()

        assert options["conditional_put"] == "etag"
        assert ("AWS_S3_ALLOW_UNSAFE_RENAME" in options) is allow_unsafe


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
        helper = DeltaTableHelper(resource_name="t", job=MagicMock(), logger=_make_logger())
        delta_uri = "s3://bucket/team_id/job_id/t"

        s3 = MagicMock()
        s3_cm = MagicMock()
        s3_cm.__aenter__ = AsyncMock(return_value=s3)
        s3_cm.__aexit__ = AsyncMock(return_value=False)
        mock_aget_s3_client = MagicMock(return_value=s3_cm)

        module = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta_table_helper"
        with (
            patch.object(helper, "_get_delta_table_uri", AsyncMock(return_value=delta_uri)),
            patch(f"{module}.deltalake.DeltaTable") as mock_delta_table,
            patch(f"{module}.aget_s3_client", mock_aget_s3_client),
            patch(f"{module}._purge_s3_prefix", AsyncMock()) as mock_purge,
            patch(f"{module}.capture_exception"),
        ):
            mock_delta_table.is_deltatable.return_value = True
            mock_delta_table.side_effect = Exception(error_message)

            if expect_heal:
                result = await helper.get_delta_table()
                assert result is None
                assert helper.is_first_sync is True
                # Regression guard: a bare recursive `_rm` (instead of the enumerate-then-delete
                # `_purge_s3_prefix`) can leave `_delta_log` strays on S3-compatible stores and
                # recreate this exact corruption on the next sync.
                mock_purge.assert_awaited_once_with(s3, delta_uri)
                mock_aget_s3_client.assert_called_once_with(fresh_instance=True)
            else:
                with pytest.raises(Exception, match="something else went wrong"):
                    await helper.get_delta_table()
                mock_purge.assert_not_awaited()
                assert helper.is_first_sync is False

    @pytest.mark.asyncio
    async def test_open_failure_heals_even_if_prefix_already_gone(self):
        """A concurrent purge (e.g. a retried Temporal attempt) can already have cleared the
        prefix by the time this one runs `_purge_s3_prefix`, which surfaces as `FileNotFoundError`.
        That's still a successful heal, not a failure to propagate."""
        helper = DeltaTableHelper(resource_name="t", job=MagicMock(), logger=_make_logger())
        delta_uri = "s3://bucket/team_id/job_id/t"

        s3_cm = MagicMock()
        s3_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        s3_cm.__aexit__ = AsyncMock(return_value=False)

        module = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta_table_helper"
        with (
            patch.object(helper, "_get_delta_table_uri", AsyncMock(return_value=delta_uri)),
            patch(f"{module}.deltalake.DeltaTable") as mock_delta_table,
            patch(f"{module}.aget_s3_client", MagicMock(return_value=s3_cm)),
            patch(f"{module}._purge_s3_prefix", AsyncMock(side_effect=FileNotFoundError)),
            patch(f"{module}.capture_exception"),
        ):
            mock_delta_table.is_deltatable.return_value = True
            mock_delta_table.side_effect = Exception("Kernel error: No table metadata or protocol found in delta log.")

            result = await helper.get_delta_table()
            assert result is None
            assert helper.is_first_sync is True

    @pytest.mark.asyncio
    async def test_is_deltatable_failure_is_captured_and_reraised(self):
        """The `is_deltatable` existence check is a separate S3 call from the DeltaTable() open
        handled above, and callers span best-effort maintenance to the main write path, so a
        failure here can't be swallowed as "no table" (that would trip should_overwrite_table and
        wipe an existing table) — it must be captured for visibility and reraised."""
        helper = DeltaTableHelper(resource_name="t", job=MagicMock(), logger=_make_logger())
        delta_uri = "s3://bucket/team_id/job_id/t"

        module = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta_table_helper"
        with (
            patch.object(helper, "_get_delta_table_uri", AsyncMock(return_value=delta_uri)),
            patch(f"{module}.deltalake.DeltaTable") as mock_delta_table,
            patch(f"{module}.capture_exception") as mock_capture,
        ):
            mock_delta_table.is_deltatable.side_effect = OSError("Access Denied: not authorized to list bucket")

            with pytest.raises(OSError, match="Access Denied"):
                await helper.get_delta_table()

            mock_capture.assert_called_once()
            assert helper.is_first_sync is False

    @pytest.mark.asyncio
    async def test_is_deltatable_transient_error_is_not_captured_but_still_reraised(self):
        """A known-transient object-store blip (e.g. an S3 LIST request timing out) must not be
        reported to error tracking as a defect — it's a self-recovering network hiccup, not a bug.
        It must still propagate (as TransientObjectStoreError, not the raw OSError) so Temporal's
        activity retry policy retries the sync. Wrapping matters, not just suppressing the inline
        capture_exception call here: a bare OSError would still reach the activity interceptor
        (posthog_client.py), which reports any uncaught activity exception that isn't a
        NonReportableError, minting a fresh error-tracking issue per blip anyway."""
        helper = DeltaTableHelper(resource_name="t", job=MagicMock(), logger=_make_logger())
        delta_uri = "s3://bucket/team_id/job_id/t"

        module = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta_table_helper"
        original_error = OSError(
            "Generic S3 error\nError getting list response body\nHTTP error\n"
            "request or response body error\noperation timed out"
        )
        with (
            patch.object(helper, "_get_delta_table_uri", AsyncMock(return_value=delta_uri)),
            patch(f"{module}.deltalake.DeltaTable") as mock_delta_table,
            patch(f"{module}.capture_exception") as mock_capture,
        ):
            mock_delta_table.is_deltatable.side_effect = original_error

            with pytest.raises(TransientObjectStoreError, match="operation timed out") as exc_info:
                await helper.get_delta_table()

            assert exc_info.value.__cause__ is original_error
            mock_capture.assert_not_called()
            cast(AsyncMock, helper._logger.awarning).assert_awaited_once()
            assert helper.is_first_sync is False


def _make_local_helper(delta_uri: str) -> DeltaTableHelper:
    """DeltaTableHelper that reads/writes a local filesystem path instead of S3."""
    helper = DeltaTableHelper(resource_name="test", job=MagicMock(), logger=_make_logger())
    patch.object(helper, "_get_delta_table_uri", new=AsyncMock(return_value=delta_uri)).start()
    patch.object(helper, "_get_credentials", new=MagicMock(return_value={})).start()
    helper.get_delta_table.cache_clear()
    return helper


class TestRealignDecimalBuffers:
    """delta-rs aborts the worker on 8-byte-aligned Decimal128 buffers; we realign them
    to pyarrow's 64-byte allocator before any Delta write. See delta-io/delta-rs#3884."""

    def test_misaligned_decimal_is_realigned(self) -> None:
        table = pa.table({"amount": _decimal_array([1, 2, 3, 4], misaligned=True), "id": pa.array([1, 2, 3, 4])})
        assert _table_is_misaligned(table) is True

        result = realign_decimal_buffers(table)

        assert _table_is_misaligned(result) is False
        # Values and schema are preserved exactly
        assert result.column("amount").to_pylist() == table.column("amount").to_pylist()
        assert result.column("id").to_pylist() == [1, 2, 3, 4]
        assert result.schema == table.schema

    @pytest.mark.parametrize(
        "table",
        [
            pa.table({"amount": _decimal_array([1, 2, 3], misaligned=False), "id": pa.array([1, 2, 3])}),
            pa.table({"id": pa.array([1, 2, 3]), "name": pa.array(["a", "b", "c"])}),
        ],
        ids=["already_aligned_decimal", "no_decimal_columns"],
    )
    def test_unmisaligned_table_is_returned_unchanged(self, table: pa.Table) -> None:
        assert _table_is_misaligned(table) is False

        result = realign_decimal_buffers(table)

        # No misalignment found → identity return (no needless copy)
        assert result is table

    def test_only_misaligned_columns_are_rebuilt(self) -> None:
        aligned_dec = _decimal_array([10, 20], misaligned=False)
        misaligned_dec = _decimal_array([30, 40], misaligned=True)
        table = pa.table({"good": aligned_dec, "bad": misaligned_dec, "id": pa.array([1, 2])})

        result = realign_decimal_buffers(table)

        assert _table_is_misaligned(result) is False
        assert result.column("good").to_pylist() == [10, 20]
        assert result.column("bad").to_pylist() == [30, 40]
        # The already-aligned column keeps its original buffer (rebuilt only what was broken)
        good_buffer = result.column("good").chunks[0].buffers()[1]
        orig_buffer = aligned_dec.buffers()[1]
        assert good_buffer is not None and orig_buffer is not None
        assert good_buffer.address == orig_buffer.address

    def test_multi_chunk_misaligned_column(self) -> None:
        # The arrays already carry decimal128(10, 2); an explicit type= doesn't match any
        # pyarrow-stubs chunked_array overload for decimal types.
        chunked = pa.chunked_array(
            [_decimal_array([1, 2], misaligned=True), _decimal_array([3, 4], misaligned=True)],
        )
        table = pa.table({"amount": chunked, "id": pa.array([1, 2, 3, 4])})
        assert _table_is_misaligned(table) is True

        result = realign_decimal_buffers(table)

        assert _table_is_misaligned(result) is False
        assert result.column("amount").to_pylist() == [1, 2, 3, 4]

    def test_empty_decimal_table(self) -> None:
        table = pa.table({"amount": pa.array([], type=pa.decimal128(10, 2)), "id": pa.array([], type=pa.int64())})

        result = realign_decimal_buffers(table)

        assert result.num_rows == 0
        assert result.schema == table.schema


class TestIsTableCorrupted:
    _MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta_table_helper"

    def _helper(self) -> DeltaTableHelper:
        return DeltaTableHelper("t", MagicMock(), MagicMock(adebug=AsyncMock()), False)

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
        ]
    )
    @pytest.mark.asyncio
    async def test_is_table_corrupted(self, _name: str, is_delta: bool, open_exc: Exception | None, expected: bool):
        helper = self._helper()
        with (
            patch.object(helper, "_get_delta_table_uri", new=AsyncMock(return_value="s3://b/t")),
            patch.object(helper, "_get_credentials", return_value={}),
            patch(f"{self._MODULE}.deltalake.DeltaTable") as mock_dt,
        ):
            mock_dt.is_deltatable = MagicMock(return_value=is_delta)
            if open_exc is not None:
                mock_dt.side_effect = open_exc
            result = await helper.is_table_corrupted()

        assert result is expected
