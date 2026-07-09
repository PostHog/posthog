import uuid
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, Mock, patch

from django.utils import timezone

import psycopg

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
    enqueue_chunks,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.backfill_snapshot import (
    CHUNK_TARGET_BYTES,
    BackfillChunk,
    _committed_batch_keys,
    _group_files_into_chunks,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.jobs_db import (
    RETIRE_KIND_SUPERSEDED_BY_REPLACE,
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


# Stands in for the queue-DB connection in _reconcile_one: the SQL results are
# the boundary; the assertions are on the Django state writes.
class _FakeQueueConn:
    def __init__(self, results: list) -> None:
        self._results = list(results)

    def execute(self, *args, **kwargs):
        row = self._results.pop(0)
        return SimpleNamespace(fetchone=lambda: row)


def _fake_conn(results: list) -> psycopg.Connection[Any]:
    return cast("psycopg.Connection[Any]", _FakeQueueConn(results))


@pytest.mark.django_db
class TestFailureStreak:
    def _team(self) -> Team:
        return Team.objects.create(organization=Organization.objects.create(name="org"), name="t")

    def _backdate(self, state: DuckgresSinkSchemaState, seconds: int) -> None:
        DuckgresSinkSchemaState.objects.filter(id=state.id).update(
            updated_at=timezone.now() - timedelta(seconds=seconds)
        )

    def test_plan_failure_records_streak_and_first_failed_at_once(self, monkeypatch):
        monkeypatch.setattr(backfill_module, "_plan_one", Mock(side_effect=RuntimeError("no files in log segment")))
        candidate = _sink_state(self._team(), _State.PENDING_BACKFILL)

        _plan_pending(team_ids=[candidate.team_id])
        candidate.refresh_from_db()
        assert candidate.state == _State.PENDING_BACKFILL
        assert candidate.consecutive_failures == 1
        assert candidate.first_failed_at is not None
        assert "no files in log segment" in (candidate.last_error or "")
        streak_started_at = candidate.first_failed_at

        # Second failed attempt: the streak grows but the high-watermark anchor
        # must not move — it is the durable "backfill owed since" timestamp.
        self._backdate(candidate, seconds=3600)  # clear the retry backoff window
        _plan_pending(team_ids=[candidate.team_id])
        candidate.refresh_from_db()
        assert candidate.consecutive_failures == 2
        assert candidate.first_failed_at == streak_started_at

    def test_unsupported_table_parks_needs_resync_with_streak(self, monkeypatch):
        monkeypatch.setattr(
            backfill_module, "_plan_one", Mock(side_effect=backfill_module.BackfillUnsupportedError("deletion vectors"))
        )
        candidate = _sink_state(self._team(), _State.PENDING_BACKFILL)

        _plan_pending(team_ids=[candidate.team_id])

        candidate.refresh_from_db()
        assert candidate.state == _State.NEEDS_RESYNC
        assert candidate.consecutive_failures == 1
        assert candidate.first_failed_at is not None

    def test_capacity_revert_does_not_start_a_streak(self, monkeypatch):
        # Pre-check passes, post-claim re-check trips: the revert is pacing, not
        # failure — recording it would misclassify busy-but-healthy orgs.
        monkeypatch.setattr(backfill_module, "_org_at_capacity", Mock(side_effect=[False, True]))
        monkeypatch.setattr(backfill_module, "_plan_one", Mock(side_effect=AssertionError("must not plan")))
        candidate = _sink_state(self._team(), _State.PENDING_BACKFILL)

        _plan_pending(team_ids=[candidate.team_id])

        candidate.refresh_from_db()
        assert candidate.state == _State.PENDING_BACKFILL
        assert candidate.consecutive_failures == 0
        assert candidate.first_failed_at is None

    @freeze_time("2026-01-15T12:00:00Z")
    def test_backoff_skips_recent_failure_then_retries_after_window(self, monkeypatch):
        plan_one = Mock(side_effect=RuntimeError("still broken"))
        monkeypatch.setattr(backfill_module, "_plan_one", plan_one)
        candidate = _sink_state(self._team(), _State.PENDING_BACKFILL)
        DuckgresSinkSchemaState.objects.filter(id=candidate.id).update(
            consecutive_failures=10, first_failed_at=timezone.now()
        )

        # Streak at cap, updated_at fresh: inside the backoff window, no attempt.
        _plan_pending(team_ids=[candidate.team_id])
        plan_one.assert_not_called()

        # Past the max window (cap * max jitter): retried — backoff delays, never gives up.
        self._backdate(candidate, seconds=int(backfill_module.RETRY_BACKOFF_CAP_SECONDS * 1.2) + 1)
        _plan_pending(team_ids=[candidate.team_id])
        plan_one.assert_called_once()

    @freeze_time("2026-01-15T12:00:00Z")
    def test_mark_primed_resets_streak(self):
        candidate = _sink_state(self._team(), _State.BACKFILLING)
        DuckgresSinkSchemaState.objects.filter(id=candidate.id).update(
            consecutive_failures=5,
            first_failed_at=timezone.now(),
            last_error="boom",
            backfill_run_uuid="run-1",
        )

        backfill_module.mark_primed(str(candidate.schema_id), run_uuid="run-1")

        candidate.refresh_from_db()
        assert candidate.state == _State.PRIMED
        assert candidate.consecutive_failures == 0
        assert candidate.first_failed_at is None
        assert candidate.last_error is None

    @freeze_time("2026-01-15T12:00:00Z")
    def test_replan_backfill_resets_streak(self):
        candidate = _sink_state(self._team(), _State.NEEDS_RESYNC)
        DuckgresSinkSchemaState.objects.filter(id=candidate.id).update(
            consecutive_failures=5, first_failed_at=timezone.now(), last_error="boom"
        )

        backfill_module.replan_backfill(str(candidate.schema_id))

        candidate.refresh_from_db()
        assert candidate.state == _State.PENDING_BACKFILL
        assert candidate.consecutive_failures == 0
        assert candidate.first_failed_at is None

    @freeze_time("2026-01-15T12:00:00Z")
    def test_stuck_gauges_derive_from_state_without_any_batches(self):
        # The whole point of the state-derived gauges: a wedged schema stays
        # visible with zero rows in the (retention-bounded) batch queue.
        team = self._team()
        stuck = _sink_state(team, _State.PENDING_BACKFILL)
        DuckgresSinkSchemaState.objects.filter(id=stuck.id).update(
            consecutive_failures=backfill_module.FAILING_THRESHOLD,
            first_failed_at=timezone.now() - timedelta(days=20),
        )
        _sink_state(team, _State.PENDING_BACKFILL)  # healthy: not counted

        backfill_module._emit_state_gauge()

        assert backfill_module.STUCK_BACKFILL_GAUGE._value.get() == 1
        assert backfill_module.STUCK_BACKFILL_OLDEST_AGE_GAUGE._value.get() == pytest.approx(
            timedelta(days=20).total_seconds(), rel=0.01
        )

    def test_reconcile_escalates_wedged_run_to_failing_once(self):
        # A duckgres 'failed' status is terminal — the run never retries itself,
        # so reconcile must classify the schema failing immediately or its
        # backlog sits in the pageable healthy bucket forever.
        candidate = _sink_state(self._team(), _State.BACKFILLING)
        DuckgresSinkSchemaState.objects.filter(id=candidate.id).update(
            backfill_run_uuid="bf-run", chunk_count=5, chunks_applied=1
        )
        candidate.refresh_from_db()

        backfill_module._reconcile_one(_fake_conn([(1,), ("chunk exploded", None)]), candidate)

        candidate.refresh_from_db()
        assert candidate.state == _State.BACKFILLING
        assert candidate.consecutive_failures >= backfill_module.FAILING_THRESHOLD
        assert candidate.first_failed_at is not None
        assert candidate.last_error == "chunk exploded"
        streak_started_at = candidate.first_failed_at
        marked_at = candidate.updated_at

        # A steady wedge stops churning the row once recorded (same error,
        # streak already at threshold, anchor stamped).
        backfill_module._reconcile_one(_fake_conn([(1,), ("chunk exploded", None)]), candidate)
        candidate.refresh_from_db()
        assert candidate.first_failed_at == streak_started_at
        assert candidate.updated_at == marked_at

    def test_reconcile_supersession_is_streak_neutral(self):
        # Retirement by a newer live replace run is normal lifecycle, not failure.
        candidate = _sink_state(self._team(), _State.BACKFILLING)
        DuckgresSinkSchemaState.objects.filter(id=candidate.id).update(backfill_run_uuid="bf-run", chunk_count=5)
        candidate.refresh_from_db()

        backfill_module._reconcile_one(_fake_conn([(0,), ("superseded", RETIRE_KIND_SUPERSEDED_BY_REPLACE)]), candidate)

        candidate.refresh_from_db()
        assert candidate.state == _State.NEEDS_RESYNC
        assert candidate.consecutive_failures == 0
        assert candidate.first_failed_at is None

    @freeze_time("2026-01-15T12:00:00Z")
    def test_reconcile_chunk_progress_resets_streak(self):
        # Chunks landing again is forward progress: the streak (and with it the
        # failing classification) must end, or a healed schema stays unalerted.
        candidate = _sink_state(self._team(), _State.BACKFILLING)
        DuckgresSinkSchemaState.objects.filter(id=candidate.id).update(
            backfill_run_uuid="bf-run",
            chunk_count=5,
            chunks_applied=1,
            snapshot_version=None,
            consecutive_failures=4,
            first_failed_at=timezone.now(),
        )
        candidate.refresh_from_db()

        # applied=3 (progress), no failed batch, all 5 chunk rows still present.
        backfill_module._reconcile_one(_fake_conn([(3,), None, (5,)]), candidate)

        candidate.refresh_from_db()
        assert candidate.chunks_applied == 3
        assert candidate.consecutive_failures == 0
        assert candidate.first_failed_at is None


# transaction=True: failing_schema_ids calls close_old_connections (thread-entry
# hygiene for the consumer's sync_to_async maintenance calls), which severs the
# TestCase-style transaction-wrapped connection.
@pytest.mark.django_db(transaction=True)
class TestFailingSchemaClassification:
    def test_failing_schema_ids_classification(self):
        team = Team.objects.create(organization=Organization.objects.create(name="org"), name="t")

        def _state_with(state: str, failures: int) -> DuckgresSinkSchemaState:
            row = _sink_state(team, state)
            DuckgresSinkSchemaState.objects.filter(id=row.id).update(consecutive_failures=failures)
            return row

        healthy_pending = _state_with(_State.PENDING_BACKFILL, 0)
        below_threshold = _state_with(_State.PENDING_BACKFILL, backfill_module.FAILING_THRESHOLD - 1)
        failing_pending = _state_with(_State.PENDING_BACKFILL, backfill_module.FAILING_THRESHOLD)
        failing_backfilling = _state_with(_State.BACKFILLING, backfill_module.FAILING_THRESHOLD)
        parked = _state_with(_State.NEEDS_RESYNC, 0)
        # PRIMED is never failing, even with a stale streak left behind.
        primed_stale_streak = _state_with(_State.PRIMED, 10)

        assert set(backfill_module.failing_schema_ids([team.id])) == {
            str(failing_pending.schema_id),
            str(failing_backfilling.schema_id),
            str(parked.schema_id),
        }
        assert backfill_module.failing_schema_ids([]) == []
        for row in (healthy_pending, below_threshold, primed_stale_streak):
            assert str(row.schema_id) not in backfill_module.failing_schema_ids(None)


@pytest.mark.django_db
class TestGenerationPinnedPromotions:
    def _team(self) -> Team:
        return Team.objects.create(organization=Organization.objects.create(name="org"), name="t")

    def _backfilling_state(self, run_uuid: str | None, chunk_count: int = 2) -> DuckgresSinkSchemaState:
        return DuckgresSinkSchemaState.objects.create(
            team=self._team(),
            schema_id=uuid.uuid4(),
            state=DuckgresSinkSchemaState.State.BACKFILLING,
            backfill_run_uuid=run_uuid,
            chunk_count=chunk_count,
            chunks_applied=0,
        )

    def test_mark_primed_ignores_stale_generation(self):
        # A replan can retire run R1 and plan R2 while R1's final swap is still
        # committing; R1's late mark_primed must not promote R2's row.
        row = self._backfilling_state("run-r2")

        backfill_module.mark_primed(str(row.schema_id), run_uuid="run-r1", chunks_applied=2)
        row.refresh_from_db()
        assert row.state == DuckgresSinkSchemaState.State.BACKFILLING

        backfill_module.mark_primed(str(row.schema_id), run_uuid="run-r2", chunks_applied=2)
        row.refresh_from_db()
        assert row.state == DuckgresSinkSchemaState.State.PRIMED
        assert row.chunks_applied == 2

    def test_reconcile_promotion_ignores_stale_generation(self):
        # The reconciler's applied-count evidence belongs to the run it read at
        # the top of the pass; a replan swapping generations mid-pass must not
        # be promoted on the old run's counts.
        row = self._backfilling_state("run-r1")
        stale_snapshot = DuckgresSinkSchemaState.objects.get(id=row.id)
        DuckgresSinkSchemaState.objects.filter(id=row.id).update(backfill_run_uuid="run-r2")

        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = (stale_snapshot.chunk_count,)
        backfill_module._reconcile_one(conn, stale_snapshot)

        row.refresh_from_db()
        assert row.state == DuckgresSinkSchemaState.State.BACKFILLING
        assert row.backfill_run_uuid == "run-r2"

    def test_plan_one_defers_while_replace_run_inflight(self):
        team = self._team()
        source = ExternalDataSource.objects.create(
            team=team, source_id="s", connection_id="c", source_type="Stripe", status="Running"
        )
        schema = ExternalDataSchema.objects.create(team=team, source=source, name="customers")
        row = DuckgresSinkSchemaState.objects.create(
            team=team,
            schema_id=schema.id,
            state=DuckgresSinkSchemaState.State.BACKFILLING,
            backfill_run_uuid=None,
        )

        with (
            patch.object(backfill_module, "_has_inflight_replace_run", return_value=True),
            patch.object(backfill_module, "resolve_snapshot_plan") as resolve,
            patch.object(backfill_module.psycopg, "connect") as connect,
        ):
            connect.return_value.__enter__.return_value = MagicMock()
            backfill_module._plan_one(row)

        resolve.assert_not_called()
        row.refresh_from_db()
        assert row.backfill_run_uuid is None
        assert row.state == DuckgresSinkSchemaState.State.BACKFILLING


@pytest.mark.django_db
class TestDeletedSchemaPurge:
    def _fixture(self, deleted: bool, run_uuid: str | None = "run-1"):
        team = Team.objects.create(organization=Organization.objects.create(name="org"), name="t")
        source = ExternalDataSource.objects.create(
            team=team, source_id="s", connection_id="c", source_type="Stripe", status="Running"
        )
        schema = ExternalDataSchema.objects.create(team=team, source=source, name="customers", deleted=deleted)
        state = DuckgresSinkSchemaState.objects.create(
            team=team, schema_id=schema.id, state=DuckgresSinkSchemaState.State.BACKFILLING, backfill_run_uuid=run_uuid
        )
        return schema, state

    def test_purge_retires_run_and_drops_state_for_deleted_schema(self):
        _, state = self._fixture(deleted=True)
        conn = MagicMock()
        with patch.object(backfill_module, "retire_backfill_run") as retire:
            backfill_module._purge_deleted_schema_states(conn, None)
        retire.assert_called_once_with(conn, run_uuid="run-1")
        assert not DuckgresSinkSchemaState.objects.filter(id=state.id).exists()

    def test_purge_leaves_live_schemas_untouched(self):
        _, state = self._fixture(deleted=False)
        conn = MagicMock()
        with patch.object(backfill_module, "retire_backfill_run") as retire:
            backfill_module._purge_deleted_schema_states(conn, None)
        retire.assert_not_called()
        assert DuckgresSinkSchemaState.objects.filter(id=state.id).exists()

    def test_plan_one_skips_deleted_schema(self):
        _, state = self._fixture(deleted=True, run_uuid=None)
        with (
            patch.object(backfill_module, "resolve_snapshot_plan") as resolve,
            patch.object(backfill_module.psycopg, "connect") as connect,
        ):
            backfill_module._plan_one(state)
        resolve.assert_not_called()
        connect.assert_not_called()


class TestEnqueueLockTimeout:
    def test_lock_timeout_skips_replay_and_resets(self):
        conn = MagicMock()

        def execute(query, *args, **kwargs):
            if "pg_advisory_lock" in str(query):
                raise psycopg.errors.LockNotAvailable()
            return MagicMock()

        conn.execute.side_effect = execute
        assert enqueue_chunks(conn, MagicMock(), "run-x", []) == 0
        executed = [str(call.args[0]) for call in conn.execute.call_args_list]
        assert any("SET lock_timeout" in query for query in executed)
        assert any("RESET lock_timeout" in query for query in executed)
        assert not any("INSERT INTO" in query for query in executed)
