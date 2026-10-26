"""Diff a full read of a table against the open rows of its history table.

A full-refresh sync, or a CDC re-snapshot, reads every row of the source table. The diff compares
that read with the open (current) row of each key in the history table, by key and by row hash:

* a key with no open row, or whose open row is a tombstone, gets a new version;
* a key whose row hash differs from its open row gets a new version, which closes the open row;
* a key with an open row that is missing from the read gets a tombstone, which closes the open row;
* a key whose row hash equals its open row gets nothing.

The output rows carry the validity and deleted columns, so `Scd2DeltaWriter.write` can close the
open rows and append them. That writer must hash with the same `row_hash_exclude_columns`, or every
row reads as changed on the next diff.

The diff holds the read rows of one key-hash bucket at a time, so memory follows the bucket size and
the row group size, not the table size. Each bucket scans the read and the history table once more, which trades read
time for memory on a table larger than one bucket.
"""

import math
from collections.abc import Collection, Iterator, Sequence
from datetime import datetime
from typing import Any, cast

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as pa_ds

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    first_per_pk_table,
    normalize_column_name,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.memory_governor import (
    MB,
    get_governor,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.row_hash import (
    ROW_HASH_VERSION,
    compute_row_hashes,
)

MAX_BUCKET_KEYS = 2_000_000
# Each bucket scans the whole read again, so a smaller bucket than this costs more scans than the
# memory it saves is worth. A table that needs smaller buckets runs above its memory slice instead.
MIN_BUCKET_KEYS = 250_000
# Peak memory of a bucket per decoded byte of its read rows: the rows, their hash payload while it
# is built, the join tables, and one decoded row group per scan. As of October 2026, a 2M-key diff
# of ~100-byte rows peaked at about 1 GB, five times the decoded rows.
_PEAK_BYTES_PER_READ_BYTE = 5.0
_ROW_SIZE_SAMPLE_ROWS = 1_000
_SCAN_BATCH_ROWS = 65_536
_BUCKET_HASH_SEED = 0

_ROW = "__ph_diff_row"
_HASH = "__ph_diff_hash"
_OPEN = "__ph_diff_open"
_OPEN_HASH = "__ph_diff_open_hash"
_OPEN_DELETED = "__ph_diff_open_deleted"
_TIMESTAMP_TYPE = pa.timestamp("us", tz="UTC")


@frozen
class HistoryColumns:
    """The columns a history table stamps on each version."""

    valid_from: str
    valid_to: str
    row_hash: str
    deleted: str
    deleted_at: str

    @property
    def row_hash_version(self) -> str:
        return f"{self.row_hash}_version"


@frozen
class HistoryDiffBucket:
    """The changes of one key-hash bucket.

    `rows` holds the new versions and the tombstones, stamped with the validity and deleted
    columns, in the shape `Scd2DeltaWriter.write` takes. Each key appears at most once.
    """

    rows: pa.Table
    new_keys: int
    changed_keys: int
    deleted_keys: int
    unchanged_keys: int


def bucket_keys_for_budget(budget_mb: float | None, read_row_bytes: float) -> int:
    """The number of keys one bucket may hold so that its peak fits `budget_mb`."""
    if budget_mb is None or read_row_bytes <= 0:
        return MAX_BUCKET_KEYS
    fitting = int(budget_mb * MB / (read_row_bytes * _PEAK_BYTES_PER_READ_BYTE))
    return min(MAX_BUCKET_KEYS, max(MIN_BUCKET_KEYS, fitting))


class HistoryDiff:
    """Diffs a full read against a history table and yields the changes one bucket at a time.

    `valid_from` stamps every new version and tombstone, and is the time the open rows close at.
    `row_hash_exclude_columns` names the columns left out of the row hash, as on `Scd2DeltaWriter`.
    Bucket size comes from the memory governor's per-load slice unless `max_bucket_keys` is set.
    """

    def __init__(
        self,
        *,
        primary_keys: Sequence[str],
        columns: HistoryColumns,
        valid_from: datetime,
        row_hash_exclude_columns: Collection[str] = (),
        max_bucket_keys: int | None = None,
    ) -> None:
        if not primary_keys:
            raise ValueError("A history diff needs a primary key")
        self._primary_keys = [normalize_column_name(name) for name in primary_keys]
        self._columns = columns
        self._valid_from = valid_from
        self._max_bucket_keys = max_bucket_keys
        # The same set Scd2DeltaWriter leaves out, so a hash computed here equals the stored one.
        self._unhashed_columns = {
            columns.valid_from,
            columns.valid_to,
            columns.row_hash,
            columns.row_hash_version,
            *(normalize_column_name(name) for name in row_hash_exclude_columns),
        }

    def buckets(self, read: pa_ds.Dataset, history: pa_ds.Dataset | None) -> Iterator[HistoryDiffBucket]:
        """Yield the changes of each bucket. `history` is None when the history table does not exist yet."""
        columns = self._columns
        stamped = {
            columns.valid_from,
            columns.valid_to,
            columns.row_hash,
            columns.row_hash_version,
            columns.deleted,
            columns.deleted_at,
        }
        taken = stamped & set(read.schema.names)
        if taken:
            raise ValueError(f"Source column(s) {sorted(taken)} collide with the history table's columns")
        missing = [name for name in self._primary_keys if name not in read.schema.names]
        if missing:
            raise ValueError(f"The read has no primary key column(s) {missing}")

        key_types = self._key_types(read, history)
        bucket_count = self._bucket_count(read, history)
        for bucket in range(bucket_count):
            yield self._diff_bucket(read, history, key_types, bucket, bucket_count)

    def _key_types(self, read: pa_ds.Dataset, history: pa_ds.Dataset | None) -> dict[str, pa.DataType]:
        # Both sides must hold a key in the same type to join, and to hash into the same bucket.
        # The history table's type wins, because the output rows are appended to it.
        source = history if history is not None else read
        return {
            name: (source.schema.field(name) if name in source.schema.names else read.schema.field(name)).type
            for name in self._primary_keys
        }

    def _bucket_count(self, read: pa_ds.Dataset, history: pa_ds.Dataset | None) -> int:
        keys = read.count_rows()
        if history is not None:
            keys = max(keys, history.count_rows(filter=self._open_filter()))
        if self._max_bucket_keys is not None:
            bucket_keys = self._max_bucket_keys
        else:
            sample = read.head(_ROW_SIZE_SAMPLE_ROWS)
            row_bytes = sample.nbytes / sample.num_rows if sample.num_rows else 0.0
            bucket_keys = bucket_keys_for_budget(get_governor().slot_budget_mb(), row_bytes)
        return max(1, math.ceil(keys / bucket_keys))

    def _open_filter(self) -> pc.Expression:
        return pc.field(self._columns.valid_to).is_null()

    def _diff_bucket(
        self,
        read: pa_ds.Dataset,
        history: pa_ds.Dataset | None,
        key_types: dict[str, pa.DataType],
        bucket: int,
        bucket_count: int,
    ) -> HistoryDiffBucket:
        read_rows = self._scan_bucket(read, None, None, key_types, bucket, bucket_count)
        # A source can return a key twice. Two open versions of one key would break the next close.
        read_rows = first_per_pk_table(read_rows, self._primary_keys)
        read_rows = read_rows.append_column(
            pa.field(self._columns.deleted, pa.bool_()), pa.repeat(False, read_rows.num_rows)
        )
        # Hashed with the deleted flag in it, as the writer hashes the rows it gets, so a tombstone
        # never has the hash of a live row.
        read_hashes = compute_row_hashes(read_rows, self._unhashed_columns)
        read_keys = read_rows.select(self._primary_keys).append_column(_HASH, read_hashes)
        read_keys = read_keys.append_column(_ROW, pa.array(range(read_rows.num_rows), type=pa.int64()))

        open_rows = self._open_rows(history, key_types, bucket, bucket_count)
        joined = read_keys.join(open_rows, self._primary_keys, join_type="left outer")
        is_new = pc.is_null(joined.column(_OPEN))
        is_changed = pc.and_(
            pc.invert(is_new),
            pc.or_(
                _filled(joined.column(_OPEN_DELETED), False),
                _filled(pc.not_equal(joined.column(_HASH), joined.column(_OPEN_HASH)), True),
            ),
        )
        versions = read_rows.take(joined.filter(pc.or_(is_new, is_changed)).sort_by(_ROW).column(_ROW))

        live_open_keys = open_rows.filter(pc.invert(_filled(open_rows.column(_OPEN_DELETED), False)))
        gone = live_open_keys.select(self._primary_keys).join(
            read_keys.select(self._primary_keys), self._primary_keys, join_type="left anti"
        )
        tombstones = self._tombstones(gone, history)

        new_keys = _count(is_new)
        changed_keys = _count(is_changed)
        return HistoryDiffBucket(
            rows=self._stamp_validity(pa.concat_tables([versions, tombstones], promote_options="default"), history),
            new_keys=new_keys,
            changed_keys=changed_keys,
            deleted_keys=gone.num_rows,
            unchanged_keys=read_rows.num_rows - new_keys - changed_keys,
        )

    def _open_rows(
        self, history: pa_ds.Dataset | None, key_types: dict[str, pa.DataType], bucket: int, bucket_count: int
    ) -> pa.Table:
        """The keys of the bucket's open rows, with their row hash and deleted flag."""
        schema = pa.schema(
            [
                *(pa.field(name, key_types[name]) for name in self._primary_keys),
                pa.field(_OPEN_HASH, pa.binary(16)),
                pa.field(_OPEN_DELETED, pa.bool_()),
                pa.field(_OPEN, pa.bool_()),
            ]
        )
        if history is None:
            return schema.empty_table()

        names = set(history.schema.names)
        columns = self._columns
        has_hashes = columns.row_hash in names and columns.row_hash_version in names
        stored = [name for name in (columns.row_hash, columns.row_hash_version, columns.deleted) if name in names]
        rows = self._scan_bucket(
            history, [*self._primary_keys, *stored], self._open_filter(), key_types, bucket, bucket_count
        )
        hashes: pa.Array | pa.ChunkedArray
        if has_hashes and not pc.any(self._stale_hashes(rows)).as_py():
            hashes = rows.column(columns.row_hash)
        else:
            # A row written before row hashes, or under another hash version, has no comparable
            # hash. Hash its stored values instead, so that it does not read as changed.
            rows = self._scan_bucket(history, None, self._open_filter(), key_types, bucket, bucket_count)
            hashes = compute_row_hashes(rows, self._unhashed_columns)
            if has_hashes:
                hashes = pc.if_else(self._stale_hashes(rows), hashes, rows.column(columns.row_hash))

        deleted = rows.column(columns.deleted) if columns.deleted in names else pa.repeat(False, rows.num_rows)
        keyed = pa.table(
            [
                *(rows.column(name) for name in self._primary_keys),
                pc.cast(hashes, pa.binary(16)),
                deleted,
                pa.repeat(True, rows.num_rows),
            ],
            schema=schema,
        )
        # Two open rows of one key would each match the read row and emit it twice.
        return first_per_pk_table(keyed, self._primary_keys)

    def _stale_hashes(self, rows: pa.Table) -> pa.BooleanArray:
        version = rows.column(self._columns.row_hash_version)
        return _filled(pc.not_equal(version, pa.scalar(ROW_HASH_VERSION, version.type)), True)

    def _scan_bucket(
        self,
        dataset: pa_ds.Dataset,
        columns: list[str] | None,
        row_filter: pc.Expression | None,
        key_types: dict[str, pa.DataType],
        bucket: int,
        bucket_count: int,
    ) -> pa.Table:
        scanner = dataset.scanner(
            columns=columns, filter=row_filter, batch_size=_SCAN_BATCH_ROWS, batch_readahead=1, fragment_readahead=1
        )
        parts: list[pa.Table] = []
        for batch in scanner.to_batches():
            part = self._with_key_types(pa.Table.from_batches([batch]), key_types)
            if bucket_count > 1:
                part = part.filter(self._bucket_mask(part, bucket, bucket_count))
            if part.num_rows:
                parts.append(part)
        if not parts:
            return self._with_key_types(scanner.projected_schema.empty_table(), key_types)
        return pa.concat_tables(parts)

    def _with_key_types(self, table: pa.Table, key_types: dict[str, pa.DataType]) -> pa.Table:
        for name, key_type in key_types.items():
            index = table.schema.get_field_index(name)
            if table.schema.field(index).type != key_type:
                table = table.set_column(index, pa.field(name, key_type), table.column(index).cast(key_type))
        return table

    def _bucket_mask(self, table: pa.Table, bucket: int, bucket_count: int) -> pa.Array:
        import polars as pl  # noqa: PLC0415 — keeps polars off the import path of every pipeline that loads the delta package

        keys = pl.from_arrow(table.select(self._primary_keys))
        assert isinstance(keys, pl.DataFrame)
        buckets = (keys.hash_rows(seed=_BUCKET_HASH_SEED) % bucket_count).to_arrow()
        return pc.equal(buckets, pa.scalar(bucket, buckets.type))

    def _tombstones(self, gone: pa.Table, history: pa_ds.Dataset | None) -> pa.Table:
        deleted_at_type = self._history_type(history, self._columns.deleted_at)
        return gone.append_column(
            pa.field(self._columns.deleted, pa.bool_()), pa.repeat(True, gone.num_rows)
        ).append_column(
            pa.field(self._columns.deleted_at, deleted_at_type),
            _repeat(self._valid_from, gone.num_rows, deleted_at_type),
        )

    def _stamp_validity(self, rows: pa.Table, history: pa_ds.Dataset | None) -> pa.Table:
        validity_type = self._history_type(history, self._columns.valid_from)
        return rows.append_column(
            pa.field(self._columns.valid_from, validity_type),
            _repeat(self._valid_from, rows.num_rows, validity_type),
        ).append_column(pa.field(self._columns.valid_to, validity_type), _repeat(None, rows.num_rows, validity_type))

    def _history_type(self, history: pa_ds.Dataset | None, name: str) -> pa.DataType:
        if history is not None and name in history.schema.names:
            return history.schema.field(name).type
        return _TIMESTAMP_TYPE


def _filled(mask: pa.Array | pa.ChunkedArray, value: bool) -> pa.BooleanArray:
    combined = mask.combine_chunks() if isinstance(mask, pa.ChunkedArray) else mask
    return cast(pa.BooleanArray, cast(pa.BooleanArray, combined).fill_null(value))


def _repeat(value: Any, size: int, value_type: pa.DataType) -> pa.Array:
    # pyarrow's stubs type `repeat` per scalar class, so they reject a scalar whose type is only known at runtime.
    return pa.repeat(pa.scalar(value, value_type), size)  # type: ignore[call-overload]


def _count(mask: pa.BooleanArray) -> int:
    return pc.sum(mask.cast(pa.int64())).as_py() or 0
