from datetime import datetime

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import PersonPropertySyncSource
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline import person_property_sync as pps

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.person_property_sync"


class TestBuildBundles:
    def test_maps_columns_and_stringifies_key(self):
        rows = [{"distinct_id": 123, "plan": "pro", "seats": 5}]
        bundles = pps.build_bundles(rows, "distinct_id", {"plan": "plan_tier", "seats": "seat_count"})
        assert bundles == [("123", {"plan_tier": "pro", "seat_count": 5})]

    @parameterized.expand(
        [
            ("null_key", [{"distinct_id": None, "plan": "pro"}], []),
            ("null_value_excluded", [{"distinct_id": "a", "plan": None}], []),
            ("missing_column_excluded", [{"distinct_id": "a"}], []),
        ]
    )
    def test_rows_without_usable_data_are_skipped(self, _name, rows, expected):
        assert pps.build_bundles(rows, "distinct_id", {"plan": "plan_tier"}) == expected

    def test_partial_bundle_keeps_present_values(self):
        rows = [{"distinct_id": "a", "plan": "pro", "seats": None}]
        assert pps.build_bundles(rows, "distinct_id", {"plan": "plan_tier", "seats": "seat_count"}) == [
            ("a", {"plan_tier": "pro"})
        ]


class TestBundleHash:
    def test_is_order_independent(self):
        assert pps.bundle_hash({"a": 1, "b": 2}) == pps.bundle_hash({"b": 2, "a": 1})

    def test_handles_non_json_scalars(self):
        # datetimes must hash without raising
        assert isinstance(pps.bundle_hash({"t": datetime(2026, 1, 1)}), str)

    def test_different_values_hash_differently(self):
        assert pps.bundle_hash({"a": 1}) != pps.bundle_hash({"a": 2})


class TestSelectChanged:
    def test_skips_unchanged_and_keeps_changed_and_new(self):
        unchanged_hash = pps.bundle_hash({"plan_tier": "pro"})
        bundles = [
            ("unchanged", {"plan_tier": "pro"}),
            ("changed", {"plan_tier": "enterprise"}),
            ("new", {"plan_tier": "free"}),
        ]
        prior = {"unchanged": unchanged_hash, "changed": pps.bundle_hash({"plan_tier": "starter"})}

        changed, new_hashes = pps.select_changed(bundles, prior)

        assert sorted(d for d, _ in changed) == ["changed", "new"]
        assert set(new_hashes) == {"changed", "new"}

    def test_last_write_wins_for_duplicate_distinct_id_in_run(self):
        bundles = [("a", {"plan_tier": "old"}), ("a", {"plan_tier": "new"})]
        changed, new_hashes = pps.select_changed(bundles, {})
        assert changed == [("a", {"plan_tier": "new"})]
        assert new_hashes["a"] == pps.bundle_hash({"plan_tier": "new"})


class TestRunOrchestration:
    """Orchestration control flow with all I/O boundaries (S3, personhog, Kafka, DB) mocked."""

    def _source(self):
        return PersonPropertySyncSource(
            source_id="source-1",
            definition_id="def-1",
            key_column="distinct_id",
            column_property_map={"plan": "plan_tier"},
        )

    @pytest.mark.asyncio
    async def test_produces_only_changed_and_existing_persons_and_advances_snapshot(self):
        team = MagicMock(api_token="tok", project_id=7)
        rows = [
            {"distinct_id": "a", "plan": "pro"},
            {"distinct_id": "b", "plan": "free"},
            {"distinct_id": "ghost", "plan": "x"},
        ]
        with (
            patch(f"{_MODULE}.person_property_sync_sources_for", return_value=[self._source()]),
            patch(f"{_MODULE}.Team") as team_cls,
            patch(f"{_MODULE}._read_staged_rows", new=AsyncMock(return_value=rows)),
            patch(f"{_MODULE}._read_snapshot_hashes", new=AsyncMock(return_value={})),
            patch(f"{_MODULE}._filter_existing_persons", return_value={"a", "b"}) as existing,
            patch(f"{_MODULE}._produce_intents", return_value=2) as produce,
            patch(f"{_MODULE}._write_snapshot_hashes", new=AsyncMock()) as write_snapshot,
            patch(f"{_MODULE}._stamp_provenance") as stamp,
            patch(f"{_MODULE}._clear_staged", new=AsyncMock()) as clear,
        ):
            team_cls.objects.get.return_value = team
            result = await pps.run_person_property_sync(team_id=1, schema_id="schema-1", job_id="job-1")

        # ghost is filtered out; only a and b are produced.
        produced_items = produce.call_args.args[2]
        assert sorted(d for d, _ in produced_items) == ["a", "b"]
        assert result.produced == 2

        # snapshot advanced only for produced ids.
        assert write_snapshot.await_args is not None
        written = write_snapshot.await_args.args[3]
        assert set(written) == {"a", "b"}

        existing.assert_called_once()
        stamp.assert_called_once()
        clear.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_sources_is_a_noop(self):
        with (
            patch(f"{_MODULE}.person_property_sync_sources_for", return_value=None),
            patch(f"{_MODULE}._read_staged_rows", new=AsyncMock()) as read,
            patch(f"{_MODULE}._clear_staged", new=AsyncMock()) as clear,
        ):
            result = await pps.run_person_property_sync(team_id=1, schema_id="schema-1", job_id="job-1")

        assert result.sources == 0
        read.assert_not_awaited()
        clear.assert_not_awaited()
