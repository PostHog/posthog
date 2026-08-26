import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow as pa
import deltalake
import pyarrow.compute as pc
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    MissingPrimaryKeysException,
    SchemaColumnTypeChangedException,
    evolve_pyarrow_schema,
    first_per_pk_table,
    realign_decimal_buffers,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.maintenance import DeltaMaintenance
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.test.helpers import (
    decimal_array,
    make_local_table_ref,
    make_logger,
    table_is_misaligned,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.writer import (
    DeltaWriter,
    _deltalite_write_stats,
    _merge_predicate_ops,
)

_WRITER_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.writer"


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


def _make_writer() -> DeltaWriter:
    return DeltaWriter(DeltaTableRef(resource_name="t", job=MagicMock(), logger=make_logger()))


class TestHasCommitWithMetadata:
    @pytest.mark.asyncio
    async def test_returns_false_when_no_delta_table(self):
        writer = _make_writer()
        with patch.object(writer._table, "get_delta_table", AsyncMock(return_value=None)):
            assert await writer.has_commit_with_metadata({"run_uuid": "abc", "batch_index": "0"}) is False

    @parameterized.expand(
        [(name, history, match, expected) for (name, history, match, expected) in _COMMIT_LAYOUT_CASES]
    )
    @pytest.mark.asyncio
    async def test_layout(self, _name: str, history: list[dict], match: dict, expected: bool):
        writer = _make_writer()
        mock_delta = MagicMock()
        mock_delta.history = MagicMock(return_value=history)

        with patch.object(writer._table, "get_delta_table", AsyncMock(return_value=mock_delta)):
            assert await writer.has_commit_with_metadata(match) is expected

    @pytest.mark.asyncio
    async def test_scan_limit_passed_to_history(self):
        writer = _make_writer()
        mock_delta = MagicMock()
        mock_delta.history = MagicMock(return_value=[])

        with patch.object(writer._table, "get_delta_table", AsyncMock(return_value=mock_delta)):
            await writer.has_commit_with_metadata({"k": "v"}, scan_limit=123)

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
        writer = _make_writer()
        with patch.object(writer, "has_commit_with_metadata", AsyncMock(return_value=mocked_return)) as m:
            result = await writer.has_batch_been_committed(run_uuid, batch_index)

            assert result is mocked_return
            m.assert_called_once_with({"run_uuid": run_uuid, "batch_index": str(batch_index)})


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

        helper = DeltaTableRef(resource_name="t", job=MagicMock(), logger=make_logger())
        data = pa.table({"id": [1, 2, 3]})
        mock_delta = MagicMock()
        mock_delta.schema = MagicMock(return_value=MagicMock(to_arrow=MagicMock(return_value=data.schema)))

        with (
            patch.object(helper, "get_delta_table", AsyncMock(return_value=mock_delta)),
            patch(f"{_WRITER_MODULE}.evolve_delta_schema", AsyncMock(return_value=mock_delta)),
            patch("deltalake.write_deltalake") as mock_write,
        ):
            await DeltaWriter(helper).write(
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


class TestNullabilityDriftGuardOrder:
    """The nullability reset signal guards only the delta-rs MERGE fallback: deltalite
    relaxes a lying non-nullable column in the table metadata and writes, so it must
    receive the batch before the guard fires."""

    def _seed_non_nullable_table(self, path: str) -> deltalake.DeltaTable:
        schema = pa.schema(
            [
                pa.field("id", pa.int64(), nullable=False),
                pa.field("v", pa.int64(), nullable=False),
            ]
        )
        deltalake.write_deltalake(path, pa.table({"id": pa.array([1, 2]), "v": pa.array([1, 1])}, schema=schema))
        return deltalake.DeltaTable(path)

    def _null_carrying_batch(self) -> pa.Table:
        # Deliberately NOT passed through evolve_pyarrow_schema: its non-nullable
        # backfill would replace the nulls with defaults, and the guard exists exactly
        # for batches that bypass that preamble.
        return pa.table({"id": pa.array([2, 3], pa.int64()), "v": pa.array([None, 5], pa.int64())})

    @pytest.mark.asyncio
    async def test_merge_fallback_raises_reset_signal_on_null_in_non_nullable(self, tmp_path: Path) -> None:
        delta_path = str(tmp_path / "table")
        self._seed_non_nullable_table(delta_path)
        helper = make_local_table_ref(delta_path)

        # deltalite is off (the flag evaluation fails closed in tests), so the write falls
        # through to the MERGE, which would silently store the nulls under a schema that
        # denies them -- the guard must stop it with the reset signal instead.
        with pytest.raises(SchemaColumnTypeChangedException, match="now contains nulls"):
            await DeltaWriter(helper).write(
                data=self._null_carrying_batch(),
                write_type="incremental",
                should_overwrite_table=False,
                primary_keys=["id"],
            )

    @pytest.mark.asyncio
    async def test_deltalite_write_bypasses_the_reset_signal(self, tmp_path: Path) -> None:
        delta_path = str(tmp_path / "table")
        self._seed_non_nullable_table(delta_path)
        helper = make_local_table_ref(delta_path)

        # deltalite handled the batch (it relaxes the column itself), so the guard must
        # not fire -- firing here would reset tables deltalite can write fine.
        with patch.object(DeltaWriter, "_write_via_deltalite", AsyncMock(return_value=True)):
            result = await DeltaWriter(helper).write(
                data=self._null_carrying_batch(),
                write_type="incremental",
                should_overwrite_table=False,
                primary_keys=["id"],
            )
        assert result is not None


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

        helper = make_local_table_ref(delta_path)
        batch = evolve_pyarrow_schema(_v3_batch(partitioned=partitioned), dt.schema())

        result = await DeltaWriter(helper).write(
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

        helper = make_local_table_ref(delta_path)
        batch = evolve_pyarrow_schema(_v3_batch(), dt.schema())

        result = await DeltaWriter(helper).write(
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

        helper = make_local_table_ref(delta_path)
        batch = evolve_pyarrow_schema(_v3_batch(), dt.schema())

        result = await DeltaWriter(helper).write(
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

        helper = make_local_table_ref(delta_path)
        batch = pa.table({"id": [3], "name": ["c"]})

        result = await DeltaWriter(helper).write(
            data=batch,
            write_type="incremental",
            should_overwrite_table=False,
            primary_keys=["id"],
        )

        final = result.to_pyarrow_table()
        assert final.num_rows == 3
        assert set(final.column("id").to_pylist()) == {1, 2, 3}

    @pytest.mark.asyncio
    async def test_incremental_merge_raises_when_primary_key_column_missing_from_batch(self, tmp_path: Path) -> None:
        """A configured primary key that no longer matches any column in the batch (e.g. a stale
        persisted key name after the source's schema changed) must fail clearly instead of building
        an empty merge predicate — delta-rs rejects an empty predicate with an opaque
        "sql parser error: Expected: an expression, found: EOF" DeltaError."""
        delta_path = str(tmp_path / "table")
        deltalake.write_deltalake(delta_path, pa.table({"id": [1, 2], "name": ["a", "b"]}))

        helper = make_local_table_ref(delta_path)
        batch = pa.table({"name": ["c"]})

        with pytest.raises(MissingPrimaryKeysException):
            await DeltaWriter(helper).write(
                data=batch,
                write_type="incremental",
                should_overwrite_table=False,
                primary_keys=["id"],
            )

    @pytest.mark.asyncio
    async def test_incremental_merge_uses_fallback_key_when_primary_missing_from_batch(self, tmp_path: Path) -> None:
        """Some sources emit rows in more than one shape for the same table (e.g. a record
        sub-type that carries no `uuid`, only `id`). Configuring more than one primary key
        candidate must let a batch merge on whichever one it actually has, instead of raising
        MissingPrimaryKeysException just because the first-listed key is absent from this batch."""
        delta_path = str(tmp_path / "table")
        deltalake.write_deltalake(
            delta_path,
            pa.table(
                {"uuid": ["u1"], "id": [None], "name": ["a"]},
                schema=pa.schema(
                    [
                        pa.field("uuid", pa.string()),
                        pa.field("id", pa.string()),
                        pa.field("name", pa.string()),
                    ]
                ),
            ),
        )

        helper = make_local_table_ref(delta_path)
        batch = pa.table({"id": ["2"], "name": ["b"]})

        result = await DeltaWriter(helper).write(
            data=batch,
            write_type="incremental",
            should_overwrite_table=False,
            primary_keys=["uuid", "id"],
        )

        final = result.to_pyarrow_table()
        assert final.num_rows == 2
        assert set(final.column("name").to_pylist()) == {"a", "b"}


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
        helper = make_local_table_ref(delta_path)

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

        result = await DeltaWriter(helper).write(
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
        helper = make_local_table_ref(delta_path)

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
            await DeltaWriter(helper).write(
                data=batch, write_type="append", should_overwrite_table=False, primary_keys=None
            )


class TestFullRefreshDecimalReconciliation:
    """A later batch of a full_refresh (or first incremental) sync infers its own decimal type
    independently of earlier batches, same as the incremental-merge and append-continuation
    paths. Without reconciling to the table's already-established stored type before writing,
    a batch whose inferred scale is wider than the stored column hits delta-rs's merge-schema
    SchemaMismatchError, since schema_mode="merge" can't widen a stored column's scale in place.
    """

    @pytest.mark.asyncio
    async def test_wider_scale_batch_is_rounded_to_stored_type(self, tmp_path: Path) -> None:
        delta_path = str(tmp_path / "table")
        # First batch establishes a narrower-scale decimal column, as independent per-batch
        # inference would.
        deltalake.write_deltalake(
            delta_path,
            pa.table(
                {"id": pa.array([1], type=pa.int64()), "amount": pa.array([Decimal("1.0")], type=pa.decimal128(4, 1))}
            ),
        )
        helper = make_local_table_ref(delta_path)

        # Second batch's own values infer a wider scale.
        batch = pa.table(
            {
                "id": pa.array([2], type=pa.int64()),
                "amount": pa.array([Decimal("2.23456")], type=pa.decimal128(8, 5)),
            }
        )

        result = await DeltaWriter(helper).write(
            data=batch, write_type="full_refresh", should_overwrite_table=False, primary_keys=None
        )

        final = result.to_pyarrow_table()
        assert final.schema.field("amount").type == pa.decimal128(4, 1)
        assert set(final.column("id").to_pylist()) == {1, 2}
        assert Decimal("2.2") in final.column("amount").to_pylist()


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

        helper = make_local_table_ref(delta_path)

        # The incoming field is non-nullable because every value in *this* batch is
        # non-null — exactly how upstream Arrow construction infers it, unrelated to
        # whether the column can appear in prior or future batches.
        fields: list[pa.Field] = [pa.field("id", pa.int64()), pa.field("status", pa.string(), nullable=False)]
        batch_schema = pa.schema(fields)
        batch = pa.table(
            {"id": pa.array([3, 4], type=pa.int64()), "status": pa.array(["ok", "ok"])}, schema=batch_schema
        )

        result = await DeltaWriter(helper).write(
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

        helper = make_local_table_ref(delta_path)
        # id=2 appears twice in one batch — without dedup both copies get inserted.
        batch = pa.table({"id": [1, 2, 2], "name": ["updated", "first_copy", "second_copy"]})

        result = await DeltaWriter(helper).write(
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

        helper = make_local_table_ref(delta_path)
        batch = pa.table({"id": [1, 1], "name": ["first_copy", "second_copy"]})

        result = await DeltaWriter(helper).write(
            data=batch,
            write_type="incremental",
            should_overwrite_table=False,
            primary_keys=["id"],
        )

        final = result.to_pyarrow_table()
        assert final.column("id").to_pylist() == [1]
        assert final.column("name").to_pylist() == ["second_copy"]


class TestCreateRaceWithExistingTable:
    """DeltaTable.create() defaults to mode="error", raising "table already exists at that
    location" whenever the destination is non-empty. get_delta_table() can report "no table
    yet" while one already exists there — e.g. a zombie Temporal activity attempt (heartbeat-
    timed-out but still running while its retry starts, same unfenced race this package's
    README documents for repartition) races another writer that already created it. write()
    must tolerate that race instead of failing the sync.
    """

    @pytest.mark.parametrize(
        "write_type,expected_ids",
        [("full_refresh", {2, 3}), ("append", {1, 2, 3})],
        ids=["full_refresh", "append"],
    )
    @pytest.mark.asyncio
    async def test_create_tolerates_a_table_already_created_by_a_racing_writer(
        self, write_type: str, expected_ids: set[int], tmp_path: Path
    ):
        delta_path = str(tmp_path / "table")
        # A concurrent writer (e.g. a zombie retry) has already created the table at this location.
        deltalake.write_deltalake(delta_path, pa.table({"id": [1]}))

        helper = make_local_table_ref(delta_path)
        real_get_delta_table = helper.get_delta_table
        calls = {"n": 0}

        async def flaky_first_check():
            calls["n"] += 1
            return None if calls["n"] == 1 else await real_get_delta_table()

        batch = pa.table({"id": [2, 3]})

        with patch.object(helper, "get_delta_table", AsyncMock(side_effect=flaky_first_check)):
            result = await DeltaWriter(helper).write(
                data=batch,
                write_type=write_type,  # type: ignore[arg-type]
                should_overwrite_table=write_type == "full_refresh",
                primary_keys=None,
            )

        assert set(result.to_pyarrow_table().column("id").to_pylist()) == expected_ids


class TestUnpartitionedTableWithPartitionKeyColumn:
    """A Delta table can carry `_ph_partition_key` in its schema while its
    partition_columns metadata is empty `[]` — e.g. the SchemaMismatchError fallback in
    DeltaWriter.write rewrites with partition_by=None while the column is still in the
    data, or evolve_pyarrow_schema re-adds the column to a batch headed for an
    unpartitioned table. DeltaWriter.write derives partitioning from column *presence*,
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

        helper = make_local_table_ref(delta_path)
        # id=2 already exists (merge updates it); id=3,4 are new.
        batch = pa.table({"id": pa.array([2, 3, 4]), PARTITION_KEY: pa.array(["p0", "p0", "p0"])})

        result = await DeltaWriter(helper).write(
            data=batch,
            write_type=write_type,  # type: ignore[arg-type]
            should_overwrite_table=should_overwrite,
            primary_keys=primary_keys,
        )

        final = result.to_pyarrow_table()
        assert set(final.column("id").to_pylist()) == expected_ids
        # The table stays unpartitioned — we don't fight its existing layout.
        assert result.metadata().partition_columns == []


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
            pa.table({"id": pa.array([1, 2]), "amount": decimal_array([5, 6], misaligned=False)}),
        )

        helper = make_local_table_ref(delta_path)
        batch = pa.table({"id": pa.array([3, 4]), "amount": decimal_array([7, 8], misaligned=True)})
        assert table_is_misaligned(batch) is True

        result = await DeltaWriter(helper).write(
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

    def _helper(self) -> DeltaTableRef:
        return DeltaTableRef(resource_name="t", job=MagicMock(team_id=2, schema_id="sch-1"), logger=make_logger())

    async def _call(self, helper: DeltaTableRef) -> bool:
        return await DeltaWriter(helper)._write_via_deltalite(
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
            wrote = await DeltaWriter(self._helper())._write_via_deltalite(
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
        logger = make_logger()  # captured so we can inspect the structured log without hitting the typed attr
        helper = DeltaTableRef(resource_name="t", job=MagicMock(team_id=2, schema_id="sch-1"), logger=logger)
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
            wrote = await DeltaWriter(helper)._write_via_deltalite(
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
        logger = make_logger()  # set the side effect on the mock before it becomes the typed _logger attr
        existing = MagicMock()
        if failing_step == "refresh":
            existing.update_incremental.side_effect = RuntimeError("post-commit refresh boom")
        else:
            logger.ainfo.side_effect = RuntimeError("post-commit log boom")
        helper = DeltaTableRef(resource_name="t", job=MagicMock(team_id=2, schema_id="sch-1"), logger=logger)
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
            wrote = await DeltaWriter(helper)._write_via_deltalite(
                existing_delta_table=existing,
                data=pa.table({"id": pa.array([1], pa.int64())}),
                normalized_primary_keys=["id"],
                use_partitioning=False,
                commit_metadata=None,
            )
        assert wrote is True  # committed; the post-commit failure is swallowed
        fake_table.upsert.assert_called_once()


class TestRealignDecimalBuffers:
    """delta-rs aborts the worker on 8-byte-aligned Decimal128 buffers; realign_decimal_buffers
    rebuilds them on pyarrow's 64-byte allocator before any Delta write reaches delta-rs.
    See delta-io/delta-rs#3884."""

    def test_misaligned_decimal_is_realigned(self) -> None:
        table = pa.table({"amount": decimal_array([1, 2, 3, 4], misaligned=True), "id": pa.array([1, 2, 3, 4])})
        assert table_is_misaligned(table) is True

        result = realign_decimal_buffers(table)

        assert table_is_misaligned(result) is False
        # Values and schema are preserved exactly
        assert result.column("amount").to_pylist() == table.column("amount").to_pylist()
        assert result.column("id").to_pylist() == [1, 2, 3, 4]
        assert result.schema == table.schema

    @pytest.mark.parametrize(
        "table",
        [
            pa.table({"amount": decimal_array([1, 2, 3], misaligned=False), "id": pa.array([1, 2, 3])}),
            pa.table({"id": pa.array([1, 2, 3]), "name": pa.array(["a", "b", "c"])}),
        ],
        ids=["already_aligned_decimal", "no_decimal_columns"],
    )
    def test_unmisaligned_table_is_returned_unchanged(self, table: pa.Table) -> None:
        assert table_is_misaligned(table) is False

        result = realign_decimal_buffers(table)

        # No misalignment found → identity return (no needless copy)
        assert result is table

    def test_only_misaligned_columns_are_rebuilt(self) -> None:
        aligned_dec = decimal_array([10, 20], misaligned=False)
        misaligned_dec = decimal_array([30, 40], misaligned=True)
        table = pa.table({"good": aligned_dec, "bad": misaligned_dec, "id": pa.array([1, 2])})

        result = realign_decimal_buffers(table)

        assert table_is_misaligned(result) is False
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
            [decimal_array([1, 2], misaligned=True), decimal_array([3, 4], misaligned=True)],
        )
        table = pa.table({"amount": chunked, "id": pa.array([1, 2, 3, 4])})
        assert table_is_misaligned(table) is True

        result = realign_decimal_buffers(table)

        assert table_is_misaligned(result) is False
        assert result.column("amount").to_pylist() == [1, 2, 3, 4]

    def test_empty_decimal_table(self) -> None:
        table = pa.table({"amount": pa.array([], type=pa.decimal128(10, 2)), "id": pa.array([], type=pa.int64())})

        result = realign_decimal_buffers(table)

        assert result.num_rows == 0
        assert result.schema == table.schema
