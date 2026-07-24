"""Shared harness: data generation, the two write paths, and logical comparison.

The `merge_path` function is a faithful transcription of the production incremental
branch of `DeltaTableHelper.write_to_deltalake` (per-partition merge loop with
`streamed_exec=True`, single merge with `streamed_exec=False` when unpartitioned, only
the final commit tagged), so parity assertions compare against what actually ships.
"""

from __future__ import annotations

import random
import shutil
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import deltalake
import pyarrow.compute as pc

PARTITION_KEY = "_ph_partition_key"


# --------------------------------------------------------------------------------------
# Source-batch preparation (must be identical for both paths)
# --------------------------------------------------------------------------------------


def dedupe_keep_last(table: pa.Table, primary_keys: list[str], partition_key: str | None) -> pa.Table:
    """Intra-batch keep-last dedup per (PKs, partition), mirroring
    `_dedupe_incremental_batch`.

    Rows carrying a NULL in any PK column are exempt: SQL `NULL != NULL` means they can
    never collide with anything, so they must all survive rather than collapse into one.
    """
    if table.num_rows == 0:
        return table
    keys = list(primary_keys) + ([partition_key] if partition_key else [])

    null_mask = None
    for k in primary_keys:
        m = pc.is_null(table[k])
        null_mask = m if null_mask is None else pc.or_(null_mask, m)

    idx = pa.array(range(table.num_rows), pa.int64())
    with_idx = table.append_column("__idx", idx)

    nullable_rows = with_idx.filter(null_mask)
    keyed_rows = with_idx.filter(pc.invert(null_mask))

    if keyed_rows.num_rows:
        grouped = keyed_rows.group_by(keys).aggregate([("__idx", "max")])
        keep = set(grouped["__idx_max"].to_pylist())
        mask = pa.array([i in keep for i in keyed_rows["__idx"].to_pylist()])
        keyed_rows = keyed_rows.filter(mask)

    out = pa.concat_tables([keyed_rows, nullable_rows])
    out = out.sort_by([("__idx", "ascending")])
    return out.drop(["__idx"])


# --------------------------------------------------------------------------------------
# The two write paths
# --------------------------------------------------------------------------------------


def evolve_schema(uri: str, batch: pa.Table, storage_options: dict[str, str] | None = None) -> None:
    """Additive schema evolution, mirroring `_evolve_delta_schema`."""
    dt = deltalake.DeltaTable(uri, storage_options=storage_options)
    existing = {f.name for f in dt.schema().fields}
    new_fields = [deltalake.Field.from_arrow(batch.schema.field(n)) for n in batch.schema.names if n not in existing]
    if new_fields:
        dt.alter.add_columns(new_fields)


def merge_path(
    uri: str,
    batch: pa.Table,
    primary_keys: list[str],
    partition_key: str | None,
    commit_metadata: dict[str, str] | None = None,
    storage_options: dict[str, str] | None = None,
) -> None:
    """delta-rs SQL MERGE, exactly as the production helper drives it."""
    evolve_schema(uri, batch, storage_options)
    dt = deltalake.DeltaTable(uri, storage_options=storage_options)

    props = deltalake.CommitProperties(custom_metadata=commit_metadata) if commit_metadata else None

    if partition_key:
        partitions = sorted(set(batch[partition_key].to_pylist()))
        if not partitions:
            return
        for i, p in enumerate(partitions):
            part_batch = batch.filter(pc.equal(batch[partition_key], p))
            pred = " AND ".join(
                [f"source.{k} = target.{k}" for k in primary_keys]
                + [f"source.{partition_key} = target.{partition_key}"]
                + [f"target.{partition_key} = '{p}'"]
            )
            # Only the terminal commit of the batch carries the idempotency tag.
            is_last = i == len(partitions) - 1
            (
                dt.merge(
                    source=part_batch,
                    source_alias="source",
                    target_alias="target",
                    predicate=pred,
                    streamed_exec=True,
                    commit_properties=props if (is_last and props) else None,
                )
                .when_matched_update_all()
                .when_not_matched_insert_all()
                .execute()
            )
            dt = deltalake.DeltaTable(uri, storage_options=storage_options)
    else:
        pred = " AND ".join(f"source.{k} = target.{k}" for k in primary_keys)
        (
            dt.merge(
                source=batch,
                source_alias="source",
                target_alias="target",
                predicate=pred,
                streamed_exec=False,
                commit_properties=props,
            )
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute()
        )


def upsert_path(
    uri: str,
    batch: pa.Table,
    primary_keys: list[str],
    partition_key: str | None,
    commit_metadata: dict[str, str] | None = None,
    storage_options: dict[str, str] | None = None,
    **kwargs: Any,
) -> Any:
    """deltalite streaming partition upsert."""
    import deltalite

    evolve_schema(uri, batch, storage_options)
    t = deltalite.DeltaLiteTable.open(uri, storage_options)
    return t.upsert(
        batch,
        primary_keys,
        partition_key,
        commit_metadata=commit_metadata,
        **kwargs,
    )


# --------------------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------------------


def read_sorted(uri: str, storage_options: dict[str, str] | None = None) -> tuple[list[tuple], list[tuple[str, str]]]:
    """Full logical content as a sorted list of row tuples, plus the schema."""
    dt = deltalake.DeltaTable(uri, storage_options=storage_options)
    tbl = dt.to_pyarrow_table()
    names = sorted(tbl.schema.names)
    tbl = tbl.select(names)
    cols = [tbl.column(n).to_pylist() for n in names]
    rows = list(zip(*cols)) if cols else []
    # Sort on a total order that tolerates NULLs and mixed types.
    rows.sort(key=lambda r: tuple((v is None, str(v)) for v in r))
    schema = [(f.name, str(f.type)) for f in tbl.schema]
    return rows, sorted(schema)


def assert_parity(
    uri_merge: str,
    uri_upsert: str,
    label: str,
    storage_options: dict[str, str] | None = None,
) -> None:
    rows_m, schema_m = read_sorted(uri_merge, storage_options)
    rows_u, schema_u = read_sorted(uri_upsert, storage_options)

    assert schema_m == schema_u, f"[{label}] schema mismatch\n  merge : {schema_m}\n  upsert: {schema_u}"
    if rows_m != rows_u:
        only_m = [r for r in rows_m if r not in rows_u][:5]
        only_u = [r for r in rows_u if r not in rows_m][:5]
        raise AssertionError(
            f"[{label}] content mismatch: merge has {len(rows_m)} rows, "
            f"upsert has {len(rows_u)}\n"
            f"  only in merge : {only_m}\n"
            f"  only in upsert: {only_u}"
        )


# --------------------------------------------------------------------------------------
# Scenario driver
# --------------------------------------------------------------------------------------


@dataclass
class Scenario:
    name: str
    initial: pa.Table
    batches: list[pa.Table]
    primary_keys: list[str]
    partitioned: bool = True

    @property
    def partition_key(self) -> str | None:
        return PARTITION_KEY if self.partitioned else None


def create_table(
    uri: str,
    data: pa.Table,
    partitioned: bool,
    storage_options: dict[str, str] | None = None,
) -> None:
    if "://" not in uri and Path(uri).exists():
        shutil.rmtree(uri)
    deltalake.write_deltalake(
        uri,
        data,
        partition_by=[PARTITION_KEY] if partitioned else None,
        mode="overwrite",
        storage_options=storage_options,
    )


def run_scenario(
    scenario: Scenario,
    tmp: Path | str,
    storage_options: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Apply the same batch sequence to two fresh tables via the two paths.

    `tmp` may be a local directory Path or a remote base URI string (e.g.
    ``s3://bucket/prefix``); table URIs are appended to it either way.
    """
    if isinstance(tmp, Path):
        uri_m = str(tmp / f"{scenario.name}_merge")
        uri_u = str(tmp / f"{scenario.name}_upsert")
    else:
        uri_m = f"{tmp.rstrip('/')}/{scenario.name}_merge"
        uri_u = f"{tmp.rstrip('/')}/{scenario.name}_upsert"
    create_table(uri_m, scenario.initial, scenario.partitioned, storage_options)
    create_table(uri_u, scenario.initial, scenario.partitioned, storage_options)

    for i, raw in enumerate(scenario.batches):
        batch = dedupe_keep_last(raw, scenario.primary_keys, scenario.partition_key)
        md = {"run_uuid": "run-1", "batch_index": str(i)}
        merge_path(
            uri_m,
            batch,
            scenario.primary_keys,
            scenario.partition_key,
            md,
            storage_options=storage_options,
        )
        upsert_path(
            uri_u,
            batch,
            scenario.primary_keys,
            scenario.partition_key,
            md,
            storage_options=storage_options,
        )

    return uri_m, uri_u


# --------------------------------------------------------------------------------------
# Data generation
# --------------------------------------------------------------------------------------

_WORDS = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]


def big_string(rng: random.Random, size: int = 4500) -> str:
    """A JSON-ish blob, so rows land around the ~5 KB the real workload sees."""
    parts = []
    n = 0
    while n < size:
        k = rng.choice(_WORDS)
        v = "".join(rng.choices(string.ascii_letters + string.digits, k=24))
        chunk = f'"{k}_{rng.randint(0, 9999)}": "{v}"'
        parts.append(chunk)
        n += len(chunk) + 2
    return "{" + ", ".join(parts) + "}"


def wide_schema() -> pa.Schema:
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


def gen_wide(
    ids: list[str],
    partition: str,
    seed: int = 0,
    payload_size: int = 4500,
    version: int = 1,
) -> pa.Table:
    """Wide ~5 KB rows: string PK, ints, timestamps, a decimal, a large JSON-ish string."""
    import datetime as _dt

    rng = random.Random(seed)
    n = len(ids)
    base = _dt.datetime(2026, 1, 1)
    return pa.table(
        {
            "id": pa.array(ids, pa.string()),
            "tenant": pa.array([rng.randint(1, 50) for _ in range(n)], pa.int64()),
            "counter": pa.array([version] * n, pa.int32()),
            "created_at": pa.array([base] * n, pa.timestamp("us")),
            "updated_at": pa.array([base + _dt.timedelta(seconds=version)] * n, pa.timestamp("us")),
            "amount": pa.array(
                [
                    __import__("decimal").Decimal(f"{rng.randint(0, 10**6)}.{rng.randint(0, 10**9):09d}")
                    for _ in range(n)
                ],
                pa.decimal128(38, 10),
            ),
            "payload": pa.array([big_string(rng, payload_size) for _ in range(n)], pa.string()),
            PARTITION_KEY: pa.array([partition] * n, pa.string()),
        },
        schema=wide_schema(),
    )


def uuid_ids(n: int, offset: int = 0, seed: int = 0) -> list[str]:
    """Deterministic UUID-shaped primary keys."""
    rng = random.Random(seed)
    _ = rng
    return [f"{i:08x}-0000-4000-8000-{i:012x}" for i in range(offset, offset + n)]
