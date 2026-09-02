"""Content-based file selection (`prune_strategy="probe"`).

The probe reads only the PK column(s) of each candidate file and skips files with zero
matches, recovering MERGE's exact join-based rewrite set without a join. The tests here
weight the silent-corruption risk heaviest: a file that DOES contain a match must never
be skipped, under random UUID keys (where min/max stats prune nothing), NULL PKs,
composite PKs, schema evolution, and partitioned layouts. Parity against the real
delta-rs MERGE is the oracle throughout.
"""

from __future__ import annotations

import sys
import uuid
import random
import shutil
from pathlib import Path

import pytest

import pyarrow as pa
import deltalake

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.common import (  # noqa: E402
    PARTITION_KEY,
    assert_parity,
    dedupe_keep_last,
    merge_path,
    read_sorted,
    upsert_path,
)

N_FILES = 6
ROWS_PER_FILE = 300


def rand_ids(rng: random.Random, n: int) -> list[str]:
    return [str(uuid.UUID(int=rng.getrandbits(128), version=4)) for _ in range(n)]


def rows(ids, v, part="p1", tenant=None):
    n = len(ids)
    return pa.table(
        {
            "id": pa.array(ids, pa.string()),
            "tenant": pa.array(tenant if tenant is not None else [1] * n, pa.int64()),
            "v": pa.array([v] * n if isinstance(v, int) else v, pa.int64()),
            PARTITION_KEY: pa.array(part if isinstance(part, list) else [part] * n, pa.string()),
        }
    )


def build_multifile_table(
    uri: str,
    partitioned: bool = False,
    n_files: int = N_FILES,
    rows_per_file: int = ROWS_PER_FILE,
    partitions: list[str] | None = None,
    seed: int = 20260724,
) -> dict[str, list[list[str]]]:
    """One append per file, random UUID PKs, so min/max stats can prune nothing and we
    know exactly which ids live in which file. Returns partition -> per-file id lists."""
    rng = random.Random(seed)
    parts = partitions or ["p1"]
    per_file: dict[str, list[list[str]]] = {p: [] for p in parts}
    first = True
    for p in parts:
        for _ in range(n_files):
            ids = rand_ids(rng, rows_per_file)
            per_file[p].append(ids)
            deltalake.write_deltalake(
                uri,
                rows(ids, 1, part=p),
                partition_by=[PARTITION_KEY] if partitioned else None,
                mode="overwrite" if first else "append",
                schema_mode="overwrite" if first else None,
            )
            first = False
    return per_file


# --------------------------------------------------------------------------------------
# Exactness: rewrite exactly the matching files, never more, NEVER less
# --------------------------------------------------------------------------------------


def test_temporal_locality_rewrites_only_the_matching_file(tmp_path):
    """The production shape: random UUID keys, updates re-touching recently written
    rows. min/max stats prune nothing; the probe must find the single matching file."""
    base = tmp_path / "base"
    ids = build_multifile_table(str(base))["p1"]
    # updates all live in the newest file
    batch_ids = random.Random(7).sample(ids[-1], 50)

    uri_m, uri_u = str(tmp_path / "m"), str(tmp_path / "u")
    for uri in (uri_m, uri_u):
        shutil.copytree(base, uri)
    batch = rows(batch_ids, 2)
    merge_path(uri_m, batch, ["id"], None)
    stats = upsert_path(uri_u, batch, ["id"], None, prune_strategy="probe")
    assert_parity(uri_m, uri_u, "temporal_locality")

    assert stats.files_removed == 1
    assert stats.files_carried_over == N_FILES - 1
    assert stats.files_probed == N_FILES
    assert stats.rows_updated == 50


@pytest.mark.parametrize("target_file", range(N_FILES))
def test_never_skips_a_file_containing_a_match(tmp_path, target_file):
    """The silent-corruption case: a single update whose row lives in file
    `target_file` must always cause exactly that file to be rewritten."""
    ids: list[list[str]] = []

    def build(uri):
        nonlocal ids
        ids = build_multifile_table(uri)["p1"]

    base = tmp_path / "base"
    build(str(base))
    victim = ids[target_file][ROWS_PER_FILE // 2]

    uri_m, uri_u = str(tmp_path / "m"), str(tmp_path / "u")
    for uri in (uri_m, uri_u):
        shutil.copytree(base, uri)
    batch = rows([victim], 99)
    merge_path(uri_m, batch, ["id"], None)
    stats = upsert_path(uri_u, batch, ["id"], None, prune_strategy="probe")
    assert_parity(uri_m, uri_u, f"single_hit_file_{target_file}")

    assert stats.files_removed == 1
    assert stats.files_carried_over == N_FILES - 1
    assert stats.rows_updated == 1

    # Belt and braces beyond parity: the updated value is actually visible.
    content, _ = read_sorted(uri_u)
    assert sum(1 for r in content if victim in r and 99 in r) == 1


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_fuzz_random_file_subsets(tmp_path, seed):
    """Random subsets of files receive updates; parity with MERGE is the oracle and the
    probe must rewrite exactly the touched files."""
    ids: list[list[str]] = []

    def build(uri):
        nonlocal ids
        ids = build_multifile_table(uri, seed=1000 + seed)["p1"]

    base = tmp_path / "base"
    build(str(base))
    rng = random.Random(seed)
    touched = sorted(rng.sample(range(N_FILES), rng.randint(1, N_FILES)))
    upd = [i for f in touched for i in rng.sample(ids[f], rng.randint(1, 40))]
    new = rand_ids(rng, 10)

    uri_m, uri_u = str(tmp_path / "m"), str(tmp_path / "u")
    for uri in (uri_m, uri_u):
        shutil.copytree(base, uri)
    batch = rows(upd + new, 2)
    merge_path(uri_m, batch, ["id"], None)
    stats = upsert_path(uri_u, batch, ["id"], None, prune_strategy="probe")
    assert_parity(uri_m, uri_u, f"fuzz_{seed}")

    assert stats.files_removed == len(touched)
    assert stats.files_carried_over == N_FILES - len(touched)
    assert stats.rows_updated == len(upd)
    assert stats.rows_inserted == len(new)


def test_scattered_updates_rewrite_everything(tmp_path):
    """No locality: every file holds a match, so nothing may be skipped."""
    base = tmp_path / "base"
    ids = build_multifile_table(str(base))["p1"]
    rng = random.Random(11)
    upd = [i for f in ids for i in rng.sample(f, 5)]
    uri_m, uri_u = str(tmp_path / "m"), str(tmp_path / "u")
    for uri in (uri_m, uri_u):
        shutil.copytree(base, uri)
    batch = rows(upd, 2)
    merge_path(uri_m, batch, ["id"], None)
    stats = upsert_path(uri_u, batch, ["id"], None, prune_strategy="probe")
    assert_parity(uri_m, uri_u, "scattered")

    assert stats.files_removed == N_FILES
    assert stats.files_carried_over == 0


def test_match_only_in_last_row_group_is_found(tmp_path):
    """The probe streams a file batch by batch and short-circuits on the first hit. A
    match living in the LAST row group of a multi-row-group file must still be found --
    and a small read_batch_size forces many probe batches per row group too."""
    props = deltalake.WriterProperties(max_row_group_size=500)  # 8 row groups of 500
    rng = random.Random(42)
    ids = rand_ids(rng, 4000)
    other = rand_ids(rng, 100)

    def build(uri):
        deltalake.write_deltalake(uri, rows(ids, 1), mode="overwrite", writer_properties=props)
        deltalake.write_deltalake(uri, rows(other, 1), mode="append", writer_properties=props)

    base = tmp_path / "base"
    build(str(base))
    uri_m, uri_u = str(tmp_path / "m"), str(tmp_path / "u")
    for uri in (uri_m, uri_u):
        shutil.copytree(base, uri)

    victim = ids[-1]  # physically in the final row group of file 1
    batch = rows([victim], 99)
    merge_path(uri_m, batch, ["id"], None)
    stats = upsert_path(uri_u, batch, ["id"], None, prune_strategy="probe", read_batch_size=100)
    assert_parity(uri_m, uri_u, "late_row_group")

    assert stats.files_removed == 1
    assert stats.files_carried_over == 1
    assert stats.rows_updated == 1
    content, _ = read_sorted(uri_u)
    assert sum(1 for r in content if victim in r and 99 in r) == 1


# --------------------------------------------------------------------------------------
# NULL PK semantics under the probe
# --------------------------------------------------------------------------------------


def test_null_pk_rows_never_match_and_all_files_skip(tmp_path):
    """An all-NULL-PK source can match nothing: every file must be carried over without
    even being probed, and the NULL rows must append."""
    ids: list[list[str]] = []

    def build(uri):
        nonlocal ids
        ids = build_multifile_table(uri)["p1"]

    base = tmp_path / "base"
    build(str(base))
    uri_m, uri_u = str(tmp_path / "m"), str(tmp_path / "u")
    for uri in (uri_m, uri_u):
        shutil.copytree(base, uri)

    batch = rows([None, None, None], 7)
    batch = dedupe_keep_last(batch, ["id"], None)
    merge_path(uri_m, batch, ["id"], None)
    stats = upsert_path(uri_u, batch, ["id"], None, prune_strategy="probe")
    assert_parity(uri_m, uri_u, "all_null_pk")

    assert stats.files_removed == 0
    assert stats.files_carried_over == N_FILES
    assert stats.files_probed == 0  # short-circuit: empty PK set needs no I/O
    assert stats.rows_inserted == 3


def test_null_pks_in_target_files_are_not_matched(tmp_path):
    """Target rows with NULL PKs must survive every rewrite and never be 'updated' by a
    NULL source row, while real updates in the same files still land."""

    def build(uri):
        deltalake.write_deltalake(uri, rows(["a", None, "b"], 1), mode="overwrite")
        deltalake.write_deltalake(uri, rows([None, "c"], 1), mode="append")

    base = tmp_path / "base"
    build(str(base))
    uri_m, uri_u = str(tmp_path / "m"), str(tmp_path / "u")
    for uri in (uri_m, uri_u):
        shutil.copytree(base, uri)

    batch = dedupe_keep_last(rows(["c", None, "x"], 2), ["id"], None)
    merge_path(uri_m, batch, ["id"], None)
    stats = upsert_path(uri_u, batch, ["id"], None, prune_strategy="probe")
    assert_parity(uri_m, uri_u, "null_pk_target")

    # 'c' lives in file 2 -> file 1 is match-free and must be carried over.
    assert stats.files_removed == 1
    assert stats.files_carried_over == 1
    assert stats.rows_updated == 1


# --------------------------------------------------------------------------------------
# Composite PKs
# --------------------------------------------------------------------------------------


def test_composite_pk_only_full_tuple_matches(tmp_path):
    """(id, tenant) PK: a file holding (X, 1) is match-free for source (X, 2)."""

    def build(uri):
        deltalake.write_deltalake(uri, rows(["x", "y"], 1, tenant=[1, 1]), mode="overwrite")
        deltalake.write_deltalake(uri, rows(["z"], 1, tenant=[1]), mode="append")

    base = tmp_path / "base"
    build(str(base))
    uri_m, uri_u = str(tmp_path / "m"), str(tmp_path / "u")
    for uri in (uri_m, uri_u):
        shutil.copytree(base, uri)

    # (x,2) matches nothing anywhere; (z,1) matches file 2 only.
    batch = dedupe_keep_last(rows(["x", "z"], 5, tenant=[2, 1]), ["id", "tenant"], None)
    merge_path(uri_m, batch, ["id", "tenant"], None)
    stats = upsert_path(uri_u, batch, ["id", "tenant"], None, prune_strategy="probe")
    assert_parity(uri_m, uri_u, "composite_pk")

    assert stats.files_removed == 1
    assert stats.files_carried_over == 1
    assert stats.rows_updated == 1


# --------------------------------------------------------------------------------------
# Schema evolution: PK column physically absent from old files
# --------------------------------------------------------------------------------------


def test_pk_column_added_by_evolution_skips_old_files(tmp_path):
    """Old files predate a PK column: it reads as all-NULL there, so those files are
    exact negatives and must be skipped without corruption."""

    def build(uri):
        deltalake.write_deltalake(uri, rows(["a", "b"], 1), mode="overwrite")
        deltalake.write_deltalake(uri, rows(["c", "d"], 1), mode="append")

    base = tmp_path / "base"
    build(str(base))
    uri_m, uri_u = str(tmp_path / "m"), str(tmp_path / "u")
    for uri in (uri_m, uri_u):
        shutil.copytree(base, uri)

    batch = rows(["a", "c"], 2).append_column("k2", pa.array(["k", "k"], pa.string()))
    batch = dedupe_keep_last(batch, ["id", "k2"], None)
    # merge_path/upsert_path both evolve the schema (add k2) before writing.
    merge_path(uri_m, batch, ["id", "k2"], None)
    stats = upsert_path(uri_u, batch, ["id", "k2"], None, prune_strategy="probe")
    assert_parity(uri_m, uri_u, "evolved_pk")

    # No old row can match a (id, k2) tuple -> everything carried, rows appended.
    assert stats.files_removed == 0
    assert stats.files_carried_over == 2
    assert stats.rows_updated == 0
    assert stats.rows_inserted == 2


# --------------------------------------------------------------------------------------
# Partitioned tables
# --------------------------------------------------------------------------------------


def test_partitioned_probe_prunes_within_each_partition(tmp_path):
    per_file: dict[str, list[list[str]]] = {}

    def build(uri):
        per_file.update(build_multifile_table(uri, partitioned=True, n_files=3, partitions=["p1", "p2"]))

    base = tmp_path / "base"
    build(str(base))
    rng = random.Random(3)
    upd = rng.sample(per_file["p1"][2], 10) + rng.sample(per_file["p2"][0], 10)
    parts = ["p1"] * 10 + ["p2"] * 10

    uri_m, uri_u = str(tmp_path / "m"), str(tmp_path / "u")
    for uri in (uri_m, uri_u):
        shutil.copytree(base, uri)
    batch = dedupe_keep_last(rows(upd, 2, part=parts), ["id"], PARTITION_KEY)
    merge_path(uri_m, batch, ["id"], PARTITION_KEY)
    stats = upsert_path(uri_u, batch, ["id"], PARTITION_KEY, prune_strategy="probe")
    assert_parity(uri_m, uri_u, "partitioned_probe")

    assert stats.partitions_touched == 2
    assert stats.files_removed == 2  # one matching file per partition
    assert stats.files_carried_over == 4
    assert stats.rows_updated == 20


def test_pk_equal_to_partition_column_is_conservative(tmp_path):
    """Degenerate PK = the partition column (all-constant probe): probe and none must
    produce identical content -- probing may only skip provably match-free files."""

    def build(uri):
        deltalake.write_deltalake(
            uri,
            rows(["a", "b"], 1, part=["p1", "p1"]),
            partition_by=[PARTITION_KEY],
            mode="overwrite",
        )
        deltalake.write_deltalake(
            uri,
            rows(["c"], 1, part=["p2"]),
            partition_by=[PARTITION_KEY],
            mode="append",
        )

    base = tmp_path / "base"
    build(str(base))
    uri_p, uri_n = str(tmp_path / "p"), str(tmp_path / "n")
    for uri in (uri_p, uri_n):
        shutil.copytree(base, uri)

    batch = rows(["z"], 9, part=["p1"])
    s_probe = upsert_path(uri_p, batch, [PARTITION_KEY], PARTITION_KEY, prune_strategy="probe")
    s_none = upsert_path(uri_n, batch, [PARTITION_KEY], PARTITION_KEY, prune_strategy="none")
    assert read_sorted(uri_p) == read_sorted(uri_n)
    # Every p1 row shares the source's PK tuple -> the p1 file must be rewritten.
    assert s_probe.files_removed == s_none.files_removed == 1


# --------------------------------------------------------------------------------------
# The knob itself
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("strategy", ["none", "stats", "probe"])
def test_every_strategy_is_merge_equivalent(tmp_path, strategy):
    ids: list[list[str]] = []

    def build(uri):
        nonlocal ids
        ids = build_multifile_table(uri, n_files=3)["p1"]

    base = tmp_path / "base"
    build(str(base))
    rng = random.Random(5)
    upd = rng.sample(ids[1], 20)

    uri_m, uri_u = str(tmp_path / "m"), str(tmp_path / "u")
    for uri in (uri_m, uri_u):
        shutil.copytree(base, uri)
    batch = rows(upd, 2)
    merge_path(uri_m, batch, ["id"], None)
    stats = upsert_path(uri_u, batch, ["id"], None, prune_strategy=strategy)
    assert_parity(uri_m, uri_u, f"strategy_{strategy}")

    if strategy == "probe":
        assert stats.files_removed == 1 and stats.files_carried_over == 2
    else:
        # Random UUID ranges overlap: stats pruning cannot exclude anything here.
        assert stats.files_removed == 3 and stats.files_carried_over == 0
        assert stats.files_probed == 0


def test_skip_unmatched_files_false_maps_to_none(tmp_path):
    ids: list[list[str]] = []

    def build(uri):
        nonlocal ids
        ids = build_multifile_table(uri, n_files=3)["p1"]

    base = tmp_path / "base"
    build(str(base))
    uri_u = str(tmp_path / "u")
    shutil.copytree(base, uri_u)

    batch = rows([ids[0][0]], 2)
    stats = upsert_path(uri_u, batch, ["id"], None, skip_unmatched_files=False)
    assert stats.files_removed == 3
    assert stats.files_carried_over == 0
    assert stats.files_probed == 0


def test_invalid_prune_strategy_is_rejected(tmp_path):
    def build(uri):
        deltalake.write_deltalake(uri, rows(["a"], 1), mode="overwrite")

    uri = str(tmp_path / "t")
    build(uri)
    import deltalite

    with pytest.raises(deltalite.DeltaLiteError, match="unknown prune_strategy"):
        upsert_path(uri, rows(["a"], 2), ["id"], None, prune_strategy="bogus")
