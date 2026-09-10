"""Crash-safety and redelivery.

Production runs these batches under Temporal with Kafka-style redelivery, so a batch can
be SIGKILLed at any point and re-run. These tests verify:

1. A kill between the parquet rewrite and the `CommitBuilder` commit leaves the table
   logically unchanged (orphaned data files are fine; the log, version, live file set,
   and contents must be untouched and the table must not be corrupted).
2. The idempotency tag (`run_uuid` + `batch_index` in commitInfo) supports the
   redelivery decision: discoverable after a successful commit (skip), absent after a
   pre-commit crash (re-run).
3. Re-running a whole batch is idempotent by construction -- with the documented
   exception of NULL-PK rows, which always insert and therefore duplicate on redelivery
   on BOTH paths (a genuine trap; pinned explicitly below).
4. deltalite makes ONE commit per batch, so a mid-batch kill never exposes a partial
   (some-partitions-updated) table -- unlike today's per-partition MERGE loop, whose
   partial visibility is also demonstrated here for contrast.

Kill mechanics: the upsert runs in a subprocess; the parent polls the table directory
every ~1 ms and SIGKILLs on a phase trigger (new data files appearing before the log
gains a commit). Every kill asserts on *observed* state -- the worker must die without
printing its COMMITTED sentinel and without a new log entry -- so a kill that missed its
phase fails (or retries) rather than silently passing.
"""

from __future__ import annotations

import os
import re
import sys
import time
import shutil
import signal
import textwrap
import subprocess
from pathlib import Path

import pytest

import pyarrow as pa
import deltalake
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness.common import (  # noqa: E402
    PARTITION_KEY,
    create_table,
    gen_wide,
    merge_path,
    read_sorted,
    upsert_path,
    uuid_ids,
)

# Crash-table shape: 4 partitions x 8000 wide rows (~27 MB total). With
# max_parallel_partitions=1 each partition's rewritten parquet file appears ~50 ms after
# the previous one and the commit lands ~2 ms after the last, so killing on the first
# new file leaves ~150 ms of margin before the commit could possibly land.
N_PARTITIONS = 4
ROWS_PER_PARTITION = 8_000
BATCH_ROWS_PER_PARTITION = 1_000
PAYLOAD_SIZE = 1_000
CRASH_PARTITIONS = [f"2026-07-{d:02d}" for d in range(20, 20 + N_PARTITIONS)]

POLL_S = 0.001
WORKER_TIMEOUT_S = 120
KILL_ATTEMPTS = 3  # re-try a lost race (commit beat the kill) up to this many times

COMMIT_RE = re.compile(r"^\d{20}\.json$")
CRASH_MD = {"run_uuid": "crash-run", "batch_index": "0"}

WORKER_SRC = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, {root!r})
    import pyarrow.parquet as pq
    from harness.common import merge_path, upsert_path

    mode, uri, batch_path = sys.argv[1], sys.argv[2], sys.argv[3]
    batch = pq.read_table(batch_path)
    md = {md!r}
    if mode == "merge":
        merge_path(uri, batch, ["id"], {pk!r}, md)
    else:
        upsert_path(uri, batch, ["id"], {pk!r}, md, max_parallel_partitions=1)
    print("COMMITTED", flush=True)
    """
).format(root=str(ROOT), md=CRASH_MD, pk=PARTITION_KEY)


# --------------------------------------------------------------------------------------
# Observation helpers
# --------------------------------------------------------------------------------------


def data_files(uri: str) -> set[str]:
    root = Path(uri)
    return {str(f.relative_to(root)) for f in root.rglob("*.parquet") if "_delta_log" not in f.parts}


def commit_entries(uri: str) -> set[str]:
    log = Path(uri) / "_delta_log"
    if not log.exists():
        return set()
    return {f.name for f in log.iterdir() if COMMIT_RE.match(f.name)}


def table_state(uri: str):
    """The full logically-visible state: version, live files, content, schema."""
    dt = deltalake.DeltaTable(uri)
    rows, schema = read_sorted(uri)
    return {
        "version": dt.version(),
        "file_uris": sorted(dt.file_uris()),
        "rows": rows,
        "schema": schema,
    }


def batch_already_committed(uri: str, md: dict[str, str], limit: int = 10) -> bool:
    """The production redelivery decision: `has_commit_with_metadata`'s matcher
    (accepts both the flat 1.x commitInfo layout and nested userMetadata)."""
    for commit in deltalake.DeltaTable(uri).history(limit):
        flat = all(commit.get(k) == v for k, v in md.items())
        nested = commit.get("userMetadata")
        if flat or (isinstance(nested, dict) and all(nested.get(k) == v for k, v in md.items())):
            return True
    return False


def updated_partitions(uri: str) -> list[str]:
    """Partitions in which the batch's rows (counter == 2) are visible."""
    tbl = deltalake.DeltaTable(uri).to_pyarrow_table(columns=["counter", PARTITION_KEY])
    return sorted({p for c, p in zip(tbl["counter"].to_pylist(), tbl[PARTITION_KEY].to_pylist()) if c == 2})


# --------------------------------------------------------------------------------------
# Crash fixture: one base table template per session, copied per attempt
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def crash_template(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("crash_template")
    uri = str(tmp / "base")
    initial = pa.concat_tables(
        gen_wide(
            uuid_ids(ROWS_PER_PARTITION, offset=i * ROWS_PER_PARTITION),
            p,
            seed=i,
            payload_size=PAYLOAD_SIZE,
            version=1,
        )
        for i, p in enumerate(CRASH_PARTITIONS)
    )
    create_table(uri, initial, True)

    # The redelivered batch: 1000 updated rows in every partition (version/counter=2).
    batch = pa.concat_tables(
        gen_wide(
            uuid_ids(BATCH_ROWS_PER_PARTITION, offset=i * ROWS_PER_PARTITION),
            p,
            seed=100 + i,
            payload_size=PAYLOAD_SIZE,
            version=2,
        )
        for i, p in enumerate(CRASH_PARTITIONS)
    )
    batch_path = tmp / "batch.parquet"
    pq.write_table(batch, batch_path)

    worker = tmp / "worker.py"
    worker.write_text(WORKER_SRC)

    # Expected content after the batch is applied exactly once (either path).
    control = str(tmp / "control")
    shutil.copytree(uri, control)
    upsert_path(control, batch, ["id"], PARTITION_KEY, CRASH_MD)
    expected_rows, expected_schema = read_sorted(control)

    yield {
        "base": uri,
        "batch": batch,
        "batch_path": str(batch_path),
        "worker": str(worker),
        "expected_rows": expected_rows,
        "expected_schema": expected_schema,
    }
    shutil.rmtree(tmp, ignore_errors=True)


def fresh_copy(template, tmp_path: Path, name: str) -> str:
    dst = tmp_path / name
    shutil.copytree(template["base"], dst)
    return str(dst)


def run_and_kill(uri: str, template, mode: str, trigger):
    """Run one write in a subprocess; SIGKILL when `trigger(new_files, new_commits)`
    fires. Returns observed state; caller decides whether the attempt landed."""
    before_files = data_files(uri)
    before_commits = commit_entries(uri)

    proc = subprocess.Popen(
        [sys.executable, template["worker"], mode, uri, template["batch_path"]],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    killed = False
    kill_snapshot = None
    t0 = time.perf_counter()
    try:
        while proc.poll() is None:
            if time.perf_counter() - t0 > WORKER_TIMEOUT_S:
                raise AssertionError("crash worker hung")
            new_files = data_files(uri) - before_files
            new_commits = commit_entries(uri) - before_commits
            if trigger(new_files, new_commits):
                kill_snapshot = {"files": set(new_files), "commits": set(new_commits)}
                proc.send_signal(signal.SIGKILL)
                killed = True
                break
            time.sleep(POLL_S)
    finally:
        if proc.poll() is None and not killed:
            proc.kill()
    out, err = proc.communicate(timeout=WORKER_TIMEOUT_S)

    return {
        "killed": killed,
        "returncode": proc.returncode,
        "stdout": out,
        "stderr": err,
        "kill_snapshot": kill_snapshot,
        "new_files": data_files(uri) - before_files,
        "new_commits": commit_entries(uri) - before_commits,
    }


def kill_upsert_mid_rewrite(uri: str, template, min_new_files: int):
    """Kill the upsert worker once >= min_new_files rewritten parquet files exist on
    disk but before any commit. Asserts the kill verifiably landed pre-commit."""
    res = run_and_kill(
        uri,
        template,
        "upsert",
        lambda files, commits: len(files) >= min_new_files and not commits,
    )
    if not res["killed"] or res["new_commits"]:
        return None  # commit won the race; caller retries on a fresh copy

    # Prove the kill landed in the intended phase.
    assert res["returncode"] == -signal.SIGKILL
    assert "COMMITTED" not in res["stdout"]
    assert len(res["new_files"]) >= min_new_files, f"expected >= {min_new_files} orphaned files, saw {res['new_files']}"
    assert not res["new_commits"], "kill was supposed to land before the commit"
    return res


# --------------------------------------------------------------------------------------
# 1. Kill between rewrite and commit -> nothing visible
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "min_new_files",
    [1, N_PARTITIONS - 1],
    ids=["early_in_rewrite", "after_most_partitions_rewritten"],
)
def test_kill_before_commit_leaves_table_logically_unchanged(tmp_path, crash_template, min_new_files):
    """New parquet files are on disk (verified) but the commit never happened: the
    table's version, live file set, contents, and schema must all be untouched."""
    for attempt in range(KILL_ATTEMPTS):
        uri = fresh_copy(crash_template, tmp_path, f"kill_{min_new_files}_{attempt}")
        before = table_state(uri)
        before_commits = commit_entries(uri)

        res = kill_upsert_mid_rewrite(uri, crash_template, min_new_files)
        if res is None:
            shutil.rmtree(uri)
            continue

        after = table_state(uri)
        assert after == before, "a pre-commit kill changed the logically-visible table"
        assert commit_entries(uri) == before_commits

        # The orphans really exist and really are invisible.
        live = {Path(u).name for u in after["file_uris"]}
        orphans = {Path(f).name for f in res["new_files"]}
        assert orphans and not (orphans & live)

        # Not corrupted: the standard corruption probe passes.
        assert deltalake.DeltaTable.is_deltatable(uri)
        deltalake.DeltaTable(uri).to_pyarrow_table(columns=["id"])
        shutil.rmtree(uri)
        return
    pytest.fail(f"kill never landed mid-rewrite in {KILL_ATTEMPTS} attempts")


def test_crash_orphans_survive_default_vacuum_and_need_full_mode(tmp_path, crash_template):
    """The design says orphaned pre-commit files are 'reclaimed by vacuum'. That is
    only true of vacuum(full=True): a never-committed file has no Remove tombstone, and
    delta-rs 1.x vacuum defaults to lite mode (tombstones only) -- which is exactly how
    production's `vacuum_table` calls it (retention_hours=24, enforce off, no full=).
    Crash orphans therefore accumulate until a full vacuum runs. Pinned here so the
    operational requirement is a documented fact."""
    for attempt in range(KILL_ATTEMPTS):
        uri = fresh_copy(crash_template, tmp_path, f"vacuum_{attempt}")
        res = kill_upsert_mid_rewrite(uri, crash_template, 1)
        if res is None:
            shutil.rmtree(uri)
            continue

        orphans = [Path(uri) / f for f in res["new_files"]]
        assert orphans and all(f.exists() for f in orphans)
        # Pretend the crash happened 2 days ago so the 24 h retention cannot excuse
        # vacuum from considering the files.
        old = time.time() - 48 * 3600
        for f in orphans:
            os.utime(f, (old, old))

        dt = deltalake.DeltaTable(uri)
        # Production's exact invocation (lite mode): orphans are NOT reclaimed.
        dt.vacuum(retention_hours=24, enforce_retention_duration=False, dry_run=False)
        assert all(f.exists() for f in orphans), (
            "unexpectedly reclaimed by lite vacuum -- the full-mode requirement no longer holds"
        )

        # Only full mode reclaims them, and doing so does not harm the table.
        dt.vacuum(
            retention_hours=24,
            enforce_retention_duration=False,
            dry_run=False,
            full=True,
        )
        assert not any(f.exists() for f in orphans)
        rows, _ = read_sorted(uri)
        assert len(rows) == N_PARTITIONS * ROWS_PER_PARTITION
        shutil.rmtree(uri)
        return
    pytest.fail(f"kill never landed mid-rewrite in {KILL_ATTEMPTS} attempts")


# --------------------------------------------------------------------------------------
# 4. Single atomic commit: no partial batch is ever visible; redelivery converges
# --------------------------------------------------------------------------------------


def test_no_partial_batch_after_kill_and_redelivery_converges(tmp_path, crash_template):
    """Kill after 3 of 4 partitions were fully rewritten on disk. Because deltalite
    commits once per batch, ZERO partitions may be visibly updated. The tag must be
    absent (decision: re-run), and re-running the whole batch must converge to exactly
    the single-application result with one new commit."""
    for attempt in range(KILL_ATTEMPTS):
        uri = fresh_copy(crash_template, tmp_path, f"partial_{attempt}")
        before = table_state(uri)

        res = kill_upsert_mid_rewrite(uri, crash_template, N_PARTITIONS - 1)
        if res is None:
            shutil.rmtree(uri)
            continue

        # >= 3 partitions' worth of rewritten data sits on disk, yet none is visible.
        assert updated_partitions(uri) == [], "partial batch visible after mid-batch kill -- atomicity broken"
        assert table_state(uri) == before

        # Redelivery decision: the tag must NOT be discoverable -> re-run the batch.
        assert not batch_already_committed(uri, CRASH_MD)

        # Re-run the identical batch (the Temporal redelivery), in spite of orphans.
        stats = upsert_path(uri, crash_template["batch"], ["id"], PARTITION_KEY, CRASH_MD)
        assert stats.version == before["version"] + 1  # exactly one commit
        rows, schema = read_sorted(uri)
        assert rows == crash_template["expected_rows"]
        assert schema == crash_template["expected_schema"]
        assert updated_partitions(uri) == CRASH_PARTITIONS
        assert batch_already_committed(uri, CRASH_MD)
        shutil.rmtree(uri)
        return
    pytest.fail(f"kill never landed mid-rewrite in {KILL_ATTEMPTS} attempts")


def test_merge_path_kill_exposes_partial_batch(tmp_path, crash_template):
    """Contrast: today's per-partition MERGE loop commits N times, so a mid-batch kill
    leaves some partitions updated and others not -- the failure mode deltalite's
    single commit removes. Recovery still works (intermediate commits are untagged, so
    the redelivery decision is re-run, and MERGE re-application converges)."""
    for attempt in range(KILL_ATTEMPTS):
        uri = fresh_copy(crash_template, tmp_path, f"merge_partial_{attempt}")

        res = run_and_kill(
            uri,
            crash_template,
            "merge",
            lambda files, commits: len(commits) >= 1,
        )
        n_commits = len(res["new_commits"])
        if not res["killed"] or not (1 <= n_commits < N_PARTITIONS):
            shutil.rmtree(uri)
            continue  # worker finished all partitions before the kill; retry

        assert res["returncode"] == -signal.SIGKILL
        assert "COMMITTED" not in res["stdout"]

        # Partial state IS visible: the first n_commits partitions (merge_path walks
        # them in sorted order) show the new rows, the rest do not.
        assert updated_partitions(uri) == CRASH_PARTITIONS[:n_commits], (
            "expected exactly the committed partitions to be visibly updated"
        )

        # Only the terminal commit carries the tag, so redelivery correctly re-runs.
        assert not batch_already_committed(uri, CRASH_MD)
        merge_path(uri, crash_template["batch"], ["id"], PARTITION_KEY, CRASH_MD)
        rows, schema = read_sorted(uri)
        assert rows == crash_template["expected_rows"]
        assert schema == crash_template["expected_schema"]
        assert batch_already_committed(uri, CRASH_MD)
        shutil.rmtree(uri)
        return
    pytest.fail(f"never caught MERGE between its per-partition commits in {KILL_ATTEMPTS} attempts")


# --------------------------------------------------------------------------------------
# 2. Redelivery after a successful commit is detected
# --------------------------------------------------------------------------------------


def simple(ids, part, v):
    n = len(ids)
    return pa.table(
        {
            "id": pa.array(ids, pa.string()),
            "v": pa.array([v] * n if isinstance(v, int) else v, pa.int64()),
            PARTITION_KEY: pa.array(part if isinstance(part, list) else [part] * n, pa.string()),
        }
    )


def test_redelivery_after_successful_commit_is_detected(tmp_path):
    """The full redelivery decision: tag absent before the batch -> run; present after
    -> skip; a *different* batch of the same run is not confused with it."""
    uri = str(tmp_path / "redelivery")
    create_table(uri, simple(["a", "b"], "2026-07-23", 1), True)
    md0 = {"run_uuid": "run-r", "batch_index": "0"}
    md1 = {"run_uuid": "run-r", "batch_index": "1"}

    assert not batch_already_committed(uri, md0)

    upsert_path(uri, simple(["a", "c"], "2026-07-23", 2), ["id"], PARTITION_KEY, md0)

    assert batch_already_committed(uri, md0), "redelivered batch would NOT be skipped"
    assert not batch_already_committed(uri, md1), "unrelated batch would be skipped"
    assert not batch_already_committed(uri, {"run_uuid": "other-run", "batch_index": "0"})

    # An empty batch's action-less commit must also register for redelivery detection.
    upsert_path(uri, simple([], "2026-07-23", []), ["id"], PARTITION_KEY, md1)
    assert batch_already_committed(uri, md1)


# --------------------------------------------------------------------------------------
# 3. Re-running a whole batch is idempotent by construction (except NULL PKs)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("path_name", ["merge", "upsert"])
def test_rerun_of_committed_batch_is_idempotent(tmp_path, path_name):
    """Apply the identical (NULL-free) batch twice; the table must equal a single
    application -- no duplicated rows, same schema, and on the upsert path the second
    run reports pure updates (nothing inserted)."""
    path = merge_path if path_name == "merge" else upsert_path
    parts = ["2026-07-23", "2026-07-24"]
    batch = simple(["a", "b", "x"], [parts[0], parts[0], parts[1]], 2)

    uri_once = str(tmp_path / f"once_{path_name}")
    uri_twice = str(tmp_path / f"twice_{path_name}")
    initial = simple(["a", "b", "c"], parts[0], 1)
    create_table(uri_once, initial, True)
    create_table(uri_twice, initial, True)

    path(uri_once, batch, ["id"], PARTITION_KEY, {"run_uuid": "r", "batch_index": "0"})
    path(uri_twice, batch, ["id"], PARTITION_KEY, {"run_uuid": "r", "batch_index": "0"})
    stats = path(uri_twice, batch, ["id"], PARTITION_KEY, {"run_uuid": "r", "batch_index": "0"})

    rows_once, schema_once = read_sorted(uri_once)
    rows_twice, schema_twice = read_sorted(uri_twice)
    assert rows_twice == rows_once, f"[{path_name}] re-applying the batch changed the table"
    assert schema_twice == schema_once
    assert len(rows_twice) == 4  # a, b updated; c untouched; x inserted -- exactly once

    if path_name == "upsert":
        # Every row of the re-applied batch matched an existing row, so nothing is new.
        assert stats.rows_updated == batch.num_rows
        assert stats.rows_inserted == 0


def test_upsert_stats_do_not_double_count_updated_rows_as_inserts(tmp_path):
    """A 3-row batch with 2 matches must report rows_updated=2, rows_inserted=1.

    Regression test for a fixed bug: `rewrite_partition` used to set
    `rows_inserted = source.num_rows()` (the whole slice), counting every matched row
    as both an update and an insert. Table content was never affected.
    """
    uri = str(tmp_path / "stats_counts")
    create_table(uri, simple(["a", "b", "c"], "2026-07-23", 1), True)
    batch = simple(["a", "b", "x"], "2026-07-23", 2)

    stats = upsert_path(uri, batch, ["id"], PARTITION_KEY)
    assert stats.rows_updated == 2
    assert stats.rows_inserted == batch.num_rows - stats.rows_updated  # 1, not 3


def test_null_pk_batch_redelivery_is_not_idempotent_on_either_path(tmp_path):
    """The correctness trap: NULL-PK rows never match (SQL NULL != NULL), so they
    INSERT on every application. Re-running a batch containing NULL PKs therefore
    legitimately duplicates those rows -- on BOTH paths, identically. The commit tag is
    the ONLY thing standing between an after-commit redelivery and duplicated data.

    This pins the behavior so the divergence-from-idempotency is a documented fact,
    not a latent surprise."""
    batch = simple([None, None, "a"], "2026-07-23", 2)
    results = {}
    for path_name, path in (("merge", merge_path), ("upsert", upsert_path)):
        uri = str(tmp_path / f"nullpk_{path_name}")
        create_table(uri, simple(["a", "b"], "2026-07-23", 1), True)

        path(uri, batch, ["id"], PARTITION_KEY, {"run_uuid": "r", "batch_index": "0"})
        rows_after_first, _ = read_sorted(uri)
        # First application: 2 NULL rows inserted, 'a' updated.
        assert len(rows_after_first) == 4

        # The redelivery (same batch, same tag -- as if the tag check were skipped).
        path(uri, batch, ["id"], PARTITION_KEY, {"run_uuid": "r", "batch_index": "0"})
        rows_after_second, _ = read_sorted(uri)
        results[path_name] = rows_after_second

        # NOT idempotent: the two NULL rows inserted again.
        assert len(rows_after_second) == 6, (
            f"[{path_name}] expected NULL-PK rows to duplicate on redelivery (got {len(rows_after_second)} rows)"
        )

    # ...and both paths land on the identical (duplicated) state: no divergence.
    assert results["merge"] == results["upsert"]


def test_null_pk_redelivery_is_safe_when_tag_is_honored(tmp_path):
    """The mitigation for the trap above: the production flow checks the tag BEFORE
    re-applying. After a successful commit, the skip decision protects even NULL-PK
    batches; only a tag-check bypass (or history truncation) can duplicate them."""
    uri = str(tmp_path / "nullpk_guard")
    create_table(uri, simple(["a", "b"], "2026-07-23", 1), True)
    md = {"run_uuid": "r", "batch_index": "0"}
    batch = simple([None, "a"], "2026-07-23", 2)

    if not batch_already_committed(uri, md):
        upsert_path(uri, batch, ["id"], PARTITION_KEY, md)
    rows_first, _ = read_sorted(uri)

    # Redelivery, this time driving the decision the way production does.
    if not batch_already_committed(uri, md):  # -> True, so skipped
        upsert_path(uri, batch, ["id"], PARTITION_KEY, md)
    rows_second, _ = read_sorted(uri)

    assert batch_already_committed(uri, md)
    assert rows_second == rows_first, "tag-guarded redelivery must be a no-op"
    assert len(rows_first) == 3  # a updated, one NULL insert, b untouched


# --------------------------------------------------------------------------------------
# Single-commit-per-batch happy path (the property the crash tests rely on)
# --------------------------------------------------------------------------------------


def test_upsert_is_one_commit_per_batch_where_merge_is_n(tmp_path):
    parts = ["2026-07-21", "2026-07-22", "2026-07-23"]
    initial = simple(["a", "b", "c"], parts, 1)
    batch = simple(["a", "b", "c", "d"], [*parts, parts[0]], 2)

    uri_m = str(tmp_path / "ncommits_merge")
    uri_u = str(tmp_path / "ncommits_upsert")
    create_table(uri_m, initial, True)
    create_table(uri_u, initial, True)

    v0_m = deltalake.DeltaTable(uri_m).version()
    v0_u = deltalake.DeltaTable(uri_u).version()

    merge_path(uri_m, batch, ["id"], PARTITION_KEY, {"run_uuid": "r", "batch_index": "0"})
    upsert_path(uri_u, batch, ["id"], PARTITION_KEY, {"run_uuid": "r", "batch_index": "0"})

    assert deltalake.DeltaTable(uri_m).version() == v0_m + len(parts)  # N commits
    assert deltalake.DeltaTable(uri_u).version() == v0_u + 1  # ONE commit
