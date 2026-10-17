import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

import pyarrow as pa
import deltalake
import pyarrow.compute as pc
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.scd2 import Scd2DeltaWriter
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.test.helpers import (
    decimal_array,
    make_local_table_ref,
    table_is_misaligned,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.writer import commit_matches

_TS_TYPE = pa.timestamp("us", tz="UTC")


def _make_writer(delta_uri: str) -> Scd2DeltaWriter:
    return Scd2DeltaWriter(make_local_table_ref(delta_uri), valid_from_column="valid_from", valid_to_column="valid_to")


def _make_skip_unchanged_writer(delta_uri: str) -> Scd2DeltaWriter:
    return Scd2DeltaWriter(
        make_local_table_ref(delta_uri),
        valid_from_column="valid_from",
        valid_to_column="valid_to",
        row_hash_column="row_hash",
        # The raw source name, which the writer has to normalize to match the batch column.
        row_hash_exclude_columns=["syncedAt"],
    )


def _history_batch(rows: list[tuple[str, str, int, datetime]]) -> pa.Table:
    ids, plans, synced_at, valid_from = zip(*rows)
    return pa.table(
        {
            "id": pa.array(ids),
            "plan": pa.array(plans),
            "synced_at": pa.array(synced_at),
            "valid_from": pa.array(valid_from, type=_TS_TYPE),
            "valid_to": pa.array([None] * len(rows), type=_TS_TYPE),
        }
    )


def _versions(delta_table: deltalake.DeltaTable) -> list[tuple[str, str, datetime, datetime | None]]:
    rows = delta_table.to_pyarrow_table().to_pylist()
    return sorted((r["id"], r["plan"], r["valid_from"], r["valid_to"]) for r in rows)


class TestScd2Write:
    @pytest.mark.asyncio
    async def test_first_write_creates_the_table_with_a_short_checkpoint_interval(self, tmp_path: Path) -> None:
        # The SCD2 writer has its own create path; a table it creates on delta-rs's default interval
        # would replay a long uncheckpointed tail on every open.
        delta_path = str(tmp_path / "scd2_table")
        batch = pa.table(
            {
                "id": pa.array([1]),
                "valid_from": pa.array([datetime(2026, 1, 1, tzinfo=UTC)], type=_TS_TYPE),
                "valid_to": pa.array([None], type=_TS_TYPE),
            }
        )

        writer = _make_writer(delta_path)
        written = await writer.write(data=batch, primary_keys=["id"])

        live = deltalake.DeltaTable(delta_path)
        assert live.metadata().configuration.get("delta.checkpointInterval") == "25"
        # The ref keeps the handle of the table it created, and that handle holds every commit of the write.
        assert await writer._table.get_delta_table() is written
        assert written.version() == live.version()

    @pytest.mark.asyncio
    async def test_write_misaligned_decimal_to_local_delta(self, tmp_path: Path) -> None:
        # The SCD2 write carries its own realignment guard; without it the
        # close-existing merge would hand delta-rs a misaligned decimal and abort the worker.
        delta_path = str(tmp_path / "scd2_table")
        ts1 = datetime(2026, 1, 1, tzinfo=UTC)
        ts2 = datetime(2026, 2, 1, tzinfo=UTC)
        # Seed a current (valid_to IS NULL) row for id=1 so the new batch closes it.
        deltalake.write_deltalake(
            delta_path,
            pa.table(
                {
                    "id": pa.array([1]),
                    "amount": decimal_array([5], misaligned=False),
                    "valid_from": pa.array([ts1], type=_TS_TYPE),
                    "valid_to": pa.array([None], type=_TS_TYPE),
                }
            ),
        )

        batch = pa.table(
            {
                "id": pa.array([1]),
                "amount": decimal_array([7], misaligned=True),
                "valid_from": pa.array([ts2], type=_TS_TYPE),
                "valid_to": pa.array([None], type=_TS_TYPE),
            }
        )
        assert table_is_misaligned(batch) is True

        result = await _make_writer(delta_path).write(data=batch, primary_keys=["id"])

        final = result.to_pyarrow_table()
        # The seeded row is closed (valid_to set) and the new misaligned row is appended.
        assert final.num_rows == 2
        assert set(final.column("amount").to_pylist()) == {5, 7}
        closed = final.filter(pc.equal(final.column("amount"), pa.scalar(Decimal("5.00"), type=pa.decimal128(10, 2))))
        assert closed.column("valid_to").to_pylist() == [ts2]

    @pytest.mark.asyncio
    async def test_write_batch_declaring_a_null_column_not_null(self, tmp_path: Path) -> None:
        # CDC reads SQL sources, whose batch schema copies the source database's is_nullable
        # metadata, so a column can claim NOT NULL and still arrive holding nulls. Both delta
        # calls in the SCD2 write reject that batch: write_deltalake raises and merge panics.
        delta_path = str(tmp_path / "scd2_table")
        ts1 = datetime(2026, 1, 1, tzinfo=UTC)
        ts2 = datetime(2026, 2, 1, tzinfo=UTC)
        deltalake.write_deltalake(
            delta_path,
            pa.table(
                {
                    "id": pa.array([1]),
                    "note": pa.array(["first"]),
                    "valid_from": pa.array([ts1], type=_TS_TYPE),
                    "valid_to": pa.array([None], type=_TS_TYPE),
                }
            ),
        )

        batch_fields: list[pa.Field] = [
            pa.field("id", pa.int64(), nullable=False),
            pa.field("note", pa.string(), nullable=False),
            pa.field("valid_from", _TS_TYPE, nullable=False),
            pa.field("valid_to", _TS_TYPE, nullable=True),
        ]
        batch = pa.table(
            {"id": [1], "note": [None], "valid_from": [ts2], "valid_to": [None]},
            schema=pa.schema(batch_fields),
        )

        result = await _make_writer(delta_path).write(data=batch, primary_keys=["id"])

        final = result.to_pyarrow_table()
        assert final.num_rows == 2
        assert sorted(final.column("note").to_pylist(), key=lambda x: x is not None) == [None, "first"]

    @pytest.mark.asyncio
    async def test_only_terminal_append_commit_carries_metadata(self, tmp_path: Path) -> None:
        # SCD2 is a two-step write (close-existing merge, then append). If the intermediate
        # close merge were tagged with (run_uuid, batch_index) and the writer crashed before
        # the append, Kafka redelivery would find the tagged commit via
        # has_batch_been_committed, treat the batch as already written, and silently skip
        # the append — data loss. Only the terminal append commit may carry the metadata.
        delta_path = str(tmp_path / "scd2_table")
        ts1 = datetime(2026, 1, 1, tzinfo=UTC)
        ts2 = datetime(2026, 2, 1, tzinfo=UTC)
        deltalake.write_deltalake(
            delta_path,
            pa.table(
                {
                    "id": pa.array([1]),
                    "valid_from": pa.array([ts1], type=_TS_TYPE),
                    "valid_to": pa.array([None], type=_TS_TYPE),
                }
            ),
        )
        batch = pa.table(
            {
                "id": pa.array([1]),
                "valid_from": pa.array([ts2], type=_TS_TYPE),
                "valid_to": pa.array([None], type=_TS_TYPE),
            }
        )
        metadata = {"run_uuid": "r1", "batch_index": "0"}

        await _make_writer(delta_path).write(data=batch, primary_keys=["id"], commit_metadata=metadata)

        history = deltalake.DeltaTable(delta_path).history()
        # Newest first: [append (WRITE), close (MERGE), seed (WRITE)]. commit_matches is the
        # same layout-agnostic check has_batch_been_committed uses for redelivery dedup.
        tagged = [c["operation"] for c in history if commit_matches(c, metadata)]
        assert tagged == ["WRITE"]
        assert any(c["operation"] == "MERGE" for c in history)


class TestScd2SkipUnchanged:
    @pytest.mark.asyncio
    async def test_resent_row_makes_no_version_and_changed_row_does(self, tmp_path: Path) -> None:
        delta_path = str(tmp_path / "scd2_table")
        ts1 = datetime(2026, 1, 1, tzinfo=UTC)
        ts2 = datetime(2026, 2, 1, tzinfo=UTC)
        writer = _make_skip_unchanged_writer(delta_path)
        await writer.write(data=_history_batch([("a", "free", 1, ts1), ("b", "free", 1, ts1)]), primary_keys=["id"])

        result = await writer.write(
            data=_history_batch([("a", "free", 2, ts2), ("b", "pro", 2, ts2), ("c", "free", 2, ts2)]),
            primary_keys=["id"],
        )

        assert _versions(result) == [
            ("a", "free", ts1, None),
            ("b", "free", ts1, ts2),
            ("b", "pro", ts2, None),
            ("c", "free", ts2, None),
        ]

    @pytest.mark.asyncio
    async def test_source_column_named_like_the_hash_column_is_rejected(self, tmp_path: Path) -> None:
        batch = _history_batch([("a", "free", 1, datetime(2026, 1, 1, tzinfo=UTC))])

        with pytest.raises(ValueError, match="row_hash"):
            await _make_skip_unchanged_writer(str(tmp_path / "scd2_table")).write(
                data=batch.append_column("row_hash", pa.array(["from the source"])), primary_keys=["id"]
            )

    @pytest.mark.asyncio
    async def test_composite_key_compares_each_row_with_its_own_key(self, tmp_path: Path) -> None:
        delta_path = str(tmp_path / "scd2_table")
        ts1 = datetime(2026, 1, 1, tzinfo=UTC)
        ts2 = datetime(2026, 2, 1, tzinfo=UTC)
        writer = _make_skip_unchanged_writer(delta_path)
        seed = _history_batch([("a", "free", 1, ts1), ("a", "pro", 1, ts1)])
        await writer.write(data=seed.append_column("tenant", pa.array(["t1", "t2"])), primary_keys=["tenant", "id"])

        batch = _history_batch([("a", "free", 2, ts2), ("a", "free", 2, ts2)])
        result = await writer.write(
            data=batch.append_column("tenant", pa.array(["t1", "t2"])), primary_keys=["tenant", "id"]
        )

        rows = result.to_pyarrow_table().to_pylist()
        assert sorted((r["tenant"], r["plan"], r["valid_from"], r["valid_to"]) for r in rows) == [
            ("t1", "free", ts1, None),
            ("t2", "free", ts2, None),
            ("t2", "pro", ts1, ts2),
        ]

    @pytest.mark.asyncio
    async def test_batch_of_only_unchanged_rows_commits_nothing(self, tmp_path: Path) -> None:
        delta_path = str(tmp_path / "scd2_table")
        ts1 = datetime(2026, 1, 1, tzinfo=UTC)
        writer = _make_skip_unchanged_writer(delta_path)
        first = await writer.write(data=_history_batch([("a", "free", 1, ts1)]), primary_keys=["id"])
        version = first.version()

        result = await writer.write(
            data=_history_batch([("a", "free", 2, datetime(2026, 2, 1, tzinfo=UTC))]),
            primary_keys=["id"],
            commit_metadata={"run_uuid": "r1", "batch_index": "0"},
        )

        assert result.version() == version
        assert _versions(result) == [("a", "free", ts1, None)]

    @parameterized.expand(
        [
            ("written_without_a_hash", None),
            ("hashed_under_another_version", "v0:0123456789abcdef"),
        ]
    )
    @pytest.mark.asyncio
    async def test_current_row_without_a_comparable_hash_is_compared_by_value(
        self, _name: str, stored_hash: str | None
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            delta_path = str(Path(tmp) / "scd2_table")
            ts1 = datetime(2026, 1, 1, tzinfo=UTC)
            ts2 = datetime(2026, 2, 1, tzinfo=UTC)
            seed = _history_batch([("a", "free", 1, ts1), ("b", "free", 1, ts1)])
            if stored_hash is not None:
                seed = seed.append_column("row_hash", pa.array([stored_hash, stored_hash]))
            deltalake.write_deltalake(delta_path, seed)

            result = await _make_skip_unchanged_writer(delta_path).write(
                data=_history_batch([("a", "free", 2, ts2), ("b", "pro", 2, ts2)]), primary_keys=["id"]
            )

            assert _versions(result) == [
                ("a", "free", ts1, None),
                ("b", "free", ts1, ts2),
                ("b", "pro", ts2, None),
            ]

    @pytest.mark.asyncio
    async def test_only_leading_unchanged_rows_of_a_key_are_dropped(self, tmp_path: Path) -> None:
        delta_path = str(tmp_path / "scd2_table")
        ts1 = datetime(2026, 1, 1, tzinfo=UTC)
        ts2 = datetime(2026, 2, 1, tzinfo=UTC)
        ts3 = datetime(2026, 3, 1, tzinfo=UTC)
        writer = _make_skip_unchanged_writer(delta_path)
        await writer.write(data=_history_batch([("a", "free", 1, ts1), ("b", "free", 1, ts1)]), primary_keys=["id"])

        # Key "a" repeats its current row and then changes. Key "b" changes and then goes back.
        batch = _history_batch(
            [("a", "free", 2, ts2), ("b", "pro", 2, ts2), ("a", "pro", 3, ts3), ("b", "free", 3, ts3)]
        )
        valid_to = pa.array([ts3, ts3, None, None], type=_TS_TYPE)
        batch = batch.set_column(batch.schema.get_field_index("valid_to"), "valid_to", valid_to)

        result = await writer.write(data=batch, primary_keys=["id"])

        assert _versions(result) == [
            ("a", "free", ts1, ts3),
            ("a", "pro", ts3, None),
            ("b", "free", ts1, ts2),
            ("b", "free", ts3, None),
            ("b", "pro", ts2, ts3),
        ]
