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


# Late rows and redeliveries (`late_rows`, `dedupe_column`): webhook-shaped versions,
# ordered by (ts, rank, arr), where `arr` is the arrival sequence and `eid` the event id.
EVENT_TABLE_SCHEMA = pa.schema(
    [
        pa.field("id", pa.string()),
        pa.field("ts", TS),
        pa.field("rank", pa.int64()),
        pa.field("arr", pa.int64()),
        pa.field("eid", pa.string()),
        pa.field("payload", pa.string()),
        pa.field("valid_to", TS),
        pa.field("p", pa.string(), nullable=False),
    ]
)
EVENT_SOURCE_SCHEMA = pa.schema(
    [
        pa.field("id", pa.string()),
        pa.field("ts", TS),
        pa.field("rank", pa.int64()),
        pa.field("arr", pa.int64()),
        pa.field("eid", pa.string()),
        pa.field("payload", pa.string()),
        pa.field("seq", pa.int64()),
    ]
)


@dataclasses.dataclass(frozen=True)
class Event:
    id: str | None
    ts: datetime
    rank: int
    arr: int
    eid: str
    payload: str
    seq: int


@dataclasses.dataclass(frozen=True)
class Version:
    p: str
    id: str | None
    ts: datetime
    rank: int
    arr: int
    eid: str
    valid_to: datetime | None
    payload: str


@dataclasses.dataclass(frozen=True)
class LateCounts:
    committed: bool
    rows_deduped: int
    rows_reread: int
    rows_backwards: int
    rows_late: int
    rows_redelivered: int
    versions_opened: int
    versions_closed: int
    versions_split: int
    chain_rows_closed: int


@dataclasses.dataclass(frozen=True)
class Mode:
    late_rows: str
    dedupe: bool
    order: tuple[str, ...]


def _order_of(x: Event | Version, columns: tuple[str, ...]) -> tuple:
    return tuple(getattr(x, c) for c in columns)


def late_model_apply(rows: list[Version], source: list[Event], mode: Mode) -> tuple[list[Version], LateCounts]:
    """Reference model of `history_upsert` with `late_rows` and `dedupe_column`."""
    key = lambda x: x.id  # noqa: E731
    order = lambda x: _order_of(x, mode.order)  # noqa: E731
    counts = dict.fromkeys(
        ["deduped", "reread", "backwards", "late", "redelivered", "opened", "closed", "split", "chained"], 0
    )

    by_key: dict[str | None, list[Event]] = {}
    for s in source:
        by_key.setdefault(key(s), []).append(s)
    out = list(rows)
    for k, events in by_key.items():
        events = sorted(events, key=lambda s: (order(s), s.seq))
        if mode.dedupe:
            first: list[Event] = []
            for s in events:
                if any(f.eid == s.eid for f in first):
                    counts["redelivered"] += 1
                else:
                    first.append(s)
            events = first
        else:
            best: dict[tuple, Event] = {}
            for s in events:
                best[order(s)] = s  # sorted by seq, so the last wins
            counts["deduped"] += len(events) - len(best)
            events = sorted(best.values(), key=lambda s: (order(s), s.seq))

        old = sorted(
            (r for r in out if r.id == k),
            key=lambda r: (order(r), r.valid_to is None, r.valid_to or r.ts),
        )
        if mode.dedupe:
            held = {r.eid for r in old}
            counts["redelivered"] += sum(s.eid in held for s in events)
            events = [s for s in events if s.eid not in held]
        else:
            held_orders = {order(r) for r in old}
            counts["reread"] += sum(order(s) in held_orders for s in events)
            events = [s for s in events if order(s) not in held_orders]
        open_row = next((r for r in reversed(old) if r.valid_to is None), None)
        new: list[tuple[Event, bool]] = []
        for s in events:
            late = open_row is not None and order(s) < order(open_row)
            if not late:
                new.append((s, False))
            elif mode.late_rows == "insert":
                counts["late"] += 1
                new.append((s, True))
            else:
                counts["backwards"] += 1
        if not new:
            continue

        elems: list[tuple] = [(order(r), 0, i, r, False) for i, r in enumerate(old)]
        elems += [(order(s), 1, i, s, late) for i, (s, late) in enumerate(new)]
        elems.sort(key=lambda e: (e[0], e[1], e[2]))
        for this, following in zip(elems, [*elems[1:], None]):
            item, is_new, late = this[3], this[1] == 1, this[4]
            if is_new:
                to = following[3].ts if following else None
                out.append(
                    Version(
                        month(to) if to else CURRENT, item.id, item.ts, item.rank, item.arr, item.eid, to, item.payload
                    )
                )
                if following is None:
                    counts["opened"] += 1
                elif not late:
                    counts["chained"] += 1
            elif following is not None and following[1] == 1:
                to = following[3].ts
                if item.valid_to is None:
                    counts["closed"] += 1
                elif item.valid_to == to:
                    continue
                else:
                    counts["split"] += 1
                out.remove(item)
                out.append(dataclasses.replace(item, valid_to=to, p=month(to)))
    committed = counts["opened"] + counts["late"] > 0
    return sorted(out, key=_version_order), LateCounts(
        committed,
        counts["deduped"],
        counts["reread"],
        counts["backwards"],
        counts["late"],
        counts["redelivered"],
        counts["opened"],
        counts["closed"],
        counts["split"],
        counts["chained"],
    )


def _version_order(r: Version) -> tuple:
    return (r.p, r.id or "", r.id is None, r.ts, r.rank, r.arr, r.eid, r.valid_to or r.ts, r.payload)


def read_versions(uri: str) -> list[Version]:
    t = deltalake.DeltaTable(uri).to_pyarrow_table()
    return sorted(
        (
            Version(d["p"], d["id"], d["ts"], d["rank"], d["arr"], d["eid"], d["valid_to"], d["payload"])
            for d in t.to_pylist()
        ),
        key=_version_order,
    )


def event_source(rows: list[Event]) -> pa.Table:
    return pa.Table.from_pylist([dataclasses.asdict(r) for r in rows], schema=EVENT_SOURCE_SCHEMA)


def create_events(tmp_path: Path) -> str:
    uri = str(tmp_path / "events")
    deltalake.DeltaTable.create(uri, schema=EVENT_TABLE_SCHEMA, partition_by=["p"])
    return uri


def late_upsert(uri: str, rows: list[Event], mode: Mode, **kwargs) -> deltalite.HistoryUpsertStats:
    return deltalite.DeltaLiteTable.open(uri).history_upsert(
        event_source(rows),
        ["id"],
        list(mode.order),
        "ts",
        "valid_to",
        "p",
        CURRENT,
        "seq",
        late_rows=mode.late_rows,
        dedupe_column="eid" if mode.dedupe else None,
        **kwargs,
    )


def late_counts(stats: deltalite.HistoryUpsertStats) -> LateCounts:
    return LateCounts(
        stats.committed,
        stats.rows_deduped,
        stats.rows_reread,
        stats.rows_backwards,
        stats.rows_late,
        stats.rows_redelivered,
        stats.versions_opened,
        stats.versions_closed,
        stats.versions_split,
        stats.chain_rows_closed,
    )


WEBHOOK = Mode("insert", True, ("ts", "rank", "arr"))
MODES = {
    "webhook": WEBHOOK,
    "insert_dedupe_time_only": Mode("insert", True, ("ts",)),
    "insert_without_dedupe": Mode("insert", False, ("ts",)),
    "drop_with_dedupe": Mode("drop", True, ("ts", "rank", "arr")),
}


@pytest.mark.parametrize("mode_name", sorted(MODES))
@pytest.mark.parametrize("seed", range(40))
def test_late_rows_match_the_reference_model_over_random_calls(tmp_path, seed, mode_name):
    mode = MODES[mode_name]
    rng = random.Random(f"{mode_name}-{seed}")
    uri = create_events(tmp_path)
    keys = [rng.choice(["a", "b", "c", None]) for _ in range(rng.randint(1, 5))]
    instants = rng.sample(INSTANTS, rng.randint(2, len(INSTANTS)))
    small_files = rng.random() < 0.5
    expected: list[Version] = []
    delivered: list[Event] = []
    arrival = 0
    previous: list[Event] = []
    for call in range(rng.randint(2, 6)):
        if previous and rng.random() < 0.2:
            source = previous  # a re-run of the same input
        else:
            source = []
            for _ in range(rng.randint(0, 12)):
                arrival += 1
                if delivered and rng.random() < 0.25:
                    again = rng.choice(delivered)
                    source.append(dataclasses.replace(again, arr=arrival, seq=arrival))
                else:
                    source.append(
                        Event(
                            rng.choice(keys),
                            rng.choice(instants),
                            rng.randint(0, 2),
                            arrival,
                            f"e{arrival}",
                            f"s{seed}-c{call}-{arrival}",
                            arrival,
                        )
                    )
            delivered.extend(source)
        expected, counts = late_model_apply(expected, source, mode)
        stats = late_upsert(
            uri, source, mode, **({"target_file_size": 2048, "read_batch_size": 3} if small_files else {})
        )
        assert late_counts(stats) == counts, f"call {call}: {stats!r}"
        assert read_versions(uri) == expected, f"call {call}"
        if source is previous:
            assert not stats.committed
        previous = source


def _event(id: str, ts: str, eid: str, *, arr: int, rank: int = 0) -> Event:
    return Event(id, datetime.fromisoformat(ts).replace(tzinfo=UTC), rank, arr, eid, eid, arr)


def _version(id: str, ts: str, to: str | None, eid: str, *, arr: int, rank: int = 0) -> Version:
    start = datetime.fromisoformat(ts).replace(tzinfo=UTC)
    end = datetime.fromisoformat(to).replace(tzinfo=UTC) if to else None
    return Version(month(end) if end else CURRENT, id, start, rank, arr, eid, end, eid)


def test_a_late_event_splits_the_version_that_covers_it_across_months(tmp_path):
    uri = create_events(tmp_path)
    late_upsert(uri, [_event("k", "2026-10-10", "e1", arr=1), _event("k", "2026-12-12", "e2", arr=2)], WEBHOOK)

    stats = late_upsert(uri, [_event("k", "2026-11-11", "e3", arr=3)], WEBHOOK)

    assert (stats.rows_late, stats.versions_split, stats.versions_opened) == (1, 1, 0)
    assert read_versions(uri) == sorted(
        [
            _version("k", "2026-10-10", "2026-11-11", "e1", arr=1),
            _version("k", "2026-11-11", "2026-12-12", "e3", arr=3),
            _version("k", "2026-12-12", None, "e2", arr=2),
        ],
        key=_version_order,
    )
    assert not late_upsert(uri, [_event("k", "2026-11-11", "e3", arr=4)], WEBHOOK).committed


def test_a_late_event_older_than_the_first_version_ends_at_it(tmp_path):
    uri = create_events(tmp_path)
    late_upsert(uri, [_event("k", "2026-10-10", "e1", arr=1)], WEBHOOK)

    stats = late_upsert(uri, [_event("k", "2026-08-08", "e0", arr=2)], WEBHOOK)

    assert (stats.rows_late, stats.versions_split) == (1, 0)
    assert read_versions(uri) == sorted(
        [_version("k", "2026-08-08", "2026-10-10", "e0", arr=2), _version("k", "2026-10-10", None, "e1", arr=1)],
        key=_version_order,
    )


def test_two_events_at_one_instant_are_two_versions_and_the_earlier_arrival_is_zero_length(tmp_path):
    uri = create_events(tmp_path)
    late_upsert(uri, [_event("k", "2026-10-10", "e1", arr=1)], WEBHOOK)

    stats = late_upsert(uri, [_event("k", "2026-10-10", "e2", arr=2)], WEBHOOK)

    assert (stats.rows_reread, stats.versions_closed, stats.versions_opened) == (0, 1, 1)
    assert read_versions(uri) == sorted(
        [_version("k", "2026-10-10", "2026-10-10", "e1", arr=1), _version("k", "2026-10-10", None, "e2", arr=2)],
        key=_version_order,
    )


def test_drop_mode_without_options_keeps_the_incremental_rules(tmp_path):
    uri = create_events(tmp_path)
    mode = Mode("drop", False, ("ts",))
    late_upsert(uri, [_event("k", "2026-10-10", "e1", arr=1)], mode)

    stats = late_upsert(uri, [_event("k", "2026-09-09", "e0", arr=2), _event("k", "2026-10-10", "e2", arr=3)], mode)

    assert (stats.rows_backwards, stats.rows_reread, stats.committed) == (1, 1, False)


def test_rejects_an_unknown_late_rows_value_and_a_null_event_id(tmp_path):
    uri = create_events(tmp_path)
    with pytest.raises(deltalite.DeltaLiteError, match="late_rows"):
        late_upsert(uri, [_event("k", "2026-10-10", "e1", arr=1)], Mode("keep", True, ("ts",)))
    data = event_source([_event("k", "2026-10-10", "e1", arr=1)]).set_column(4, "eid", pa.array([None], pa.string()))
    with pytest.raises(deltalite.DeltaLiteError, match="dedupe"):
        deltalite.DeltaLiteTable.open(uri).history_upsert(
            data, ["id"], ["ts"], "ts", "valid_to", "p", CURRENT, "seq", late_rows="insert", dedupe_column="eid"
        )


MAIN_SCHEMA = pa.schema(
    [
        pa.field("id", pa.string()),
        pa.field("ts", TS),
        pa.field("rank", pa.int64()),
        pa.field("arr", pa.int64()),
        pa.field("payload", pa.string()),
    ]
)


@pytest.mark.parametrize("seed", range(30))
def test_the_upsert_order_guard_keeps_the_newest_row_per_key(tmp_path, seed):
    rng = random.Random(f"guard-{seed}")
    uri = str(tmp_path / "main")
    deltalake.DeltaTable.create(uri, schema=MAIN_SCHEMA)
    expected: dict[str | None, dict] = {}
    nulls: list[dict] = []
    arrival = 0
    for call in range(rng.randint(2, 6)):
        keys = rng.sample(["a", "b", "c", "d", "e", None], rng.randint(1, 6))
        batch = []
        for k in keys:
            arrival += 1
            batch.append(
                {
                    "id": k,
                    "ts": rng.choice(INSTANTS[:4]),
                    "rank": rng.randint(0, 1),
                    "arr": arrival,
                    "payload": f"c{call}-{k}",
                }
            )
        if rng.random() < 0.3:
            # A late redelivery: an older arrival of a row the table already holds.
            held = [r for r in expected.values() if r["arr"] < arrival]
            if held:
                old = dict(rng.choice(held), payload="redelivered")
                batch = [r for r in batch if r["id"] != old["id"]] + [old]
        skipped = 0
        for row in batch:
            if row["id"] is None:
                nulls.append(row)
                continue
            stored = expected.get(row["id"])
            order = (row["ts"], row["rank"], row["arr"])
            if stored is not None and order < (stored["ts"], stored["rank"], stored["arr"]):
                skipped += 1
            else:
                expected[row["id"]] = row
        stats = deltalite.DeltaLiteTable.open(uri).upsert(
            pa.Table.from_pylist(batch, schema=MAIN_SCHEMA),
            ["id"],
            order_column=["ts", "rank", "arr"],
            **({"target_file_size": 1024, "read_batch_size": 2} if seed % 2 else {}),
        )
        assert stats.rows_older_than_main == skipped, f"call {call}"
        assert stats.rows_updated + stats.rows_inserted + skipped == len(batch)
        got = sorted(deltalake.DeltaTable(uri).to_pyarrow_table().to_pylist(), key=lambda r: (r["id"] or "", r["arr"]))
        want = sorted([*expected.values(), *nulls], key=lambda r: (r["id"] or "", r["arr"]))
        assert got == want, f"call {call}"


def test_the_upsert_order_guard_refuses_a_null_order_value_before_any_commit(tmp_path):
    uri = str(tmp_path / "main")
    strict = pa.schema([f.with_nullable(False) if f.name == "ts" else f for f in MAIN_SCHEMA])
    deltalake.DeltaTable.create(uri, schema=strict)
    data = pa.Table.from_pylist([{"id": "a", "ts": None, "rank": 0, "arr": 1, "payload": "x"}], schema=MAIN_SCHEMA)
    table = deltalite.DeltaLiteTable.open(uri)
    with pytest.raises(deltalite.DeltaLiteError, match="null"):
        table.upsert(data, ["id"], order_column="ts")
    assert deltalake.DeltaTable(uri).version() == 0, "no nullability relax commit"
