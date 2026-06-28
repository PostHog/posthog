from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.backfill_queue import (
    backfill_run_uuid,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.backfill_snapshot import (
    CHUNK_TARGET_BYTES,
    BackfillChunk,
    _committed_batch_keys,
    _group_files_into_chunks,
)


class TestChunkGrouping:
    def test_groups_small_files_up_to_target(self):
        files = [(f"s3://b/f{i}.parquet", CHUNK_TARGET_BYTES // 4, 10) for i in range(10)]

        chunks = _group_files_into_chunks(files)

        assert [len(c.paths) for c in chunks] == [4, 4, 2]
        assert [c.index for c in chunks] == [0, 1, 2]
        assert sum(c.row_count for c in chunks) == 100

    def test_oversized_file_gets_its_own_chunk(self):
        files = [
            ("s3://b/small.parquet", 100, 1),
            ("s3://b/huge.parquet", CHUNK_TARGET_BYTES * 3, 1000),
            ("s3://b/small2.parquet", 100, 1),
        ]

        chunks = _group_files_into_chunks(files)

        # huge file closes the first chunk and lands alone; trailing small file follows
        assert len(chunks) == 3
        assert chunks[1].paths == ["s3://b/huge.parquet"]

    def test_empty_input(self):
        assert _group_files_into_chunks([]) == []


def test_backfill_run_uuid_is_unique_per_planning_attempt():
    # The generation nonce is load-bearing: a replan at an UNADVANCED Delta
    # version must still produce a fresh, claimable run (the old run's batches
    # are terminally failed and would otherwise be reused verbatim).
    a = backfill_run_uuid("abc", 7)
    b = backfill_run_uuid("abc", 7)
    assert a != b
    assert a.startswith("duckgres-backfill-abc-v7-g")
    assert b.startswith("duckgres-backfill-abc-v7-g")


def test_chunk_dataclass_shape():
    c = BackfillChunk(0, ["s3://b/f"], 1, 2)
    assert (c.index, c.byte_size, c.row_count) == (0, 1, 2)


def test_committed_batch_keys_filters_to_snapshot_version():
    class FakeDeltaTable:
        def history(self):
            return [
                {"version": 12, "run_uuid": "after-snapshot", "batch_index": "0"},
                {"version": 11, "run_uuid": "flat-layout", "batch_index": "2"},
                {"version": 10, "userMetadata": '{"run_uuid": "nested-layout", "batch_index": "3"}'},
                {"version": 9, "operation": "CREATE TABLE"},
                {"version": 8, "run_uuid": "bad-batch-index", "batch_index": "nan"},
            ]

    assert _committed_batch_keys(FakeDeltaTable(), snapshot_version=11) == [
        ("flat-layout", 2),
        ("nested-layout", 3),
    ]
