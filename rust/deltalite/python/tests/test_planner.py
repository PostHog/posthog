"""Tests for the knob-tuning heuristic (deltalite_planner).

The planner is deliberately rough -- these tests pin its *shape* (monotonicity,
clamps, the honest "does not fit" answer, and agreement with the env-var names the
Rust crate reads), not any absolute MB figure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deltalite_planner import MB, Knobs, plan


def test_production_shape_gives_usable_knobs():
    # The stated production shape: ~15 concurrent upserts on an 8 GB pod.
    k = plan(15, 8_000, source_mb=250)
    assert 1 <= k.max_parallel_partitions <= 4
    assert k.max_parallel_files in (2, 4)
    assert k.max_buffered_bytes in (32 * MB, 64 * MB)
    assert k.per_upsert_budget_mb > 0


def test_generous_pod_reaches_but_never_exceeds_the_mpp_cap():
    k = plan(1, 64_000, source_mb=100)
    assert k.max_parallel_partitions == 4
    assert k.fits


def test_more_memory_never_reduces_mpp():
    prev = 0
    for pod_mb in (2_000, 4_000, 8_000, 16_000, 32_000):
        mpp = plan(10, pod_mb, source_mb=100).max_parallel_partitions
        assert mpp >= prev
        prev = mpp


def test_more_concurrency_never_increases_mpp():
    prev = 5
    for n in (1, 2, 4, 8, 16, 32):
        mpp = plan(n, 16_000, source_mb=100).max_parallel_partitions
        assert mpp <= prev
        prev = mpp


def test_overloaded_pod_says_no_rather_than_pretending():
    k = plan(50, 4_000, source_mb=500)
    assert not k.fits
    assert k.max_parallel_partitions == 1  # still returns the most conservative knobs
    assert any("below" in n for n in k.notes)


def test_bigger_sources_reduce_headroom():
    small = plan(10, 16_000, source_mb=50)
    large = plan(10, 16_000, source_mb=600)
    assert large.max_parallel_partitions <= small.max_parallel_partitions


def test_missing_source_size_is_flagged():
    k = plan(4, 16_000)
    assert any("source size not given" in n for n in k.notes)
    assert not any("source size not given" in n for n in plan(4, 16_000, source_mb=100).notes)


def test_tight_budget_halves_the_wall_clock_knobs():
    tight = plan(30, 8_000, source_mb=200)
    assert tight.max_parallel_files == 2
    assert tight.max_buffered_bytes == 32 * MB
    roomy = plan(2, 32_000, source_mb=200)
    assert roomy.max_parallel_files == 4
    assert roomy.max_buffered_bytes == 64 * MB


def test_env_suggestions_match_the_rust_crate_names_and_scale():
    k = plan(15, 16_000, source_mb=100)
    assert set(k.env) == {
        "DELTALITE_PROCESS_MAX_PARALLEL_PARTITIONS",
        "DELTALITE_PROCESS_MAX_PARALLEL_FILES",
        "DELTALITE_PROCESS_MAX_BUFFERED_BYTES",
    }
    # Ceilings are per-call knobs x a bounded burst factor, never per-call x N upserts.
    assert int(k.env["DELTALITE_PROCESS_MAX_PARALLEL_PARTITIONS"]) <= k.max_parallel_partitions * 4
    assert int(k.env["DELTALITE_PROCESS_MAX_PARALLEL_FILES"]) <= k.max_parallel_files * 4
    assert int(k.env["DELTALITE_PROCESS_MAX_BUFFERED_BYTES"]) <= k.max_buffered_bytes * 4


def test_single_upsert_env_does_not_over_provision():
    k = plan(1, 16_000, source_mb=100)
    assert int(k.env["DELTALITE_PROCESS_MAX_PARALLEL_PARTITIONS"]) == k.max_parallel_partitions
    assert int(k.env["DELTALITE_PROCESS_MAX_BUFFERED_BYTES"]) == k.max_buffered_bytes


def test_as_upsert_kwargs_round_trips_into_upsert_signature():
    k = plan(4, 8_000, source_mb=100)
    kwargs = k.as_upsert_kwargs()
    assert set(kwargs) == {
        "max_parallel_partitions",
        "max_parallel_files",
        "max_buffered_bytes",
    }
    assert isinstance(k, Knobs)


@pytest.mark.parametrize(
    "args",
    [
        (0, 8_000),
        (-1, 8_000),
        (4, 0),
        (4, -100),
    ],
)
def test_invalid_inputs_raise(args):
    with pytest.raises(ValueError):
        plan(*args)


def test_invalid_target_file_size_raises():
    with pytest.raises(ValueError):
        plan(4, 8_000, target_file_size_mb=0)


def test_smaller_target_file_size_frees_room_for_workers():
    big = plan(10, 8_000, source_mb=100, target_file_size_mb=200)
    small = plan(10, 8_000, source_mb=100, target_file_size_mb=25)
    assert small.max_parallel_partitions >= big.max_parallel_partitions


def test_knob_kwargs_are_accepted_by_a_real_upsert(tmp_path):
    """The suggested kwargs must remain valid arguments of DeltaLiteTable.upsert."""
    import pyarrow as pa
    import deltalake
    from harness.common import PARTITION_KEY, upsert_path

    uri = str(tmp_path / "planned")
    table = pa.table(
        {
            "id": pa.array(["a", "b"], pa.string()),
            "v": pa.array([1, 2], pa.int64()),
            PARTITION_KEY: pa.array(["p1", "p1"], pa.string()),
        }
    )
    deltalake.write_deltalake(uri, table, partition_by=[PARTITION_KEY], mode="overwrite")

    knobs = plan(15, 8_000, source_mb=1)
    batch = pa.table(
        {
            "id": pa.array(["a", "c"], pa.string()),
            "v": pa.array([10, 3], pa.int64()),
            PARTITION_KEY: pa.array(["p1", "p1"], pa.string()),
        }
    )
    stats = upsert_path(uri, batch, ["id"], PARTITION_KEY, **knobs.as_upsert_kwargs())
    assert stats.rows_updated == 1
    assert stats.rows_inserted == 1
