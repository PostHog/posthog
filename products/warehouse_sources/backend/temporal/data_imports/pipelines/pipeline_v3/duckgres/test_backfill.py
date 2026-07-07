import uuid

import pytest

from posthog.models import DuckgresSinkSchemaState, Organization, Team

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres import (
    backfill as backfill_module,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.backfill import (
    _bootstrap_state_rows,
    _plan_pending,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.backfill_queue import (
    backfill_run_uuid,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.backfill_snapshot import (
    CHUNK_TARGET_BYTES,
    BackfillChunk,
    _committed_batch_keys,
    _group_files_into_chunks,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities import create_job_model

_State = DuckgresSinkSchemaState.State


def _sink_state(team: Team, state: str) -> DuckgresSinkSchemaState:
    return DuckgresSinkSchemaState.objects.create(team=team, schema_id=uuid.uuid4(), state=state)


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


@pytest.mark.django_db
def test_bootstrap_state_rows_streams_batches_and_skips_existing(monkeypatch):
    # A single team can own far more schemas than fit in one bulk_create, so the
    # bootstrap streams and flushes in batches. Force a tiny batch so the schemas
    # below straddle a flush boundary — guards against the final partial batch
    # being dropped and against the anti-join re-creating rows that already exist.
    monkeypatch.setattr(backfill_module, "BOOTSTRAP_BATCH_SIZE", 2)
    # The v3-source gate does a network flag eval; stub it on so this test stays
    # about the streaming/batching path, not flag resolution.
    monkeypatch.setattr(create_job_model, "is_pipeline_v3_enabled", lambda team_id, source_type: True)

    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org)
    source = ExternalDataSource.objects.create(
        team_id=team.pk,
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        status="Completed",
        source_type="Postgres",
    )
    table = DataWarehouseTable.objects.create(name="t", format="Parquet", team=team, url_pattern="https://b.s3/data/*")

    def _schema(name, sync_type, *, with_table):
        return ExternalDataSchema.objects.create(
            team_id=team.pk, source=source, name=name, sync_type=sync_type, table=table if with_table else None
        )

    # Only incremental-with-a-table needs priming; the rest land straight in PRIMED.
    needs_priming = _schema("incremental", ExternalDataSchema.SyncType.INCREMENTAL, with_table=True)
    full_refresh = _schema("full_refresh", ExternalDataSchema.SyncType.FULL_REFRESH, with_table=True)
    cdc = _schema("cdc", ExternalDataSchema.SyncType.CDC, with_table=True)
    no_table = _schema("no_table", ExternalDataSchema.SyncType.INCREMENTAL, with_table=False)

    _bootstrap_state_rows([team.pk])

    states = {s.schema_id: s.state for s in DuckgresSinkSchemaState.objects.all()}
    assert states == {
        needs_priming.id: DuckgresSinkSchemaState.State.PENDING_BACKFILL,
        full_refresh.id: DuckgresSinkSchemaState.State.PRIMED,
        cdc.id: DuckgresSinkSchemaState.State.PRIMED,
        no_table.id: DuckgresSinkSchemaState.State.PRIMED,
    }

    # Re-running must not duplicate or revert anything — the anti-join skips all four.
    _bootstrap_state_rows([team.pk])
    assert DuckgresSinkSchemaState.objects.count() == 4


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


@pytest.mark.django_db
class TestPlanPendingConcurrencyCaps:
    # Caps are patched to explicit values so these stay deterministic if the
    # production constants are later tuned. _plan_one is the queue-DB + Delta
    # boundary; blocked candidates must never reach it, claimed ones must.

    def test_global_cap_blocks_further_claims(self, monkeypatch):
        monkeypatch.setattr(backfill_module, "MAX_CONCURRENT_BACKFILLS_GLOBAL", 2)
        monkeypatch.setattr(backfill_module, "_plan_one", lambda state: pytest.fail("planned past the global cap"))

        busy_team = Team.objects.create(organization=Organization.objects.create(name="busy"), name="t")
        for _ in range(2):
            _sink_state(busy_team, _State.BACKFILLING)

        candidate = _sink_state(
            Team.objects.create(organization=Organization.objects.create(name="new"), name="t"), _State.PENDING_BACKFILL
        )

        _plan_pending(team_ids=[candidate.team_id])

        candidate.refresh_from_db()
        # Different org, so per-org never blocks it — only the full global budget does.
        assert candidate.state == _State.PENDING_BACKFILL

    def test_per_org_cap_blocks_same_org(self, monkeypatch):
        monkeypatch.setattr(backfill_module, "MAX_CONCURRENT_BACKFILLS_PER_ORG", 1)
        monkeypatch.setattr(backfill_module, "MAX_CONCURRENT_BACKFILLS_GLOBAL", 99)  # global is not the limiter here
        monkeypatch.setattr(backfill_module, "_plan_one", lambda state: pytest.fail("planned past the per-org cap"))

        team = Team.objects.create(organization=Organization.objects.create(name="org"), name="t")
        _sink_state(team, _State.BACKFILLING)
        candidate = _sink_state(team, _State.PENDING_BACKFILL)

        _plan_pending(team_ids=[team.id])

        candidate.refresh_from_db()
        assert candidate.state == _State.PENDING_BACKFILL

    def test_under_cap_claims_and_plans(self, monkeypatch):
        monkeypatch.setattr(backfill_module, "MAX_CONCURRENT_BACKFILLS_PER_ORG", 1)
        monkeypatch.setattr(backfill_module, "MAX_CONCURRENT_BACKFILLS_GLOBAL", 5)
        planned: list = []
        monkeypatch.setattr(backfill_module, "_plan_one", lambda state: planned.append(state.id))

        candidate = _sink_state(
            Team.objects.create(organization=Organization.objects.create(name="org"), name="t"),
            _State.PENDING_BACKFILL,
        )

        _plan_pending(team_ids=[candidate.team_id])

        candidate.refresh_from_db()
        assert candidate.state == _State.BACKFILLING
        assert planned == [candidate.id]


@pytest.mark.django_db
class TestBootstrapV3SourceGate:
    # warehouse-pipelines-v3 (is_pipeline_v3_enabled) is the network-flag boundary;
    # stub it so the assertion is on which schemas get a state row.
    def test_only_v3_sources_are_primed(self, monkeypatch):
        from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource

        monkeypatch.setattr(
            create_job_model,
            "is_pipeline_v3_enabled",
            lambda team_id, source_type: source_type == "Postgres",
        )

        team = Team.objects.create(organization=Organization.objects.create(name="org"), name="t")
        v3_source = ExternalDataSource.objects.create(
            team=team, source_id="s1", connection_id="c1", source_type="Postgres", status="Running"
        )
        non_v3_source = ExternalDataSource.objects.create(
            team=team, source_id="s2", connection_id="c2", source_type="Stripe", status="Running"
        )
        v3_schema = ExternalDataSchema.objects.create(team=team, name="pg", source=v3_source)
        non_v3_schema = ExternalDataSchema.objects.create(team=team, name="stripe", source=non_v3_source)

        backfill_module._bootstrap_state_rows([team.id])

        primed = set(DuckgresSinkSchemaState.objects.filter(team=team).values_list("schema_id", flat=True))
        assert v3_schema.id in primed
        assert non_v3_schema.id not in primed
