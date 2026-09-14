from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
    CDC_OP_COLUMN,
    CDC_SEQ_COLUMN,
    CDC_SEQ_PROVENANCE,
    DELETED_COLUMN,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.load_resolution import (
    LOAD_POSITION_CONFIG_KEY,
    MAX_VERIFIED_DELETE_ROWS,
    SCD2_APPEND_MODE,
    batch_max_seq,
    dedupe_keep_highest_seq,
    drop_superseded_rows,
    has_engine_seq,
    is_cdc_write_resolution_enabled,
    persist_load_position,
    read_load_position,
    resolve_batch,
    verify_delete_enrichment,
)


def _batch(ids, names, ops, seqs=None, engine_seq=True):
    """A CDC batch. `engine_seq=False` builds the seq column WITHOUT the batcher's provenance
    stamp — i.e. a source table that happens to have its own `_ph_cdc_seq` column."""
    columns = {
        "id": pa.array(ids, pa.int64()),
        "name": pa.array(names, pa.string()),
        CDC_OP_COLUMN: pa.array(ops, pa.string()),
        DELETED_COLUMN: pa.array([op == "D" for op in ops], pa.bool_()),
    }
    table = pa.table(columns)
    if seqs is None:
        return table

    metadata = CDC_SEQ_PROVENANCE if engine_seq else None
    field = pa.field(CDC_SEQ_COLUMN, pa.int64(), metadata=metadata)
    return table.append_column(field, pa.array(seqs, pa.int64()))


def _existing(ids, names):
    return pa.table({"id": pa.array(ids, pa.int64()), "name": pa.array(names, pa.string())})


class TestBatchMaxSeq:
    def test_none_without_seq_column(self):
        assert batch_max_seq(_batch([1], ["a"], ["I"])) is None

    def test_none_when_empty(self):
        assert batch_max_seq(_batch([], [], [], seqs=[])) is None

    def test_ignores_nulls(self):
        table = _batch([1, 2, 3], ["a", "b", "c"], ["I", "I", "I"], seqs=[10, None, 30])
        assert batch_max_seq(table) == 30


class TestDropSupersededRows:
    def test_passthrough_without_watermark(self):
        table = _batch([1, 2], ["a", "b"], ["I", "I"], seqs=[10, 20])
        result, dropped = drop_superseded_rows(table, None)
        assert dropped == 0
        assert result is table

    def test_passthrough_without_seq_column(self):
        table = _batch([1, 2], ["a", "b"], ["I", "I"])
        result, dropped = drop_superseded_rows(table, 99)
        assert dropped == 0
        assert result is table

    def test_drops_only_rows_strictly_below_watermark(self):
        table = _batch([1, 2, 3], ["a", "b", "c"], ["I", "I", "I"], seqs=[10, 20, 30])
        result, dropped = drop_superseded_rows(table, 20)

        assert dropped == 1
        assert result.column("id").to_pylist() == [2, 3]

    def test_keeps_later_chunks_of_a_split_transaction(self):
        # Every event in one Postgres transaction shares its commit LSN, and a transaction bigger
        # than the flush budget spans micro-batches. Dropping seq == watermark would discard the
        # rest of the transaction outright.
        table = _batch([3, 4], ["c", "d"], ["I", "I"], seqs=[20, 20])
        result, dropped = drop_superseded_rows(table, 20)

        assert dropped == 0
        assert result.column("id").to_pylist() == [3, 4]

    def test_keeps_null_positions(self):
        # An unknown position cannot be proven stale; dropping it would lose data.
        table = _batch([1, 2], ["a", "b"], ["I", "I"], seqs=[None, 5])
        result, dropped = drop_superseded_rows(table, 10)

        assert dropped == 1
        assert result.column("id").to_pylist() == [1]

    def test_drops_replayed_rows_below_the_watermark(self):
        table = _batch([1, 2], ["a", "b"], ["I", "I"], seqs=[10, 20])
        result, dropped = drop_superseded_rows(table, 30)

        assert dropped == 2
        assert result.num_rows == 0

    def test_ignores_a_source_owned_seq_column(self):
        # The batcher passes through a source column named _ph_cdc_seq untouched, so its values
        # are user data. Trusting them would let a source set a high value, poison the watermark,
        # and have its own later rows dropped.
        table = _batch([1, 2], ["a", "b"], ["I", "I"], seqs=[10, 20], engine_seq=False)
        result, dropped = drop_superseded_rows(table, 15)

        assert dropped == 0
        assert result is table
        assert not has_engine_seq(table)
        assert batch_max_seq(table) is None


class TestDedupeKeepHighestSeq:
    def test_passthrough_without_seq_column(self):
        table = _batch([1, 1], ["a", "b"], ["I", "U"])
        result, dropped = dedupe_keep_highest_seq(table, ["id"])
        assert dropped == 0
        assert result is table

    def test_keeps_highest_position_per_key(self):
        table = _batch([1, 1, 2], ["old", "new", "other"], ["I", "U", "I"], seqs=[10, 20, 15])
        result, dropped = dedupe_keep_highest_seq(table, ["id"])

        assert dropped == 1
        assert result.column("name").to_pylist() == ["new", "other"]

    def test_keeps_highest_even_when_batch_is_out_of_order(self):
        table = _batch([1, 1], ["new", "old"], ["U", "I"], seqs=[20, 10])
        result, dropped = dedupe_keep_highest_seq(table, ["id"])

        assert dropped == 1
        assert result.column("name").to_pylist() == ["new"]

    def test_ties_keep_later_row(self):
        table = _batch([1, 1], ["first", "second"], ["U", "U"], seqs=[10, 10])
        result, _ = dedupe_keep_highest_seq(table, ["id"])

        assert result.column("name").to_pylist() == ["second"]

    def test_composite_keys(self):
        table = pa.table(
            {
                "a": pa.array([1, 1, 1], pa.int64()),
                "b": pa.array(["x", "x", "y"], pa.string()),
                CDC_OP_COLUMN: pa.array(["I", "U", "I"], pa.string()),
            }
        ).append_column(
            pa.field(CDC_SEQ_COLUMN, pa.int64(), metadata=CDC_SEQ_PROVENANCE),
            pa.array([10, 20, 30], pa.int64()),
        )
        result, dropped = dedupe_keep_highest_seq(table, ["a", "b"])

        assert dropped == 1
        assert result.column(CDC_SEQ_COLUMN).to_pylist() == [20, 30]

    def test_no_duplicates_returns_original(self):
        table = _batch([1, 2], ["a", "b"], ["I", "I"], seqs=[10, 20])
        result, dropped = dedupe_keep_highest_seq(table, ["id"])
        assert dropped == 0
        assert result is table


class TestResolveBatch:
    def test_consolidated_lane_drops_superseded_and_dedupes(self):
        table = _batch([1, 1, 2], ["old", "new", "other"], ["I", "U", "I"], seqs=[10, 20, 30])
        result, stats = resolve_batch(table, ["id"], watermark=None, cdc_write_mode="incremental_merge")

        assert stats.superseded == 0
        assert stats.duplicate_key == 1
        assert result.column("name").to_pylist() == ["new", "other"]

    def test_history_lane_keeps_every_version_of_a_key(self):
        # The companion table is append-only history: deduping it would delete versions, not
        # resolve a conflict.
        table = _batch([1, 1], ["v1", "v2"], ["I", "U"], seqs=[10, 20])
        result, stats = resolve_batch(table, ["id"], watermark=None, cdc_write_mode=SCD2_APPEND_MODE)

        assert stats.duplicate_key == 0
        assert result.column("name").to_pylist() == ["v1", "v2"]

    def test_history_lane_still_drops_already_applied_rows(self):
        # Replaying a buffer file into the companion is how duplicate history rows arise.
        table = _batch([1, 1], ["v1", "v2"], ["I", "U"], seqs=[10, 20])
        result, stats = resolve_batch(table, ["id"], watermark=15, cdc_write_mode=SCD2_APPEND_MODE)

        assert stats.superseded == 1
        assert result.column("name").to_pylist() == ["v2"]

    def test_source_owned_seq_column_disables_resolution_entirely(self):
        table = _batch([1, 1], ["old", "new"], ["I", "U"], seqs=[99, 1], engine_seq=False)
        result, stats = resolve_batch(table, ["id"], watermark=50, cdc_write_mode="incremental_merge")

        assert (stats.superseded, stats.duplicate_key) == (0, 0)
        assert result is table

    def test_noop_on_batches_without_positions(self):
        table = _batch([1, 2], ["a", "b"], ["I", "I"])
        result, stats = resolve_batch(table, ["id"], watermark=99, cdc_write_mode="incremental_merge")

        assert (stats.superseded, stats.duplicate_key) == (0, 0)
        assert result is table


class TestVerifyDeleteEnrichment:
    def test_enriched_delete_is_clean(self):
        table = _batch([1], ["alice"], ["D"])
        report = verify_delete_enrichment(table, ["id"], _existing([1], ["alice"]))

        assert report.ok
        assert report.delete_rows_checked == 1
        assert report.columns == ()

    def test_unenriched_delete_is_reported(self):
        table = _batch([1], [None], ["D"])
        report = verify_delete_enrichment(table, ["id"], _existing([1], ["alice"]))

        assert not report.ok
        assert report.rows_with_nulled_columns == 1
        assert report.columns == ("name",)

    def test_ignores_non_delete_rows(self):
        # A NULL on an UPDATE is the source's own value, not lost data.
        table = _batch([1], [None], ["U"])
        report = verify_delete_enrichment(table, ["id"], _existing([1], ["alice"]))

        assert report.ok
        assert report.delete_rows_checked == 0

    def test_ignores_deletes_with_no_existing_row(self):
        # Unmatched delete becomes a tombstone insert; there is no data to lose.
        table = _batch([2], [None], ["D"])
        report = verify_delete_enrichment(table, ["id"], _existing([1], ["alice"]))

        assert report.ok
        assert report.delete_rows_checked == 0

    def test_null_in_target_is_not_a_violation(self):
        table = _batch([1], [None], ["D"])
        report = verify_delete_enrichment(table, ["id"], _existing([1], [None]))

        assert report.ok

    @parameterized.expand(
        [("no_existing_rows", None), ("empty_existing_rows", pa.table({"id": pa.array([], pa.int64())}))]
    )
    def test_returns_empty_without_target_state(self, _name, existing):
        table = _batch([1], [None], ["D"])
        assert verify_delete_enrichment(table, ["id"], existing).ok

    def test_checked_rows_are_capped(self):
        n = MAX_VERIFIED_DELETE_ROWS + 10
        ids = list(range(n))
        table = _batch(ids, [None] * n, ["D"] * n)
        report = verify_delete_enrichment(table, ["id"], _existing(ids, [f"name{i}" for i in ids]))

        assert report.delete_rows_checked == MAX_VERIFIED_DELETE_ROWS


class TestLoadPosition:
    @parameterized.expand(
        [
            ("absent_config", None, None),
            ("empty_config", {}, None),
            ("other_lane_only", {LOAD_POSITION_CONFIG_KEY: {"users_cdc": 99}}, None),
            ("int_value", {LOAD_POSITION_CONFIG_KEY: {"users": 42}}, 42),
            # JSON round-trips can hand back strings; a bad value must read as "unknown", not 0.
            ("string_value", {LOAD_POSITION_CONFIG_KEY: {"users": "42"}}, 42),
            ("garbage_value", {LOAD_POSITION_CONFIG_KEY: {"users": "not-a-number"}}, None),
            ("null_value", {LOAD_POSITION_CONFIG_KEY: {"users": None}}, None),
        ]
    )
    def test_read(self, _name, config, expected):
        assert read_load_position(config, "users") == expected

    def test_persist_creates_the_key_and_leaves_siblings_alone(self):
        captured: dict[str, Any] = {"cdc_last_log_position": "0/ABC"}

        def fake_update(schema_id, team_id, *, mutate=None, **kwargs):
            mutate(captured)

        with patch(
            "products.warehouse_sources.backend.models.external_data_schema.update_sync_type_config_keys",
            side_effect=fake_update,
        ):
            persist_load_position("schema-1", 2, "users", 100)

        assert captured[LOAD_POSITION_CONFIG_KEY] == {"users": 100}
        # Capture's own position lives in the same JSON column and must survive.
        assert captured["cdc_last_log_position"] == "0/ABC"

    @parameterized.expand([("advances", 50, 100, 100), ("never_rewinds", 100, 50, 100), ("equal", 100, 100, 100)])
    def test_persist_is_monotonic(self, _name, existing, incoming, expected):
        captured = {LOAD_POSITION_CONFIG_KEY: {"users": existing}}

        def fake_update(schema_id, team_id, *, mutate=None, **kwargs):
            mutate(captured)

        with patch(
            "products.warehouse_sources.backend.models.external_data_schema.update_sync_type_config_keys",
            side_effect=fake_update,
        ):
            persist_load_position("schema-1", 2, "users", incoming)

        assert captured[LOAD_POSITION_CONFIG_KEY]["users"] == expected


class TestIsCdcWriteResolutionEnabled:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        # The helper memoizes per run; tests reuse ids, so a stale entry would leak between them.
        is_cdc_write_resolution_enabled.cache_clear()
        yield
        is_cdc_write_resolution_enabled.cache_clear()

    def _team(self):
        team = MagicMock()
        team.uuid = "team-uuid"
        team.organization_id = "org-id"
        return team

    @parameterized.expand([("on", True), ("off", False)])
    def test_follows_the_flag(self, _name, flag_value):
        with (
            patch("posthog.models.Team.objects") as objects,
            patch("posthoganalytics.feature_enabled", return_value=flag_value) as feature_enabled,
        ):
            objects.only.return_value.get.return_value = self._team()
            assert is_cdc_write_resolution_enabled(2, "schema-1", "run-1") is flag_value

        assert feature_enabled.call_args.kwargs["person_properties"] == {"team_id": "2", "schema_id": "schema-1"}

    def test_evaluates_once_per_run_then_again_on_the_next_run(self):
        with (
            patch("posthog.models.Team.objects") as objects,
            patch("posthoganalytics.feature_enabled", return_value=True) as feature_enabled,
        ):
            objects.only.return_value.get.return_value = self._team()
            for _ in range(5):
                assert is_cdc_write_resolution_enabled(2, "schema-1", "run-1") is True
            assert feature_enabled.call_count == 1

            # A new run re-reads it, so a flag flip lands within one run rather than one pod.
            assert is_cdc_write_resolution_enabled(2, "schema-1", "run-2") is True
            assert feature_enabled.call_count == 2

    def test_fails_closed_when_flag_service_raises(self):
        with (
            patch("posthog.models.Team.objects") as objects,
            patch("posthoganalytics.feature_enabled", side_effect=Exception("flags down")),
        ):
            objects.only.return_value.get.return_value = self._team()
            assert is_cdc_write_resolution_enabled(2, "schema-1", "run-1") is False

    def test_fails_closed_when_team_is_missing(self):
        with patch("posthog.models.Team.objects") as objects:
            objects.only.return_value.get.side_effect = Exception("no such team")
            assert is_cdc_write_resolution_enabled(2, "schema-1", "run-1") is False
