from __future__ import annotations

import json
import random
import dataclasses
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import pyarrow as pa
import deltalake
import deltalite
import pyarrow.compute as pc

CURRENT = "current"
TS = pa.timestamp("us", tz="UTC")
MONTH_VECTORS = json.loads(
    (Path(__file__).resolve().parents[2] / "core" / "tests" / "fixtures" / "month_vectors.json").read_text()
)
TABLE_SCHEMA = pa.schema(
    [
        pa.field("id", pa.string()),
        pa.field("n", pa.int64()),
        pa.field("ts", TS),
        pa.field("payload", pa.string()),
        pa.field("valid_to", TS),
        pa.field("p", pa.string(), nullable=False),
    ]
)
SOURCE_SCHEMA = pa.schema(
    [
        pa.field("id", pa.string()),
        pa.field("n", pa.int64()),
        pa.field("ts", TS),
        pa.field("payload", pa.string()),
        pa.field("seq", pa.int64()),
    ]
)


# The product names month partitions with `pc.strftime(valid_to, "%Y-%m")`.
def month(instant: datetime) -> str:
    return pc.strftime(pa.array([instant], TS), format="%Y-%m")[0].as_py()


@dataclasses.dataclass(frozen=True)
class Src:
    id: str | None
    n: int | None
    ts: datetime
    payload: str
    seq: int

    @property
    def key(self) -> tuple[str | None, int | None]:
        return (self.id, self.n)


@dataclasses.dataclass(frozen=True)
class Row:
    p: str
    id: str | None
    n: int | None
    ts: datetime
    valid_to: datetime | None
    payload: str


@dataclasses.dataclass(frozen=True)
class Counts:
    committed: bool
    rows_reread: int
    rows_backwards: int
    versions_opened: int
    versions_closed: int
    chain_rows_closed: int


def model_apply(rows: list[Row], source: list[Src]) -> tuple[list[Row], Counts]:
    open_rows = {(r.id, r.n): r for r in rows if r.p == CURRENT}
    best: dict[tuple, Src] = {}
    for s in source:
        k = (s.key, s.ts)
        if k not in best or s.seq >= best[k].seq:
            best[k] = s
    by_key: dict[tuple, list[Src]] = {}
    for s in sorted(best.values(), key=lambda s: s.ts):
        by_key.setdefault(s.key, []).append(s)

    out = [r for r in rows if r.p != CURRENT]
    reread = backwards = opened = closed = chained = 0
    for key, versions in by_key.items():
        old = open_rows.get(key)
        kept = [s for s in versions if old is None or s.ts > old.ts]
        if old is not None:
            reread += sum(s.ts == old.ts for s in versions)
            backwards += sum(s.ts < old.ts for s in versions)
        if not kept:
            continue
        if old is not None:
            open_rows.pop(key)
            out.append(dataclasses.replace(old, valid_to=kept[0].ts, p=month(kept[0].ts)))
            closed += 1
        for this, following in zip(kept, kept[1:]):
            out.append(Row(month(following.ts), this.id, this.n, this.ts, following.ts, this.payload))
            chained += 1
        last = kept[-1]
        out.append(Row(CURRENT, last.id, last.n, last.ts, None, last.payload))
        opened += 1
    out.extend(open_rows.values())
    return sorted(out, key=_order), Counts(opened > 0, reread, backwards, opened, closed, chained)


def _order(r: Row) -> tuple:
    return (r.p, r.id or "", r.id is None, r.n or 0, r.n is None, r.ts, r.valid_to or r.ts, r.payload)


def read(uri: str) -> list[Row]:
    t = deltalake.DeltaTable(uri).to_pyarrow_table()
    rows = [Row(d["p"], d["id"], d["n"], d["ts"], d["valid_to"], d["payload"]) for d in t.to_pylist()]
    return sorted(rows, key=_order)


def source_table(rows: list[Src]) -> pa.Table:
    return pa.table(
        {
            "id": pa.array([r.id for r in rows], pa.string()),
            "n": pa.array([r.n for r in rows], pa.int64()),
            "ts": pa.array([r.ts for r in rows], TS),
            "payload": pa.array([r.payload for r in rows], pa.string()),
            "seq": pa.array([r.seq for r in rows], pa.int64()),
        },
        schema=SOURCE_SCHEMA,
    )


def create(tmp_path: Path, partition_by: list[str] | None = None) -> str:
    uri = str(tmp_path / "history")
    deltalake.DeltaTable.create(uri, schema=TABLE_SCHEMA, partition_by=["p"] if partition_by is None else partition_by)
    return uri


def split_into_batches(table: pa.Table, rng: random.Random) -> pa.Table:
    cuts = sorted(rng.randint(0, table.num_rows) for _ in range(rng.randint(0, 4)))
    bounds = [0, *cuts, table.num_rows]
    batches = [b for start, end in zip(bounds, bounds[1:]) for b in table.slice(start, end - start).to_batches()]
    if rng.random() < 0.5:
        batches.insert(rng.randint(0, len(batches)), pa.RecordBatch.from_pylist([], schema=SOURCE_SCHEMA))
    return pa.Table.from_batches(batches, schema=SOURCE_SCHEMA)


def history_upsert(
    uri: str, rows: list[Src], split_rng: random.Random | None = None, **kwargs
) -> deltalite.HistoryUpsertStats:
    data = source_table(rows)
    if split_rng is not None:
        data = split_into_batches(data, split_rng)
    return deltalite.DeltaLiteTable.open(uri).history_upsert(
        data, ["id", "n"], "ts", "ts", "valid_to", "p", CURRENT, "seq", **kwargs
    )


# Instants on both sides of month boundaries, so chains and closes cross partitions.
INSTANTS = sorted(
    {datetime.fromisoformat(v["valid_to"].replace("Z", "+00:00")) for v in MONTH_VECTORS}
    | {datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=13 * i, hours=i) for i in range(10)}
)


@pytest.mark.parametrize("seed", range(60))
def test_matches_the_reference_model_over_random_calls(tmp_path, seed):
    rng = random.Random(seed)
    uri = create(tmp_path)
    keys = [(rng.choice(["a", "b", "c", None]), rng.choice([1, 2, None])) for _ in range(rng.randint(1, 8))]
    small_files = rng.random() < 0.5
    # Its own generator, so the batch cuts do not change the rows each seed generates.
    split_rng = random.Random(f"split-{seed}")
    expected: list[Row] = []
    seq = 0
    for call in range(rng.randint(2, 5)):
        source = []
        for _ in range(rng.randint(0, 25)):
            seq += 1
            key = rng.choice(keys)
            source.append(Src(key[0], key[1], rng.choice(INSTANTS), f"s{seed}-c{call}-{seq}", rng.randint(0, 10**6)))
        expected, counts = model_apply(expected, source)
        stats = history_upsert(
            uri,
            source,
            split_rng,
            **({"target_file_size": 2048, "read_batch_size": 3} if small_files else {}),
        )
        got = Counts(
            stats.committed,
            stats.rows_reread,
            stats.rows_backwards,
            stats.versions_opened,
            stats.versions_closed,
            stats.chain_rows_closed,
        )
        assert got == counts, f"call {call}: {stats!r}"
        assert read(uri) == expected, f"call {call}"


def test_month_vectors_match_the_product_month_and_the_written_partitions(tmp_path):
    instants = [datetime.fromisoformat(v["valid_to"].replace("Z", "+00:00")) for v in MONTH_VECTORS]
    assert [month(i) for i in instants] == [v["month"] for v in MONTH_VECTORS]

    uri = create(tmp_path)
    opened_at = datetime(1960, 1, 1, tzinfo=UTC)
    history_upsert(uri, [Src(f"k{i}", 1, opened_at, "old", 1) for i in range(len(instants))])
    history_upsert(uri, [Src(f"k{i}", 1, instant, "new", 2) for i, instant in enumerate(instants)])
    closed = {r.id: r.p for r in read(uri) if r.valid_to is not None}
    assert closed == {f"k{i}": v["month"] for i, v in enumerate(MONTH_VECTORS)}


@pytest.mark.parametrize("partition_by", [[], ["id"]])
def test_refuses_a_table_not_partitioned_by_the_history_column(tmp_path, partition_by):
    uri = create(tmp_path, partition_by)
    with pytest.raises(deltalite.DeltaLiteUnsupportedTableError):
        history_upsert(uri, [Src("a", 1, INSTANTS[0], "a", 1)])


def test_key_buckets_are_null_safe_and_independent_of_batching(tmp_path):
    table = deltalite.DeltaLiteTable.open(create(tmp_path))
    data = pa.table(
        {
            "id": pa.array(["a", "b", None, "a", "customer-42"], pa.string()),
            "n": pa.array([1, 1, 1, None, 7], pa.int64()),
        }
    )
    buckets = table.key_buckets(data, ["id", "n"], 16)
    assert isinstance(buckets, pa.UInt32Array)
    # Pinned in the Rust suite too, so an encoding change shows up on the upgrade that makes it.
    assert buckets.to_pylist() == [4, 12, 0, 6, 6]
    rechunked = pa.Table.from_batches(data.slice(3).to_batches() + data.slice(0, 3).to_batches())
    assert table.key_buckets(rechunked, ["id", "n"], 16).to_pylist() == [6, 6, 4, 12, 0]


def test_calls_split_by_key_bucket_equal_one_call_when_source_keys_need_a_cast(tmp_path):
    # "1", "01" and "001" are one integer key in the table, so they must share a bucket.
    def source(n_values: list[str]) -> pa.Table:
        rows = len(n_values)
        return pa.table(
            {
                "id": pa.array(["k"] * 3 + [f"other-{i}" for i in range(rows - 3)], pa.string()),
                "n": pa.array(n_values, pa.string()),
                "ts": pa.array(INSTANTS[:rows], TS),
                "payload": pa.array([f"p{i}" for i in range(rows)], pa.string()),
                "seq": pa.array(range(rows), pa.int64()),
            }
        )

    data = source(["1", "01", "001", *(str(i) for i in range(2, 12))])
    whole_uri, split_uri = create(tmp_path / "whole"), create(tmp_path / "split")
    args = (["id", "n"], "ts", "ts", "valid_to", "p", CURRENT, "seq")
    deltalite.DeltaLiteTable.open(whole_uri).history_upsert(data, *args)

    split = deltalite.DeltaLiteTable.open(split_uri)
    buckets = split.key_buckets(data, ["id", "n"], 8)
    assert len(set(buckets.to_pylist()[:3])) == 1
    # Any call order must give the same table; descending is as good as any.
    for bucket in sorted(set(buckets.to_pylist()), reverse=True):
        split.history_upsert(data.filter(pc.equal(buckets, bucket)), *args)

    assert read(split_uri) == read(whole_uri)
