"""Fast generation of wide-row Delta tables that model the production workload.

Rows carry a UUID-shaped string PK, a couple of ints, two timestamps, a decimal, and a
large JSON-ish string column. Payloads are cut from a big random pool with a unique
per-row prefix so Parquet cannot dictionary-encode them away -- otherwise the benchmark
would understate both file size and decompressed memory.
"""

from __future__ import annotations

import json
import random
import shutil
import string
import datetime as dt
from pathlib import Path

import pyarrow as pa
import deltalake

PARTITION_KEY = "_ph_partition_key"

_POOL: str | None = None


def _pool(size: int = 1 << 20) -> str:
    global _POOL
    if _POOL is None or len(_POOL) < size:
        rng = random.Random(1234)
        _POOL = "".join(rng.choices(string.ascii_letters + string.digits, k=size))
    return _POOL


def schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("id", pa.string()),
            pa.field("tenant", pa.int64()),
            pa.field("counter", pa.int32()),
            pa.field("created_at", pa.timestamp("us")),
            pa.field("updated_at", pa.timestamp("us")),
            pa.field("amount", pa.decimal128(38, 10)),
            pa.field("payload", pa.string()),
            pa.field(PARTITION_KEY, pa.string()),
        ]
    )


def pk(i: int) -> str:
    return f"{i:08x}-0000-4000-8000-{i:012x}"


def make_batch(
    start: int,
    n: int,
    partition: str,
    payload_size: int = 4500,
    version: int = 1,
) -> pa.Table:
    import decimal

    pool = _pool()
    plen = len(pool)
    base = dt.datetime(2026, 1, 1)

    ids = [pk(i) for i in range(start, start + n)]
    payloads = []
    for i in range(start, start + n):
        off = (i * 7919) % (plen - payload_size - 1)
        payloads.append(f'{{"row":{i},"v":{version},"d":"' + pool[off : off + payload_size] + '"}')

    return pa.table(
        {
            "id": pa.array(ids, pa.string()),
            "tenant": pa.array([(i % 50) + 1 for i in range(start, start + n)], pa.int64()),
            "counter": pa.array([version] * n, pa.int32()),
            "created_at": pa.array([base] * n, pa.timestamp("us")),
            "updated_at": pa.array([base + dt.timedelta(seconds=version)] * n, pa.timestamp("us")),
            "amount": pa.array(
                [decimal.Decimal(f"{i % 1000000}.{(i * 37) % 10**9:09d}") for i in range(start, start + n)],
                pa.decimal128(38, 10),
            ),
            "payload": pa.array(payloads, pa.string()),
            PARTITION_KEY: pa.array([partition] * n, pa.string()),
        },
        schema=schema(),
    )


def build_table(
    uri: str,
    partitions: dict[str, int],
    payload_size: int = 4500,
    partitioned: bool = True,
    chunk: int = 25_000,
    files_per_partition: int | None = None,
) -> None:
    """Create a table with `partitions` mapping partition value -> row count.

    `files_per_partition` forces fragmentation by splitting each partition's rows across
    that many separate append commits.
    """
    p = Path(uri)
    if p.exists():
        shutil.rmtree(p)

    offset = 0
    first = True
    for part, rows in partitions.items():
        if files_per_partition:
            per = max(1, rows // files_per_partition)
            steps = [per] * files_per_partition
            steps[-1] += rows - per * files_per_partition
        else:
            steps = []
            remaining = rows
            while remaining > 0:
                steps.append(min(chunk, remaining))
                remaining -= chunk

        for step in steps:
            if step <= 0:
                continue
            batch = make_batch(offset, step, part, payload_size=payload_size)
            deltalake.write_deltalake(
                uri,
                batch,
                partition_by=[PARTITION_KEY] if partitioned else None,
                mode="overwrite" if first else "append",
                schema_mode="overwrite" if first else None,
            )
            first = False
            offset += step


def make_upsert_batch(
    n_updates: int,
    n_inserts: int,
    partition: str,
    existing_rows: int,
    payload_size: int = 4500,
    version: int = 2,
) -> pa.Table:
    """Mostly-updates batch: `n_updates` existing PKs plus `n_inserts` brand-new ones."""
    step = max(1, existing_rows // max(1, n_updates))
    upd_ids = [i * step for i in range(n_updates) if i * step < existing_rows]

    parts = []
    if upd_ids:
        pool = _pool()
        plen = len(pool)
        import decimal

        base = dt.datetime(2026, 1, 1)
        payloads = []
        for i in upd_ids:
            off = (i * 104729) % (plen - payload_size - 1)
            payloads.append(f'{{"row":{i},"v":{version},"d":"' + pool[off : off + payload_size] + '"}')
        parts.append(
            pa.table(
                {
                    "id": pa.array([pk(i) for i in upd_ids], pa.string()),
                    "tenant": pa.array([(i % 50) + 1 for i in upd_ids], pa.int64()),
                    "counter": pa.array([version] * len(upd_ids), pa.int32()),
                    "created_at": pa.array([base] * len(upd_ids), pa.timestamp("us")),
                    "updated_at": pa.array(
                        [base + dt.timedelta(seconds=version)] * len(upd_ids),
                        pa.timestamp("us"),
                    ),
                    "amount": pa.array(
                        [decimal.Decimal(f"{i % 1000000}.{(i * 41) % 10**9:09d}") for i in upd_ids],
                        pa.decimal128(38, 10),
                    ),
                    "payload": pa.array(payloads, pa.string()),
                    PARTITION_KEY: pa.array([partition] * len(upd_ids), pa.string()),
                },
                schema=schema(),
            )
        )
    if n_inserts:
        parts.append(make_batch(10_000_000, n_inserts, partition, payload_size, version=version))
    return pa.concat_tables(parts)


# --------------------------------------------------------------------------------------
# Log inspection: write amplification accounting
# --------------------------------------------------------------------------------------


def commit_io(uri: str, version: int) -> dict:
    """Bytes/files added and removed by a single commit, read from the Delta log."""
    path = Path(uri) / "_delta_log" / f"{version:020d}.json"
    added_bytes = removed_bytes = 0
    added = removed = 0
    for line in path.read_text().splitlines():
        a = json.loads(line)
        if "add" in a:
            added += 1
            added_bytes += a["add"].get("size", 0)
        elif "remove" in a:
            removed += 1
            removed_bytes += a["remove"].get("size", 0) or 0
    return {
        "files_added": added,
        "files_removed": removed,
        "bytes_added": added_bytes,
        "bytes_removed": removed_bytes,
    }


def table_bytes(uri: str) -> int:
    return sum(Path(f.replace("file://", "")).stat().st_size for f in deltalake.DeltaTable(uri).file_uris())


def table_files(uri: str) -> int:
    return len(deltalake.DeltaTable(uri).file_uris())


def make_clustered_upsert_batch(
    n_updates: int,
    partition: str,
    existing_rows: int,
    payload_size: int = 4500,
    version: int = 2,
    fraction: float = 0.02,
) -> pa.Table:
    """Updates confined to a contiguous slice at the end of the key space.

    The uniform-spread batch touches every file, so MERGE gets no file-pruning benefit
    and the write-amplification comparison degenerates. Real syncs of a monotonic key
    (and any table whose files have disjoint key ranges) look like this instead: a few
    files hold every match. This is the shape where MERGE should win on bytes written,
    and where deltalite's PK-stats pruning has to earn its keep.
    """
    start = max(0, existing_rows - int(existing_rows * fraction))
    ids = list(range(start, min(start + n_updates, existing_rows)))
    return make_batch(ids[0], len(ids), partition, payload_size=payload_size, version=version)


def commit_io_range(uri: str, first_version: int, last_version: int) -> dict:
    """Sum commit_io over an inclusive version range.

    MERGE commits once per affected partition, so reading only the final version
    undercounts its write volume by the number of partitions touched. Any comparison of
    bytes/files written between the two paths must use this, not `commit_io`.
    """
    total = {"files_added": 0, "files_removed": 0, "bytes_added": 0, "bytes_removed": 0}
    for v in range(first_version, last_version + 1):
        try:
            one = commit_io(uri, v)
        except FileNotFoundError:
            continue
        for k in total:
            total[k] += one[k]
    total["commits"] = last_version - first_version + 1
    return total
