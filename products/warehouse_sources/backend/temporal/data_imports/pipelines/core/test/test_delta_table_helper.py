import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

import pyarrow as pa
import deltalake
import pyarrow.compute as pc
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    SchemaColumnTypeChangedException,
    evolve_pyarrow_schema,
    first_per_pk_table,
    realign_decimal_buffers,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.maintenance import DeltaMaintenance
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta_table_helper import (
    DeltaTableHelper,
    _deltalite_write_stats,
    _merge_predicate_ops,
)

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


_COMMIT_LAYOUT_CASES: list[tuple[str, list[dict], dict, bool]] = [
    # nested dict layout (older delta-rs / fallback form)
    (
        "nested_dict_exact_match",
        [{"userMetadata": {"run_uuid": "abc", "batch_index": "0"}}],
        {"run_uuid": "abc", "batch_index": "0"},
        True,
    ),
    # delta-rs 1.x flat layout: custom_metadata entries inlined onto the commit dict
    (
        "flat_inlined_exact_match",
        [{"operation": "WRITE", "timestamp": 1, "run_uuid": "abc", "batch_index": "0", "version": 1}],
        {"run_uuid": "abc", "batch_index": "0"},
        True,
    ),
    (
        "flat_missing_one_required_key",
        [{"operation": "WRITE", "run_uuid": "abc", "version": 1}],
        {"run_uuid": "abc", "batch_index": "0"},
        False,
    ),
    # nested JSON-string layout (some delta-rs versions serialize userMetadata as JSON)
    (
        "nested_json_string_exact_match",
        [{"userMetadata": json.dumps({"run_uuid": "abc", "batch_index": "0"})}],
        {"run_uuid": "abc", "batch_index": "0"},
        True,
    ),
    # match is a subset of the metadata — should still match
    (
        "match_is_subset",
        [{"userMetadata": {"run_uuid": "abc", "batch_index": "0", "extra": "field"}}],
        {"run_uuid": "abc"},
        True,
    ),
    # multiple commits, none matching
    (
        "no_match_in_history",
        [
            {"userMetadata": {"run_uuid": "other", "batch_index": "9"}},
            {"userMetadata": {"run_uuid": "abc", "batch_index": "1"}},
        ],
        {"run_uuid": "abc", "batch_index": "0"},
        False,
    ),
    # commits without any custom metadata at all
    (
        "no_metadata_on_any_commit",
        [{"operation": "WRITE"}, {}],
        {"run_uuid": "abc"},
        False,
    ),
    # one commit has invalid JSON userMetadata, the next is a valid match — still found
    (
        "invalid_json_string_skipped_then_match",
        [
            {"userMetadata": "not-valid-json{"},
            {"userMetadata": {"run_uuid": "abc"}},
        ],
        {"run_uuid": "abc"},
        True,
    ),
]


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


class TestHasCommitWithMetadata:
    @pytest.mark.asyncio
    async def test_returns_false_when_no_delta_table(self, helper: DeltaTableHelper):
        with patch.object(helper, "get_delta_table", AsyncMock(return_value=None)):
            assert await helper.has_commit_with_metadata({"run_uuid": "abc", "batch_index": "0"}) is False

    @parameterized.expand(
        [(name, history, match, expected) for (name, history, match, expected) in _COMMIT_LAYOUT_CASES]
    )
    @pytest.mark.asyncio
    async def test_layout(self, _name: str, history: list[dict], match: dict, expected: bool):
        helper = DeltaTableHelper(resource_name="t", job=MagicMock(), logger=_make_logger())
        mock_delta = MagicMock()
        mock_delta.history = MagicMock(return_value=history)

        with patch.object(helper, "get_delta_table", AsyncMock(return_value=mock_delta)):
            assert await helper.has_commit_with_metadata(match) is expected

    @pytest.mark.asyncio
    async def test_scan_limit_passed_to_history(self, helper: DeltaTableHelper):
        mock_delta = MagicMock()
        mock_delta.history = MagicMock(return_value=[])

        with patch.object(helper, "get_delta_table", AsyncMock(return_value=mock_delta)):
            await helper.has_commit_with_metadata({"k": "v"}, scan_limit=123)

        mock_delta.history.assert_called_once_with(limit=123)


class TestHasBatchBeenCommitted:
    @parameterized.expand(
        [
            ("string_run_uuid_int_batch", "run-123", 5, True),
            ("zero_batch_index", "run-1", 0, False),
        ]
    )
    @pytest.mark.asyncio
    async def test_wraps_has_commit_with_metadata(
        self, _name: str, run_uuid: str, batch_index: int, mocked_return: bool
    ):
        helper = DeltaTableHelper(resource_name="t", job=MagicMock(), logger=_make_logger())
        with patch.object(helper, "has_commit_with_metadata", AsyncMock(return_value=mocked_return)) as m:
            result = await helper.has_batch_been_committed(run_uuid, batch_index)

            assert result is mocked_return
            m.assert_called_once_with({"run_uuid": run_uuid, "batch_index": str(batch_index)})


class TestGetDeltaTableUnrecoverableErrors:
    # (case_name, error_message, expect_heal) — heal = wipe the table and fall back to first-sync mode
    _ERROR_CASES: list[tuple[str, str, bool]] = [
        (
            "orphaned_delta_log",
            "Kernel error: No table metadata or protocol found in delta log.",
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
        s3._rm = AsyncMock()
        s3_cm = MagicMock()
        s3_cm.__aenter__ = AsyncMock(return_value=s3)
        s3_cm.__aexit__ = AsyncMock(return_value=False)

        module = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta_table_helper"
        with (
            patch.object(helper, "_get_delta_table_uri", AsyncMock(return_value=delta_uri)),
            patch(f"{module}.deltalake.DeltaTable") as mock_delta_table,
            patch(f"{module}.aget_s3_client", MagicMock(return_value=s3_cm)),
            patch(f"{module}.capture_exception"),
        ):
            mock_delta_table.is_deltatable.return_value = True
            mock_delta_table.side_effect = Exception(error_message)

            if expect_heal:
                result = await helper.get_delta_table()
                assert result is None
                assert helper.is_first_sync is True
                s3._rm.assert_awaited_once_with(delta_uri, recursive=True)
            else:
                with pytest.raises(Exception, match="something else went wrong"):
                    await helper.get_delta_table()
                s3._rm.assert_not_awaited()
                assert helper.is_first_sync is False

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
        reported to error tracking as a defect — it's a self-recovering network hiccup, not a bug —
        but it must still propagate so Temporal's activity retry policy retries the sync."""
        helper = DeltaTableHelper(resource_name="t", job=MagicMock(), logger=_make_logger())
        delta_uri = "s3://bucket/team_id/job_id/t"

        module = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta_table_helper"
        with (
            patch.object(helper, "_get_delta_table_uri", AsyncMock(return_value=delta_uri)),
            patch(f"{module}.deltalake.DeltaTable") as mock_delta_table,
            patch(f"{module}.capture_exception") as mock_capture,
        ):
            mock_delta_table.is_deltatable.side_effect = OSError(
                "Generic S3 error\nError getting list response body\nHTTP error\n"
                "request or response body error\noperation timed out"
            )

            with pytest.raises(OSError, match="operation timed out"):
                await helper.get_delta_table()

            mock_capture.assert_not_called()
            cast(AsyncMock, helper._logger.awarning).assert_awaited_once()
            assert helper.is_first_sync is False


class TestWriteToDeltalakeCommitMetadataPassThrough:
    """Covers that commit_metadata is forwarded to deltalake.write_deltalake as CommitProperties."""

    @parameterized.expand(
        [
            ("no_metadata", None, None),
            ("with_metadata", {"run_uuid": "abc", "batch_index": "2"}, {"run_uuid": "abc", "batch_index": "2"}),
        ]
    )
    @pytest.mark.asyncio
    async def test_full_refresh_passes_commit_properties(
        self,
        _name: str,
        commit_metadata: dict[str, str] | None,
        expected_custom_metadata: dict[str, str] | None,
    ):
        import pyarrow as pa

        helper = DeltaTableHelper(resource_name="t", job=MagicMock(), logger=_make_logger())
        data = pa.table({"id": [1, 2, 3]})
        mock_delta = MagicMock()
        mock_delta.schema = MagicMock(return_value=MagicMock(to_arrow=MagicMock(return_value=data.schema)))

        with (
            patch.object(helper, "get_delta_table", AsyncMock(return_value=mock_delta)),
            patch(f"{_HELPER_MODULE}.evolve_delta_schema", AsyncMock(return_value=mock_delta)),
            patch("deltalake.write_deltalake") as mock_write,
        ):
            await helper.write_to_deltalake(
                data=data,
                write_type="full_refresh",
                should_overwrite_table=False,
                primary_keys=None,
                commit_metadata=commit_metadata,
            )

            assert mock_write.called
            _, kwargs = mock_write.call_args
            commit_properties = kwargs["commit_properties"]
            if expected_custom_metadata is None:
                assert commit_properties is None
            else:
                assert isinstance(commit_properties, deltalake.CommitProperties)
                assert commit_properties.custom_metadata == expected_custom_metadata


def _create_legacy_delta_table(path: str, *, partitioned: bool = False) -> deltalake.DeltaTable:
    """Seed a Delta table that mimics what the old dlt pipeline created:
    business columns plus NOT NULL _dlt_id and _dlt_load_id."""
    fields: list[pa.Field] = [
        pa.field("id", pa.int64()),
        pa.field("name", pa.string()),
        pa.field("_dlt_id", pa.string(), nullable=False),
        pa.field("_dlt_load_id", pa.string(), nullable=False),
    ]
    if partitioned:
        fields.append(pa.field(PARTITION_KEY, pa.string()))

    data_dict: dict[str, Any] = {
        "id": pa.array([1, 2]),
        "name": pa.array(["a", "b"]),
        "_dlt_id": pa.array(["id1", "id2"]),
        "_dlt_load_id": pa.array(["load1", "load1"]),
    }
    if partitioned:
        data_dict[PARTITION_KEY] = pa.array(["p0", "p0"])

    table = pa.table(data_dict, schema=pa.schema(fields))
    deltalake.write_deltalake(path, table, partition_by=PARTITION_KEY if partitioned else None)
    return deltalake.DeltaTable(path)


def _v3_batch(*, partitioned: bool = False) -> pa.Table:
    """Build an incoming batch the way pipeline_v3 does: no _dlt_* columns."""
    data_dict: dict[str, Any] = {"id": pa.array([3, 4]), "name": pa.array(["c", "d"])}
    if partitioned:
        data_dict[PARTITION_KEY] = pa.array(["p0", "p0"])
    return pa.table(data_dict)


def _make_local_helper(delta_uri: str) -> DeltaTableHelper:
    """DeltaTableHelper that reads/writes a local filesystem path instead of S3."""
    helper = DeltaTableHelper(resource_name="test", job=MagicMock(), logger=_make_logger())
    patch.object(helper, "_get_delta_table_uri", new=AsyncMock(return_value=delta_uri)).start()
    patch.object(helper, "_get_credentials", new=MagicMock(return_value={})).start()
    helper.get_delta_table.cache_clear()
    return helper


class TestLegacyDltTableReconciliation:
    """Pipeline_v3 must handle dlt-created Delta tables with NOT NULL _dlt_* columns."""

    def test_raw_merge_rejects_missing_non_nullable_columns(self, tmp_path: Path) -> None:
        """Baseline: proves delta-rs rejects merges when non-nullable columns are absent
        from the source batch. This is the root cause of the production failures."""
        delta_path = str(tmp_path / "table")
        _create_legacy_delta_table(delta_path)
        batch = _v3_batch()
        dt = deltalake.DeltaTable(delta_path)

        with pytest.raises(Exception, match="(?i)(invalid data|non-nullable|validation|not found)"):
            dt.merge(
                source=batch,
                source_alias="source",
                target_alias="target",
                predicate="source.id = target.id",
            ).when_matched_update_all().when_not_matched_insert_all().execute()

    @pytest.mark.parametrize("partitioned", [False, True], ids=["flat", "partitioned"])
    @pytest.mark.asyncio
    async def test_incremental_merge_into_legacy_table(self, partitioned: bool, tmp_path: Path) -> None:
        delta_path = str(tmp_path / "table")
        dt = _create_legacy_delta_table(delta_path, partitioned=partitioned)

        helper = _make_local_helper(delta_path)
        batch = evolve_pyarrow_schema(_v3_batch(partitioned=partitioned), dt.schema())

        result = await helper.write_to_deltalake(
            data=batch,
            write_type="incremental",
            should_overwrite_table=False,
            primary_keys=["id"],
        )

        final = result.to_pyarrow_table()
        assert final.num_rows == 4
        assert set(final.column("id").to_pylist()) == {1, 2, 3, 4}

        new_rows = final.filter(pc.is_in(final.column("id"), value_set=pa.array([3, 4])))
        assert all(v == "" for v in new_rows.column("_dlt_id").to_pylist())
        assert all(v == "" for v in new_rows.column("_dlt_load_id").to_pylist())

    @pytest.mark.asyncio
    async def test_append_to_legacy_table(self, tmp_path: Path) -> None:
        delta_path = str(tmp_path / "table")
        dt = _create_legacy_delta_table(delta_path)

        helper = _make_local_helper(delta_path)
        batch = evolve_pyarrow_schema(_v3_batch(), dt.schema())

        result = await helper.write_to_deltalake(
            data=batch,
            write_type="append",
            should_overwrite_table=False,
            primary_keys=None,
        )

        final = result.to_pyarrow_table()
        assert final.num_rows == 4
        assert set(final.column("id").to_pylist()) == {1, 2, 3, 4}

    @pytest.mark.asyncio
    async def test_full_refresh_overwrite_on_legacy_table(self, tmp_path: Path) -> None:
        delta_path = str(tmp_path / "table")
        dt = _create_legacy_delta_table(delta_path)

        helper = _make_local_helper(delta_path)
        batch = evolve_pyarrow_schema(_v3_batch(), dt.schema())

        result = await helper.write_to_deltalake(
            data=batch,
            write_type="full_refresh",
            should_overwrite_table=True,
            primary_keys=None,
        )

        final = result.to_pyarrow_table()
        assert final.num_rows == 2
        assert all(v == "" for v in final.column("_dlt_id").to_pylist())
        assert all(v == "" for v in final.column("_dlt_load_id").to_pylist())

    @pytest.mark.asyncio
    async def test_v3_native_table_still_merges(self, tmp_path: Path) -> None:
        delta_path = str(tmp_path / "table")
        fields: list[pa.Field] = [pa.field("id", pa.int64()), pa.field("name", pa.string())]
        schema = pa.schema(fields)
        deltalake.write_deltalake(delta_path, pa.table({"id": [1, 2], "name": ["a", "b"]}, schema=schema))

        helper = _make_local_helper(delta_path)
        batch = pa.table({"id": [3], "name": ["c"]})

        result = await helper.write_to_deltalake(
            data=batch,
            write_type="incremental",
            should_overwrite_table=False,
            primary_keys=["id"],
        )

        final = result.to_pyarrow_table()
        assert final.num_rows == 3
        assert set(final.column("id").to_pylist()) == {1, 2, 3}


class TestAppendDecimalReconciliation:
    """Appending a decimal column that outgrew decimal128 must reconcile to the stored type.

    A batch whose numeric column exceeds decimal128 is promoted to decimal256, which
    `evolve_pyarrow_schema` renders to text for the Delta write. Arrow emits scientific
    notation for scale-heavy zeros (e.g. '0E-18'), which delta-rs can't parse back into
    the stored decimal — an opaque, infinitely-retrying DeltaError on the append path.
    """

    def _seed_decimal_table(self, delta_path: str) -> deltalake.DeltaTable:
        table = pa.table(
            {"id": pa.array([1], type=pa.int64()), "amount": pa.array([Decimal("1.5")], type=pa.decimal128(38, 10))}
        )
        deltalake.write_deltalake(delta_path, table)
        return deltalake.DeltaTable(delta_path)

    @pytest.mark.asyncio
    async def test_scale_heavy_batch_is_rounded_to_stored_type(self, tmp_path: Path) -> None:
        delta_path = str(tmp_path / "table")
        dt = self._seed_decimal_table(delta_path)
        helper = _make_local_helper(delta_path)

        # Values fit decimal128's integer budget but carry more scale than the stored column,
        # so they land as decimal256 and evolve renders them to text (the zero as '0E-18').
        batch = evolve_pyarrow_schema(
            pa.table(
                {
                    "id": pa.array([2, 3], type=pa.int64()),
                    "amount": pa.array(
                        [Decimal("0.12345678901234567890"), Decimal("0E-18")], type=pa.decimal256(76, 20)
                    ),
                }
            ),
            dt.schema(),
        )
        assert pa.types.is_string(batch.schema.field("amount").type)

        result = await helper.write_to_deltalake(
            data=batch, write_type="append", should_overwrite_table=False, primary_keys=None
        )

        final = result.to_pyarrow_table()
        assert final.schema.field("amount").type == pa.decimal128(38, 10)
        assert set(final.column("id").to_pylist()) == {1, 2, 3}
        assert Decimal("0") in final.column("amount").to_pylist()

    @pytest.mark.asyncio
    async def test_integer_overflow_batch_raises_clean_non_retryable(self, tmp_path: Path) -> None:
        delta_path = str(tmp_path / "table")
        dt = self._seed_decimal_table(delta_path)
        helper = _make_local_helper(delta_path)

        batch = evolve_pyarrow_schema(
            pa.table(
                {
                    "id": pa.array([2, 3], type=pa.int64()),
                    "amount": pa.array([Decimal("1" + "0" * 35 + ".5"), Decimal("0E-18")], type=pa.decimal256(76, 18)),
                }
            ),
            dt.schema(),
        )

        with pytest.raises(SchemaColumnTypeChangedException):
            await helper.write_to_deltalake(
                data=batch, write_type="append", should_overwrite_table=False, primary_keys=None
            )


class TestSchemaEvolutionNullability:
    """A column added mid-table-lifetime always predates its own addition: every file the
    table already holds was written without it, so `optimize.compact()` must be able to
    treat those rows as null for that column. If schema evolution adds the column as NOT
    NULL — which happens whenever the batch that introduces it has no nulls, since delta-rs
    takes the new field's nullability straight from the incoming Arrow field — compaction
    later fails with "Non-nullable column '<name>' is missing from the physical schema"."""

    @pytest.mark.asyncio
    async def test_compact_survives_a_column_added_by_an_all_non_null_batch(self, tmp_path: Path) -> None:
        delta_path = str(tmp_path / "table")
        deltalake.write_deltalake(delta_path, pa.table({"id": pa.array([1, 2], type=pa.int64())}))

        helper = _make_local_helper(delta_path)

        # The incoming field is non-nullable because every value in *this* batch is
        # non-null — exactly how upstream Arrow construction infers it, unrelated to
        # whether the column can appear in prior or future batches.
        fields: list[pa.Field] = [pa.field("id", pa.int64()), pa.field("status", pa.string(), nullable=False)]
        batch_schema = pa.schema(fields)
        batch = pa.table(
            {"id": pa.array([3, 4], type=pa.int64()), "status": pa.array(["ok", "ok"])}, schema=batch_schema
        )

        result = await helper.write_to_deltalake(
            data=batch, write_type="append", should_overwrite_table=False, primary_keys=None
        )
        status_field = next(f for f in result.schema().fields if f.name == "status")
        assert status_field.nullable is True

        await DeltaMaintenance(helper).compact_table()

        final = result.to_pyarrow_table()
        by_id = dict(zip(final.column("id").to_pylist(), final.column("status").to_pylist()))
        assert by_id == {1: None, 2: None, 3: "ok", 4: "ok"}


class TestIncrementalBatchDeduplication:
    """Duplicate PKs in a source batch must never reach the Delta write.

    `when_not_matched_insert_all` inserts every unmatched source row, so a batch with a
    repeated PK seeds duplicate rows in the table; every later merge then multi-matches
    those rows and the join blows up (the OOM loop seen with sources whose primary keys
    aren't actually unique).
    """

    @parameterized.expand(
        [
            ("keep_first", "first", ["a1", "b1"]),
            ("keep_last", "last", ["a2", "b1"]),
        ]
    )
    def test_first_per_pk_table_keep_modes(self, _name, keep, expected_names):
        table = pa.table({"id": [1, 1, 2], "name": ["a1", "a2", "b1"]})

        result = first_per_pk_table(table, ["id"], keep=keep).sort_by("id")

        assert result.column("id").to_pylist() == [1, 2]
        assert result.column("name").to_pylist() == expected_names

    @pytest.mark.asyncio
    async def test_incremental_merge_dedupes_duplicate_source_rows(self, tmp_path: Path) -> None:
        delta_path = str(tmp_path / "table")
        deltalake.write_deltalake(delta_path, pa.table({"id": [1], "name": ["old"]}))

        helper = _make_local_helper(delta_path)
        # id=2 appears twice in one batch — without dedup both copies get inserted.
        batch = pa.table({"id": [1, 2, 2], "name": ["updated", "first_copy", "second_copy"]})

        result = await helper.write_to_deltalake(
            data=batch,
            write_type="incremental",
            should_overwrite_table=False,
            primary_keys=["id"],
        )

        final = result.to_pyarrow_table().sort_by("id")
        assert final.column("id").to_pylist() == [1, 2]
        # The last occurrence of a duplicated key carries the freshest data.
        assert final.column("name").to_pylist() == ["updated", "second_copy"]
        cast(AsyncMock, helper._logger.awarning).assert_awaited_once()

    @pytest.mark.asyncio
    async def test_first_sync_append_dedupes_duplicate_source_rows(self, tmp_path: Path) -> None:
        delta_path = str(tmp_path / "table")

        helper = _make_local_helper(delta_path)
        batch = pa.table({"id": [1, 1], "name": ["first_copy", "second_copy"]})

        result = await helper.write_to_deltalake(
            data=batch,
            write_type="incremental",
            should_overwrite_table=False,
            primary_keys=["id"],
        )

        final = result.to_pyarrow_table()
        assert final.column("id").to_pylist() == [1]
        assert final.column("name").to_pylist() == ["second_copy"]


class TestUnpartitionedTableWithPartitionKeyColumn:
    """A Delta table can carry `_ph_partition_key` in its schema while its
    partition_columns metadata is empty `[]` — e.g. the SchemaMismatchError fallback in
    write_to_deltalake rewrites with partition_by=None while the column is still in the
    data, or evolve_pyarrow_schema re-adds the column to a batch headed for an
    unpartitioned table. write_to_deltalake derives partitioning from column *presence*,
    so it then passes partition_by=_ph_partition_key against a table delta-rs considers
    unpartitioned and raises:
        "Specified table partitioning does not match table partitioning: expected: [], got: [_ph_partition_key]"
    """

    def _seed_unpartitioned_table_with_partition_column(self, delta_path: str) -> None:
        # _ph_partition_key is a plain column; the table is NOT partitioned by it.
        deltalake.write_deltalake(
            delta_path,
            pa.table({"id": pa.array([1, 2]), PARTITION_KEY: pa.array(["p0", "p0"])}),
            partition_by=None,
        )
        dt = deltalake.DeltaTable(delta_path)
        assert dt.metadata().partition_columns == []
        assert PARTITION_KEY in dt.schema().to_arrow().names

    @pytest.mark.parametrize(
        "write_type,primary_keys,should_overwrite,expected_ids",
        [
            # append/incremental keep the existing rows; full_refresh overwrites them. Each
            # routes through a distinct write branch, all of which previously raised against
            # the unpartitioned-but-column-present table.
            ("append", None, False, {1, 2, 3, 4}),
            ("incremental", ["id"], False, {1, 2, 3, 4}),
            ("full_refresh", None, True, {2, 3, 4}),
        ],
        ids=["append", "incremental_merge", "full_refresh_overwrite"],
    )
    @pytest.mark.asyncio
    async def test_write_does_not_partition_unpartitioned_table(
        self,
        write_type: str,
        primary_keys: list[str] | None,
        should_overwrite: bool,
        expected_ids: set[int],
        tmp_path: Path,
    ) -> None:
        delta_path = str(tmp_path / "table")
        self._seed_unpartitioned_table_with_partition_column(delta_path)

        helper = _make_local_helper(delta_path)
        # id=2 already exists (merge updates it); id=3,4 are new.
        batch = pa.table({"id": pa.array([2, 3, 4]), PARTITION_KEY: pa.array(["p0", "p0", "p0"])})

        result = await helper.write_to_deltalake(
            data=batch,
            write_type=write_type,  # type: ignore[arg-type]
            should_overwrite_table=should_overwrite,
            primary_keys=primary_keys,
        )

        final = result.to_pyarrow_table()
        assert set(final.column("id").to_pylist()) == expected_ids
        # The table stays unpartitioned — we don't fight its existing layout.
        assert result.metadata().partition_columns == []


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


class TestWriteMisalignedDecimalEndToEnd:
    """Writes a misaligned-decimal batch through the real delta-rs write path. Without the
    realignment guard, delta-rs would abort the process; with it, the write succeeds."""

    @pytest.mark.parametrize(
        "write_type,should_overwrite",
        [("full_refresh", True), ("append", False), ("incremental", False)],
    )
    @pytest.mark.asyncio
    async def test_write_misaligned_decimal_to_local_delta(
        self, write_type: str, should_overwrite: bool, tmp_path: Path
    ) -> None:
        delta_path = str(tmp_path / "table")
        # Seed the table so incremental/append have an existing target to write into.
        deltalake.write_deltalake(
            delta_path,
            pa.table({"id": pa.array([1, 2]), "amount": _decimal_array([5, 6], misaligned=False)}),
        )

        helper = _make_local_helper(delta_path)
        batch = pa.table({"id": pa.array([3, 4]), "amount": _decimal_array([7, 8], misaligned=True)})
        assert _table_is_misaligned(batch) is True

        result = await helper.write_to_deltalake(
            data=batch,
            write_type=write_type,  # type: ignore[arg-type]
            should_overwrite_table=should_overwrite,
            primary_keys=["id"] if write_type == "incremental" else None,
        )

        final = result.to_pyarrow_table()
        amounts = set(final.column("amount").to_pylist())
        if should_overwrite:
            assert set(final.column("id").to_pylist()) == {3, 4}
        else:
            assert {3, 4}.issubset(set(final.column("id").to_pylist()))
            assert {7, 8}.issubset(amounts)


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


class TestNullSafeMergePredicate:
    """The incremental-merge match must be NULL-safe.

    Regression for the duplicate-accumulation bug found by the deltalite shadow canary: composite
    keys with nullable columns (e.g. GoogleAds report resources keyed on `segments.*`) matched with
    bare `source.c = target.c` never match on NULL (`NULL = NULL` is NULL), so the row is re-inserted
    on every incremental sync and the table silently grows.
    """

    def test_predicate_ops_are_null_safe(self):
        assert _merge_predicate_ops(["id", "seg"]) == [
            "(source.id IS NOT DISTINCT FROM target.id)",
            "(source.seg IS NOT DISTINCT FROM target.seg)",
        ]

    @staticmethod
    def _seed_then_merge(path: Path, predicate_ops: list[str]) -> pa.Table:
        # Seed one row whose composite key has a NULL component, then merge the same key with a new value.
        seed = pa.table(
            {
                "id": pa.array([1], pa.int64()),
                "seg": pa.array([None], pa.string()),
                "val": pa.array(["a"], pa.string()),
            }
        )
        deltalake.write_deltalake(str(path), seed, mode="overwrite")
        source = pa.table(
            {
                "id": pa.array([1], pa.int64()),
                "seg": pa.array([None], pa.string()),
                "val": pa.array(["b"], pa.string()),
            }
        )
        (
            deltalake.DeltaTable(str(path))
            .merge(source=source, source_alias="source", target_alias="target", predicate=" AND ".join(predicate_ops))
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute()
        )
        return deltalake.DeltaTable(str(path)).to_pyarrow_table()

    def test_null_composite_key_row_matches_instead_of_duplicating(self, tmp_path):
        result = self._seed_then_merge(tmp_path / "safe", _merge_predicate_ops(["id", "seg"]))
        assert result.num_rows == 1
        assert result.column("val").to_pylist() == ["b"]

    def test_non_null_key_still_matches(self, tmp_path):
        # The null-safe form must not change behaviour for ordinary (non-NULL) keys.
        seed = pa.table({"id": pa.array([1], pa.int64()), "seg": pa.array(["MOBILE"]), "val": pa.array(["a"])})
        deltalake.write_deltalake(str(tmp_path / "nn"), seed, mode="overwrite")
        source = pa.table({"id": pa.array([1], pa.int64()), "seg": pa.array(["MOBILE"]), "val": pa.array(["b"])})
        (
            deltalake.DeltaTable(str(tmp_path / "nn"))
            .merge(
                source=source,
                source_alias="source",
                target_alias="target",
                predicate=" AND ".join(_merge_predicate_ops(["id", "seg"])),
            )
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute()
        )
        result = deltalake.DeltaTable(str(tmp_path / "nn")).to_pyarrow_table()
        assert result.num_rows == 1
        assert result.column("val").to_pylist() == ["b"]

    def test_bare_equality_duplicates_null_key_row(self, tmp_path):
        # Documents the pre-fix behaviour the null-safe predicate corrects.
        result = self._seed_then_merge(tmp_path / "unsafe", ["source.id = target.id", "source.seg = target.seg"])
        assert result.num_rows == 2


class TestDeltaliteWritePath:
    """Phase 2: deltalite performs the real incremental merge, gated solely by a per-schema flag, with
    a hard fallback to the delta-rs MERGE so a deltalite failure can never fail a sync."""

    _FLAG = (
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.core."
        "deltalite_write.is_deltalite_write_enabled"
    )

    @pytest.fixture(autouse=True)
    def _preload_write_metrics(self):
        # _write_via_deltalite lazily imports the pipeline_v3 metrics module. These tests fake the
        # `deltalite` module via patch.dict(sys.modules, ...), which on exit restores the enter-time
        # snapshot and thus evicts any module first imported *inside* the block. If the metrics module
        # were first loaded there, the next test would re-execute it and hit "Duplicated timeseries" in
        # the global Prometheus registry. Loading it here (at setup, before any patch.dict) keeps it in
        # the snapshot so it survives. Imported at runtime — not module top — to keep the heavy
        # pipeline_v3 chain off collection.
        from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load import (  # noqa: F401
            metrics,
        )

    def _helper(self) -> DeltaTableHelper:
        return DeltaTableHelper(resource_name="t", job=MagicMock(team_id=2, schema_id="sch-1"), logger=_make_logger())

    async def _call(self, helper: DeltaTableHelper) -> bool:
        return await helper._write_via_deltalite(
            existing_delta_table=MagicMock(),
            data=pa.table({"id": pa.array([1], pa.int64())}),
            normalized_primary_keys=["id"],
            use_partitioning=False,
            commit_metadata={"run_uuid": "abc"},
        )

    @pytest.mark.asyncio
    async def test_skips_without_primary_keys(self):
        # No primary keys => nothing to key an upsert on; fall back without even evaluating the flag.
        with patch(self._FLAG) as flag:
            wrote = await self._helper()._write_via_deltalite(
                existing_delta_table=MagicMock(),
                data=pa.table({"id": pa.array([1], pa.int64())}),
                normalized_primary_keys=[],
                use_partitioning=False,
                commit_metadata=None,
            )
        assert wrote is False
        flag.assert_not_called()

    def test_write_stats_flattens_scalar_getters_only(self):
        # Enumerates scalar attributes (so future crate fields flow through) and drops methods/non-scalars.
        stats = SimpleNamespace(version=7, rows_inserted=2, files_added=1, _private=9)
        stats.helper = lambda: None  # callable attribute must be ignored
        assert _deltalite_write_stats(stats) == {"version": 7, "rows_inserted": 2, "files_added": 1}

    @pytest.mark.asyncio
    async def test_falls_back_when_flag_disabled(self):
        with patch(self._FLAG, return_value=False):
            assert await self._call(self._helper()) is False

    @pytest.mark.asyncio
    async def test_writes_via_deltalite_when_enabled(self):
        logger = _make_logger()  # captured so we can inspect the structured log without hitting the typed attr
        helper = DeltaTableHelper(resource_name="t", job=MagicMock(team_id=2, schema_id="sch-1"), logger=logger)
        existing = MagicMock()
        # SimpleNamespace stands in for the pyo3 UpsertStats: predictable scalar getters for the structured log.
        fake_stats = SimpleNamespace(
            version=5, partitions_touched=1, rows_inserted=3, rows_updated=2, rows_copied=10, null_pk_rows=0
        )
        fake_table = MagicMock()
        fake_table.upsert.return_value = fake_stats
        fake_deltalite = MagicMock()
        fake_deltalite.DeltaLiteTable.open.return_value = fake_table
        with (
            patch(self._FLAG, return_value=True),
            patch.dict("sys.modules", {"deltalite": fake_deltalite}),
            patch.object(helper, "_get_delta_table_uri", AsyncMock(return_value="s3://b/t")),
            patch.object(helper, "_get_credentials", return_value={"AWS_REGION": "us-east-1"}),
        ):
            wrote = await helper._write_via_deltalite(
                existing_delta_table=existing,
                data=pa.table({"id": pa.array([1], pa.int64())}),
                normalized_primary_keys=["id"],
                use_partitioning=True,
                commit_metadata={"run_uuid": "abc"},
            )
        assert wrote is True
        fake_deltalite.DeltaLiteTable.open.assert_called_once_with("s3://b/t", {"AWS_REGION": "us-east-1"})
        fake_table.upsert.assert_called_once()
        # PARTITION_KEY is passed as the partition arg when the table is partitioned.
        assert fake_table.upsert.call_args.args[2] == PARTITION_KEY
        existing.update_incremental.assert_called_once()
        # The commit is logged with the UpsertStats fields as structured keys + a duration, so it's parseable.
        logger.ainfo.assert_called_once()
        log_kwargs = logger.ainfo.call_args.kwargs
        assert log_kwargs["version"] == 5
        assert log_kwargs["rows_inserted"] == 3
        assert log_kwargs["partitions_touched"] == 1
        assert "duration_ms" in log_kwargs

    @pytest.mark.asyncio
    async def test_falls_back_when_deltalite_raises(self):
        helper = self._helper()
        fake_table = MagicMock()
        fake_table.upsert.side_effect = RuntimeError("commit conflict, retries exhausted")
        fake_deltalite = MagicMock()
        fake_deltalite.DeltaLiteTable.open.return_value = fake_table
        with (
            patch(self._FLAG, return_value=True),
            patch.dict("sys.modules", {"deltalite": fake_deltalite}),
            patch.object(helper, "_get_delta_table_uri", AsyncMock(return_value="s3://b/t")),
            patch.object(helper, "_get_credentials", return_value={}),
        ):
            wrote = await self._call(helper)
        assert wrote is False  # deltalite blew up -> caller falls through to the delta-rs MERGE

    @parameterized.expand([("refresh",), ("log",)])
    @pytest.mark.asyncio
    async def test_post_commit_failure_does_not_fall_back(self, failing_step: str):
        # Once the upsert commits, NO post-commit step (handle refresh, log, metric) may raise into the
        # caller — that would return False / bubble up and re-run the MERGE on top of deltalite's commit.
        logger = _make_logger()  # set the side effect on the mock before it becomes the typed _logger attr
        existing = MagicMock()
        if failing_step == "refresh":
            existing.update_incremental.side_effect = RuntimeError("post-commit refresh boom")
        else:
            logger.ainfo.side_effect = RuntimeError("post-commit log boom")
        helper = DeltaTableHelper(resource_name="t", job=MagicMock(team_id=2, schema_id="sch-1"), logger=logger)
        fake_table = MagicMock()
        fake_table.upsert.return_value = MagicMock(version=5, rows_inserted=1, rows_updated=0, rows_copied=0)
        fake_deltalite = MagicMock()
        fake_deltalite.DeltaLiteTable.open.return_value = fake_table
        with (
            patch(self._FLAG, return_value=True),
            patch.dict("sys.modules", {"deltalite": fake_deltalite}),
            patch.object(helper, "_get_delta_table_uri", AsyncMock(return_value="s3://b/t")),
            patch.object(helper, "_get_credentials", return_value={}),
        ):
            wrote = await helper._write_via_deltalite(
                existing_delta_table=existing,
                data=pa.table({"id": pa.array([1], pa.int64())}),
                normalized_primary_keys=["id"],
                use_partitioning=False,
                commit_metadata=None,
            )
        assert wrote is True  # committed; the post-commit failure is swallowed
        fake_table.upsert.assert_called_once()
