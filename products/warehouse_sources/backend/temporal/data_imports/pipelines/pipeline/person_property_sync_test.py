from datetime import datetime

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized

from posthog.models import Organization, PropertyDefinition, Team

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
            patch(f"{_MODULE}._filter_existing_ids", return_value={"a", "b"}) as existing,
            patch(f"{_MODULE}._produce_intents", return_value=2) as produce,
            patch(f"{_MODULE}._write_snapshot_hashes", new=AsyncMock()) as write_snapshot,
            patch(f"{_MODULE}._stamp_provenance") as stamp,
            patch(f"{_MODULE}._clear_staged", new=AsyncMock()) as clear,
        ):
            team_cls.objects.get.return_value = team
            result = await pps.run_person_property_sync(team_id=1, schema_id="schema-1", job_id="job-1")

        # ghost is filtered out; only a and b are produced.
        produced_items = produce.call_args.args[3]
        assert sorted(d for d, _ in produced_items) == ["a", "b"]
        assert result.produced == 2

        # one per-source result is recorded for the recorder to persist.
        assert [ps.source_id for ps in result.per_source] == ["source-1"]
        assert result.per_source[0].produced == 2
        assert result.per_source[0].existing == 2

        # snapshot advanced only for produced ids (args: team, schema, source, run_token, hashes).
        assert write_snapshot.await_args is not None
        assert write_snapshot.await_args.args[3] == "job-1"
        written = write_snapshot.await_args.args[4]
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


class TestReadDeltaBundles:
    """The backfill's Delta reader accumulates last-write-wins per source, scoped to each source's map."""

    def _dataset(self, rows, columns):
        import pyarrow as pa  # local import, mirrors the module's optional-dep handling

        batch = pa.RecordBatch.from_pylist(rows)
        dataset = MagicMock()
        dataset.schema.names = columns
        dataset.to_batches.return_value = [batch]
        return dataset

    def test_accumulates_per_source_last_write_wins(self):
        rows = [
            {"distinct_id": "a", "plan": "free"},
            {"distinct_id": "a", "plan": "pro"},  # later row wins
            {"distinct_id": "b", "plan": "team"},
        ]
        sources = [
            PersonPropertySyncSource("s1", "d1", "distinct_id", {"plan": "plan_tier"}),
            PersonPropertySyncSource("s2", "d2", "distinct_id", {"plan": "tier"}),
        ]
        fake_dt = MagicMock()
        fake_dt.to_pyarrow_dataset.return_value = self._dataset(rows, ["distinct_id", "plan"])
        with patch("deltalake.DeltaTable") as dt_cls:
            dt_cls.is_deltatable.return_value = True
            dt_cls.return_value = fake_dt
            accumulated, rows_read = pps._read_delta_bundles("s3://uri", {}, sources)

        assert rows_read == 3
        assert accumulated["s1"] == {"a": {"plan_tier": "pro"}, "b": {"plan_tier": "team"}}
        assert accumulated["s2"] == {"a": {"tier": "pro"}, "b": {"tier": "team"}}

    def test_missing_table_returns_empty(self):
        sources = [PersonPropertySyncSource("s1", "d1", "distinct_id", {"plan": "plan_tier"})]
        with patch("deltalake.DeltaTable") as dt_cls:
            dt_cls.is_deltatable.return_value = False
            accumulated, rows_read = pps._read_delta_bundles("s3://uri", {}, sources)
        assert accumulated == {"s1": {}} and rows_read == 0


class TestBackfillOrchestration:
    """One backfill reads the table once and upserts every enabled person source on the schema."""

    @pytest.mark.asyncio
    async def test_reads_once_and_produces_per_source(self):
        team = MagicMock(api_token="tok")
        schema = MagicMock()
        schema.folder_path.return_value = "team_1_stripe_schema-1"
        # The backfill resolves the Delta folder from the loader's actual folder name, not normalized_name.
        schema.resolved_s3_folder_name = "charges"
        schema.name = "charges"
        sources = [
            PersonPropertySyncSource("s1", "d1", "distinct_id", {"plan": "plan_tier"}),
            PersonPropertySyncSource("s2", "d2", "distinct_id", {"plan": "tier"}),
        ]
        accumulated = {"s1": {"a": {"plan_tier": "pro"}}, "s2": {"a": {"tier": "pro"}}}
        with (
            patch(f"{_MODULE}.person_property_sync_sources_for", return_value=sources),
            patch(f"{_MODULE}._get_schema", return_value=schema),
            patch(f"{_MODULE}.Team") as team_cls,
            patch(f"{_MODULE}.delta_storage_options", return_value={}),
            patch(f"{_MODULE}._read_delta_bundles", return_value=(accumulated, 5)) as read_delta,
            patch(f"{_MODULE}._read_snapshot_hashes", new=AsyncMock(return_value={})),
            patch(f"{_MODULE}._filter_existing_ids", return_value={"a"}),
            patch(f"{_MODULE}._produce_intents", return_value=1) as produce,
            patch(f"{_MODULE}._write_snapshot_hashes", new=AsyncMock()) as write_snapshot,
            patch(f"{_MODULE}._stamp_provenance"),
        ):
            team_cls.objects.get.return_value = team
            result = await pps.run_person_property_backfill(team_id=1, schema_id="schema-1", trigger="manual")

        # The table is read exactly once, though two sources map it.
        read_delta.assert_called_once()
        assert result.sources == 2
        assert result.rows_read == 5
        assert result.produced == 2  # one produced per source
        assert sorted(ps.source_id for ps in result.per_source) == ["s1", "s2"]
        # Both sources write a snapshot file under the shared backfill run token.
        assert write_snapshot.await_count == 2
        assert all(call.args[3] == pps.BACKFILL_RUN_TOKEN for call in write_snapshot.await_args_list)
        assert produce.call_count == 2

    @pytest.mark.asyncio
    async def test_missing_schema_is_a_noop(self):
        sources = [PersonPropertySyncSource("s1", "d1", "distinct_id", {"plan": "plan_tier"})]
        with (
            patch(f"{_MODULE}.person_property_sync_sources_for", return_value=sources),
            patch(f"{_MODULE}._get_schema", return_value=None),
            patch(f"{_MODULE}._read_delta_bundles") as read_delta,
        ):
            result = await pps.run_person_property_backfill(team_id=1, schema_id="schema-1", trigger="backfill")

        assert result.sources == 0
        read_delta.assert_not_called()


class _FakeS3:
    """Minimal in-memory stand-in for the async s3fs client the snapshot helpers use — enough to store
    real parquet bytes and list/read/delete them. A monotonic counter stamps LastModified so ordering
    is deterministic without a real clock."""

    def __init__(self):
        self.store: dict[str, bytes] = {}
        self.times: dict[str, int] = {}
        self._clock = 0

    async def _ls(self, path, detail=True):
        prefix = pps._s3_key(path).rstrip("/") + "/"
        entries = [
            {"Key": key, "type": "file", "LastModified": self.times[key]}
            for key in self.store
            if key.startswith(prefix)
        ]
        if not entries:
            raise FileNotFoundError(path)
        return entries

    async def _cat_file(self, path):
        return self.store[pps._s3_key(path)]

    async def _pipe_file(self, path, data):
        self._clock += 1
        key = pps._s3_key(path)
        self.store[key] = data
        self.times[key] = self._clock

    async def _rm(self, paths, recursive=False):
        for path in [paths] if isinstance(paths, str) else paths:
            key = pps._s3_key(path)
            self.store.pop(key, None)
            self.times.pop(key, None)


def _fake_s3_patch(fake):
    import contextlib

    @contextlib.asynccontextmanager
    async def _cm():
        yield fake

    return patch(f"{_MODULE}.aget_s3_client", lambda: _cm())


class TestSnapshotCompaction:
    """_write_snapshot_hashes compacts the snapshot folder as it writes, so its history can't grow one
    file per run (which the reader would then download in full on every later run)."""

    @pytest.mark.asyncio
    async def test_write_compacts_prior_files_and_preserves_union(self):
        fake = _FakeS3()
        with _fake_s3_patch(fake):
            await pps._write_snapshot_hashes(1, "s", "src", "job-1", {"a": "h1", "b": "h1"})
            await pps._write_snapshot_hashes(1, "s", "src", "job-2", {"b": "h2", "c": "h2"})

            keys = await pps._list_snapshot_files(fake, pps._snapshot_prefix(1, "s", "src"))
            hashes = await pps._read_snapshot_hashes(1, "s", "src")

        # Two producing runs collapse to a single file whose union is newest-wins (b came from job-2).
        assert len(keys) == 1
        assert hashes == {"a": "h1", "b": "h2", "c": "h2"}

    @pytest.mark.asyncio
    async def test_repeated_run_token_overwrites_its_own_file(self):
        fake = _FakeS3()
        with _fake_s3_patch(fake):
            # Backfills share one filename; the second write must overwrite it, not delete it as "stale".
            await pps._write_snapshot_hashes(1, "s", "src", pps.BACKFILL_RUN_TOKEN, {"a": "h1"})
            await pps._write_snapshot_hashes(1, "s", "src", pps.BACKFILL_RUN_TOKEN, {"a": "h2", "b": "h2"})

            keys = await pps._list_snapshot_files(fake, pps._snapshot_prefix(1, "s", "src"))
            hashes = await pps._read_snapshot_hashes(1, "s", "src")

        assert len(keys) == 1
        assert hashes == {"a": "h2", "b": "h2"}


class TestGroupTarget:
    """The group branch: a group source produces a $groupidentify-shaped intent and checks group
    existence, keyed per group type."""

    def _group_source(self):
        return PersonPropertySyncSource("s1", "d1", "group_key", {"plan": "tier"}, target="group", group_type_index=0)

    def test_produce_intents_group_payload(self):
        captured: list[dict] = []
        producer = MagicMock()
        producer.produce.side_effect = lambda **kw: captured.append(kw)
        with patch(f"{_MODULE}.producer_scope") as producer_scope:
            producer_scope.return_value.__enter__.return_value = producer
            produced = pps._produce_intents(
                1,
                "tok",
                self._group_source(),
                [("acme", {"tier": "pro"})],
                team_uuid="team-uuid",
                group_type_name="organization",
            )
        assert produced == 1
        data = captured[0]["data"]
        assert data["kind"] == "group"
        assert data["group_type"] == "organization"
        assert data["group_key"] == "acme"
        assert data["distinct_id"] == "team-uuid"  # $groupidentify placeholder
        assert data["properties"] == {"tier": "pro"}
        # keyed per (team, group_type_index, group_key) so per-group ordering is preserved
        assert captured[0]["key"] == "1:0:acme"

    def test_filter_existing_ids_uses_group_lookup(self):
        group = MagicMock(group_key="acme")
        with patch(f"{_MODULE}.get_groups_by_identifiers", return_value=[group]) as lookup:
            result = pps._filter_existing_ids(9, self._group_source(), ["acme", "ghost"])
        lookup.assert_called_once_with(9, 0, ["acme", "ghost"])
        assert result == {"acme"}  # ghost dropped: no existing group

    @pytest.mark.asyncio
    async def test_unresolved_group_type_skips_producing(self):
        # If the group type can't be resolved (deleted/misconfigured), the consumer would DLQ every
        # $groupidentify missing a group_type — so the source must be skipped, not produced.
        team = MagicMock(api_token="tok", uuid="team-uuid")
        rows = [{"group_key": "acme", "plan": "pro"}]
        with (
            patch(f"{_MODULE}.person_property_sync_sources_for", return_value=[self._group_source()]),
            patch(f"{_MODULE}.Team") as team_cls,
            patch(f"{_MODULE}._read_staged_rows", new=AsyncMock(return_value=rows)),
            patch(f"{_MODULE}._read_snapshot_hashes", new=AsyncMock(return_value={})),
            patch(f"{_MODULE}._filter_existing_ids", return_value={"acme"}),
            patch(f"{_MODULE}._group_type_name", return_value=None),
            patch(f"{_MODULE}._produce_intents", return_value=1) as produce,
            patch(f"{_MODULE}._write_snapshot_hashes", new=AsyncMock()) as write_snapshot,
            patch(f"{_MODULE}._stamp_provenance") as stamp,
            patch(f"{_MODULE}._clear_staged", new=AsyncMock()),
        ):
            team_cls.objects.get.return_value = team
            result = await pps.run_person_property_sync(team_id=1, schema_id="schema-1", job_id="job-1")

        produce.assert_not_called()
        stamp.assert_not_called()
        write_snapshot.assert_not_awaited()
        assert result.produced == 0


@pytest.mark.django_db
class TestStampProvenance:
    """`_stamp_provenance` updates existing property definitions with warehouse provenance, folding a
    per-property description into the origin when the source carries one."""

    def _team(self):
        org = Organization.objects.create(name="o")
        return Team.objects.create(organization=org, name="t")

    def test_folds_descriptions_into_provenance_only_where_present(self):
        team = self._team()
        PropertyDefinition.objects.create(team=team, name="plan_tier", type=PropertyDefinition.Type.PERSON)
        PropertyDefinition.objects.create(team=team, name="seat_count", type=PropertyDefinition.Type.PERSON)
        source = PersonPropertySyncSource(
            "s1",
            "d1",
            "distinct_id",
            {"plan": "plan_tier", "seats": "seat_count"},
            property_descriptions={"plan_tier": "The plan tier"},
        )

        pps._stamp_provenance(team.id, "schema-1", source, ["plan_tier", "seat_count"])

        described = PropertyDefinition.objects.get(team=team, name="plan_tier")
        plain = PropertyDefinition.objects.get(team=team, name="seat_count")
        assert described.warehouse_origin["custom_property_source_id"] == "s1"
        assert described.warehouse_origin["description"] == "The plan tier"
        # A property without a configured description carries provenance but no description key.
        assert plain.warehouse_origin["custom_property_source_id"] == "s1"
        assert "description" not in plain.warehouse_origin

    def test_group_target_stamps_only_matching_group_type(self):
        team = self._team()
        PropertyDefinition.objects.create(
            team=team, name="tier", type=PropertyDefinition.Type.GROUP, group_type_index=0
        )
        other = PropertyDefinition.objects.create(
            team=team, name="tier", type=PropertyDefinition.Type.GROUP, group_type_index=1
        )
        source = PersonPropertySyncSource("s1", "d1", "group_key", {"plan": "tier"}, target="group", group_type_index=0)

        pps._stamp_provenance(team.id, "schema-1", source, ["tier"])

        assert PropertyDefinition.objects.get(id=other.id).warehouse_origin is None
        stamped = PropertyDefinition.objects.get(team=team, name="tier", group_type_index=0)
        assert stamped.warehouse_origin["custom_property_source_id"] == "s1"
