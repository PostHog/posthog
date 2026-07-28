"""Production hardening added on top of the spike: the source-size guard and the
multipart upload path.

The guard turns "RSS grows until the pod OOMs" into a clean typed error at the front
door; multipart replaces single ~100 MB PUTs of output files. Both must leave upsert
semantics byte-identical, so the multipart test is a full differential parity run with
the threshold forced to minimum.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import pyarrow as pa
import deltalake

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.common import PARTITION_KEY, Scenario, assert_parity, create_table, upsert_path


def simple(ids, part, v):
    return pa.table(
        {
            "id": pa.array(ids, pa.string()),
            "value": pa.array([v] * len(ids), pa.int64()),
            PARTITION_KEY: pa.array([part] * len(ids), pa.string()),
        }
    )


def test_source_guard_rejects_oversized_batch_and_leaves_table_untouched(tmp_path):
    import deltalite

    uri = str(tmp_path / "guarded")
    create_table(uri, simple(["a", "b"], "p1", 1), partitioned=True)
    before = deltalake.DeltaTable(uri)
    version_before = before.version()

    with pytest.raises(deltalite.DeltaLiteSourceTooLargeError) as ei:
        upsert_path(uri, simple(["a", "c"], "p1", 2), ["id"], PARTITION_KEY, max_source_bytes=1)
    assert "ceiling" in str(ei.value)

    after = deltalake.DeltaTable(uri)
    assert after.version() == version_before, "a rejected batch must not commit anything"


def test_source_guard_zero_disables_the_ceiling(tmp_path):
    uri = str(tmp_path / "unguarded")
    create_table(uri, simple(["a"], "p1", 1), partitioned=True)
    stats = upsert_path(uri, simple(["a", "b"], "p1", 2), ["id"], PARTITION_KEY, max_source_bytes=0)
    assert stats.rows_updated == 1
    assert stats.rows_inserted == 1


def test_source_guard_error_is_a_deltalite_error_subclass():
    import deltalite

    assert issubclass(deltalite.DeltaLiteSourceTooLargeError, deltalite.DeltaLiteError)


def test_multipart_forced_upsert_has_merge_parity(tmp_path):
    """Force every output file through the multipart path (threshold=1 byte) and assert
    full differential parity against the real delta-rs MERGE. Proves the multipart
    store wrapper changes nothing about logical content or the commit protocol."""
    scenario = Scenario(
        name="multipart_forced",
        initial=pa.concat_tables([simple([f"k{i}" for i in range(50)], p, 1) for p in ("p1", "p2")]),
        batches=[
            pa.concat_tables(
                [
                    simple([f"k{i}" for i in range(0, 30)], "p1", 2),
                    simple([f"n{i}" for i in range(5)], "p2", 2),
                ]
            )
        ],
        primary_keys=["id"],
        partitioned=True,
    )
    # run_scenario drives the upsert arm through upsert_path(**kwargs).
    uri_m, uri_u = run_scenario_with_multipart(scenario, tmp_path)
    assert_parity(uri_m, uri_u, "multipart_forced")


def run_scenario_with_multipart(scenario, tmp_path):
    from harness.common import dedupe_keep_last, merge_path

    uri_m = str(tmp_path / f"{scenario.name}_merge")
    uri_u = str(tmp_path / f"{scenario.name}_upsert")
    create_table(uri_m, scenario.initial, scenario.partitioned)
    create_table(uri_u, scenario.initial, scenario.partitioned)
    for i, raw in enumerate(scenario.batches):
        batch = dedupe_keep_last(raw, scenario.primary_keys, scenario.partition_key)
        md = {"run_uuid": "run-mp", "batch_index": str(i)}
        merge_path(uri_m, batch, scenario.primary_keys, scenario.partition_key, md)
        upsert_path(
            uri_u,
            batch,
            scenario.primary_keys,
            scenario.partition_key,
            md,
            multipart_threshold=1,
            multipart_part_size=5 * 1024 * 1024,
        )
    return uri_m, uri_u


def test_invalid_prune_strategy_raises_typed_error(tmp_path):
    import deltalite

    uri = str(tmp_path / "badstrategy")
    create_table(uri, simple(["a"], "p1", 1), partitioned=True)
    with pytest.raises(deltalite.DeltaLiteError):
        upsert_path(uri, simple(["a"], "p1", 2), ["id"], PARTITION_KEY, prune_strategy="join")
