import io
import math
import time
import uuid
import socket
import importlib
import urllib.request
from collections.abc import Callable
from datetime import (
    UTC,
    datetime,
    time as dt_time,
    timedelta,
)

import pytest
from unittest.mock import AsyncMock, MagicMock

from django.core.management import call_command

import psycopg
from asgiref.sync import async_to_sync

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team

from products.warehouse_sources.backend.management.commands.report_warehouse_scheduler_shadow import (
    parse_schedule_fired_at,
)
from products.warehouse_sources.backend.models import ExternalDataJob, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.scheduling import runner as scheduler_runner
from products.warehouse_sources.backend.scheduling.runner import ShadowScheduler, ShadowSchedulerConfig
from products.warehouse_sources.backend.scheduling.shadow import (
    DECISION_SKIP_CDC_HALTED,
    DECISION_SKIP_OUT_OF_SCOPE,
    DECISION_SKIP_OVERLAP,
    DECISION_WOULD_FIRE,
    SYNC_EXTRACT_KIND,
    EvaluationResult,
    SchemaCadence,
    evaluate_due,
    fetch_in_scope_schema_page,
    latest_fire_at,
    next_due_after,
    schedule_offset,
    window_boundary,
)
from products.warehouse_sources_queue.backend.core.scheduler_state import (
    SCHEDULER_DECISION_TABLE,
    SCHEDULER_STATE_TABLE,
    DecisionRecord,
    SchedulerStateTable,
)
from products.warehouse_sources_queue.backend.sdk import DueSchedule, HealthState, start_health_server
from products.warehouse_sources_queue.backend.testing import ensure_scheduler_tables, get_test_database_url

# The product-structure lint reads a direct import of another product's logic
# as a facade leak; tests reference cross-product internals by module path
# instead (the cdc tests' patch targets set the precedent). Parity needs the
# real schedule builder, not a facade contract.
get_sync_schedule = importlib.import_module("products.data_warehouse.backend.logic.data_load.service").get_sync_schedule

FIXED_SCHEMA_IDS = [
    "0d3a4c1e-8f2b-4a6d-9c5e-1b7f3a9d2e4c",
    "7f6e5d4c-3b2a-4918-8776-655443322110",
    "c0ffee00-1234-4abc-8def-987654321000",
]

INTERVALS = [
    pytest.param(timedelta(minutes=5), id="5m"),
    pytest.param(timedelta(minutes=30), id="30m"),
    pytest.param(timedelta(hours=1), id="1h"),
    pytest.param(timedelta(hours=6), id="6h"),
    pytest.param(timedelta(hours=12), id="12h"),
    pytest.param(timedelta(days=1), id="24h"),
    pytest.param(timedelta(days=7), id="7d"),
]


@pytest.fixture
def organization():
    return create_organization("test org")


@pytest.fixture
def team(organization):
    return create_team(organization=organization)


def _unsaved_schema(schema_id: str, interval: timedelta, sync_time_of_day: dt_time | None) -> ExternalDataSchema:
    return ExternalDataSchema(
        id=uuid.UUID(schema_id),
        team_id=1,
        source_id=uuid.uuid4(),
        sync_frequency_interval=interval,
        sync_time_of_day=sync_time_of_day,
    )


class TestOffsetParity:
    @pytest.mark.parametrize("interval", INTERVALS)
    @pytest.mark.parametrize("schema_id", FIXED_SCHEMA_IDS)
    def test_jitter_offset_matches_get_sync_schedule(self, schema_id, interval):
        schema = _unsaved_schema(schema_id, interval, None)
        schedule = get_sync_schedule(schema)
        assert schedule.spec.intervals[0].offset == timedelta(seconds=schedule_offset(schema_id, interval, None))

    @pytest.mark.parametrize(
        "sync_time_of_day,interval,expected_offset",
        [
            pytest.param(dt_time(15, 30, 0), timedelta(days=1), timedelta(minutes=930), id="24h_direct"),
            pytest.param(dt_time(15, 30, 0), timedelta(hours=6), timedelta(minutes=210), id="6h_reduced_mod"),
            pytest.param(dt_time(15, 30, 45), timedelta(days=1), timedelta(minutes=930), id="seconds_dropped"),
        ],
    )
    def test_sync_time_offset_matches_get_sync_schedule(self, sync_time_of_day, interval, expected_offset):
        schema = _unsaved_schema(FIXED_SCHEMA_IDS[0], interval, sync_time_of_day)
        schedule = get_sync_schedule(schema)
        assert schedule.spec.intervals[0].offset == expected_offset
        assert timedelta(seconds=schedule_offset(FIXED_SCHEMA_IDS[0], interval, sync_time_of_day)) == expected_offset


class TestEpochMath:
    @pytest.mark.parametrize(
        "late_by",
        [pytest.param(0, id="on_time"), pytest.param(59, id="1m_late"), pytest.param(21599, id="just_under_interval")],
    )
    def test_late_ticks_do_not_drift(self, late_by):
        cadence = SchemaCadence(interval_seconds=21600, offset_seconds=12600)
        boundary_now = (1_756_598_400 // 21600) * 21600 + 12600

        fire = latest_fire_at(boundary_now + late_by, cadence)
        assert fire == boundary_now
        assert (fire - cadence.offset_seconds) % cadence.interval_seconds == 0
        assert window_boundary(fire, cadence) == fire - cadence.offset_seconds
        assert window_boundary(fire, cadence) % cadence.interval_seconds == 0

        next_fire = latest_fire_at(boundary_now + cadence.interval_seconds + late_by, cadence)
        assert next_fire - fire == cadence.interval_seconds

    @pytest.mark.parametrize(
        "now_offset",
        [pytest.param(0, id="at_boundary"), pytest.param(1, id="just_after"), pytest.param(21599, id="just_before")],
    )
    def test_next_due_after_never_returns_past_or_now(self, now_offset):
        cadence = SchemaCadence(interval_seconds=21600, offset_seconds=12600)
        now = (1_756_598_400 // 21600) * 21600 + 12600 + now_offset
        assert next_due_after(now, cadence) > now


def _create_source(team, **overrides) -> ExternalDataSource:
    defaults = {
        "team": team,
        "source_id": str(uuid.uuid4()),
        "connection_id": str(uuid.uuid4()),
        "status": "Running",
        "source_type": "Stripe",
        "access_method": ExternalDataSource.AccessMethod.WAREHOUSE,
    }
    return ExternalDataSource.objects.create(**{**defaults, **overrides})


def _create_schema(team, source, **overrides) -> ExternalDataSchema:
    defaults = {
        "team": team,
        "source": source,
        "name": "test_table",
        "should_sync": True,
        "sync_frequency_interval": timedelta(hours=6),
    }
    return ExternalDataSchema.objects.create(**{**defaults, **overrides})


@pytest.mark.django_db
class TestScopePredicate:
    @pytest.mark.parametrize(
        "source_overrides,schema_overrides,expected_in_scope",
        [
            pytest.param({}, {}, True, id="baseline_included"),
            pytest.param({}, {"should_sync": False}, False, id="sync_disabled"),
            pytest.param({}, {"sync_frequency_interval": None}, False, id="no_interval"),
            pytest.param({}, {"deleted": True}, False, id="schema_deleted"),
            pytest.param({"deleted": True}, {}, False, id="source_deleted"),
            pytest.param({"access_method": ExternalDataSource.AccessMethod.DIRECT}, {}, False, id="direct_source"),
            pytest.param({}, {"sync_type_config": {"cdc_broken": True}}, True, id="cdc_halted_stays_in_scope"),
        ],
    )
    def test_scope_predicate(self, team, source_overrides, schema_overrides, expected_in_scope):
        source = _create_source(team, **source_overrides)
        schema = _create_schema(team, source, **schema_overrides)

        in_scope_ids = {row.schema_id for row in fetch_in_scope_schema_page(None, 100)}
        assert (str(schema.id) in in_scope_ids) == expected_in_scope


def _due_row(schema_id: str, team_id: int, now_epoch: int) -> DueSchedule:
    cadence = SchemaCadence(interval_seconds=21600, offset_seconds=0)
    return DueSchedule(
        kind=SYNC_EXTRACT_KIND,
        schedule_key=schema_id,
        team_id=team_id,
        interval_seconds=cadence.interval_seconds,
        offset_seconds=cadence.offset_seconds,
        next_due_at=datetime.fromtimestamp(latest_fire_at(now_epoch, cadence), tz=UTC),
    )


@pytest.mark.django_db(transaction=True)
class TestEvaluateDue:
    @pytest.mark.parametrize(
        "job_status,sync_type_config,expected_decision",
        [
            pytest.param("Running", {}, DECISION_SKIP_OVERLAP, id="running_job_overlaps"),
            pytest.param("Completed", {}, DECISION_WOULD_FIRE, id="completed_job_fires"),
            pytest.param("Failed", {}, DECISION_WOULD_FIRE, id="failed_job_fires"),
            pytest.param("BillingLimitReached", {}, DECISION_WOULD_FIRE, id="billing_limited_job_fires"),
            pytest.param(None, {"cdc_broken": True}, DECISION_SKIP_CDC_HALTED, id="cdc_broken_skips"),
            pytest.param(None, {"cdc_extraction_paused": True}, DECISION_SKIP_CDC_HALTED, id="cdc_paused_skips"),
            pytest.param(None, {"cdc_broken": False}, DECISION_WOULD_FIRE, id="cdc_ok_fires"),
        ],
    )
    def test_skip_reasons(self, team, job_status, sync_type_config, expected_decision):
        source = _create_source(team)
        schema = _create_schema(team, source, sync_type_config=sync_type_config)
        now_epoch = int(time.time())
        if job_status is not None:
            job = ExternalDataJob.objects.create(team=team, pipeline=source, schema=schema, status=job_status)
            if expected_decision == DECISION_SKIP_OVERLAP:
                due_at = datetime.fromtimestamp(
                    latest_fire_at(now_epoch, SchemaCadence(interval_seconds=21600, offset_seconds=0)), tz=UTC
                )
                ExternalDataJob.objects.filter(pk=job.pk).update(created_at=due_at - timedelta(seconds=1))

        result = async_to_sync(evaluate_due)([_due_row(str(schema.id), team.pk, now_epoch)], now_epoch)

        assert len(result.records) == 1
        record = result.records[0]
        assert record.decision == expected_decision
        assert record.due_at == datetime.fromtimestamp(
            latest_fire_at(now_epoch, SchemaCadence(interval_seconds=21600, offset_seconds=0)), tz=UTC
        )
        assert result.missed_windows == 0

    def test_current_boundary_temporal_job_is_not_an_overlap(self, team):
        source = _create_source(team)
        schema = _create_schema(team, source)
        now_epoch = int(time.time())
        due_at = datetime.fromtimestamp(
            latest_fire_at(now_epoch, SchemaCadence(interval_seconds=21600, offset_seconds=0)), tz=UTC
        )
        job = ExternalDataJob.objects.create(team=team, pipeline=source, schema=schema, status="Running")
        ExternalDataJob.objects.filter(pk=job.pk).update(created_at=due_at)

        result = async_to_sync(evaluate_due)([_due_row(str(schema.id), team.pk, now_epoch)], now_epoch)

        assert [record.decision for record in result.records] == [DECISION_WOULD_FIRE]

    def test_unknown_schema_is_out_of_scope(self, team):
        now_epoch = int(time.time())
        result = async_to_sync(evaluate_due)([_due_row(str(uuid.uuid4()), team.pk, now_epoch)], now_epoch)
        assert [record.decision for record in result.records] == [DECISION_SKIP_OUT_OF_SCOPE]


@pytest.mark.django_db(transaction=True)
class TestShadowSchedulerTick:
    def _setup_due_states(self, team_id: int, schema_ids: list[str]) -> tuple[datetime, str]:
        db_url = get_test_database_url()
        due_at = (datetime.now(UTC) - timedelta(minutes=1)).replace(microsecond=0)
        with psycopg.Connection.connect(db_url, autocommit=True) as conn:
            ensure_scheduler_tables(conn)
            conn.execute(f"TRUNCATE {SCHEDULER_DECISION_TABLE}, {SCHEDULER_STATE_TABLE}")
            for schema_id in schema_ids:
                conn.execute(
                    f"""
                    INSERT INTO {SCHEDULER_STATE_TABLE}
                        (kind, schedule_key, team_id, interval_seconds, offset_seconds, next_due_at)
                    VALUES (%s, %s, %s, 3600, 0, %s)
                    """,
                    (SYNC_EXTRACT_KIND, schema_id, team_id, due_at),
                )
        return due_at, db_url

    def _setup_due_state(self, team_id: int) -> tuple[str, datetime, str]:
        schema_id = str(uuid.uuid4())
        due_at, db_url = self._setup_due_states(team_id, [schema_id])
        return schema_id, due_at, db_url

    def _setup_due_schemas(self, team, count: int) -> tuple[set[str], str]:
        source = _create_source(team)
        schema_ids = [str(_create_schema(team, source, name=f"table_{i}").id) for i in range(count)]
        _, db_url = self._setup_due_states(team.pk, schema_ids)
        return set(schema_ids), db_url

    def _decided_keys(self, db_url: str) -> set[str]:
        with psycopg.Connection.connect(db_url) as conn:
            rows = conn.execute(f"SELECT schedule_key FROM {SCHEDULER_DECISION_TABLE}").fetchall()
        return {row[0] for row in rows}

    def _overdue_keys(self, db_url: str) -> set[str]:
        with psycopg.Connection.connect(db_url) as conn:
            rows = conn.execute(
                f"SELECT schedule_key FROM {SCHEDULER_STATE_TABLE} WHERE next_due_at <= now()"
            ).fetchall()
        return {row[0] for row in rows}

    @pytest.mark.parametrize(
        "schema_count,claim_limit,expected_batches",
        [
            pytest.param(0, 2, 1, id="empty"),
            pytest.param(1, 2, 1, id="under_limit"),
            pytest.param(4, 2, 3, id="exact_multiple_needs_empty_batch"),
            pytest.param(5, 2, 3, id="backlog_over_limit"),
        ],
    )
    def test_tick_drains_backlog_and_heartbeats_per_batch(
        self, team, monkeypatch, schema_count, claim_limit, expected_batches
    ):
        schema_ids, db_url = self._setup_due_schemas(team, schema_count)
        monkeypatch.setattr(
            scheduler_runner.JobsTable, "try_acquire_sentinel_slot", AsyncMock(side_effect=[True, False])
        )
        due_per_tick = MagicMock()
        monkeypatch.setattr(scheduler_runner, "DUE_PER_TICK", due_per_tick)
        health_reporter = MagicMock()

        scheduler = ShadowScheduler(ShadowSchedulerConfig(database_url=db_url, claim_limit=claim_limit))
        async_to_sync(scheduler._tick)(health_reporter)

        assert self._decided_keys(db_url) == schema_ids
        assert self._overdue_keys(db_url) == set()
        due_per_tick.observe.assert_called_once_with(schema_count)
        assert health_reporter.call_count >= expected_batches

    def test_drain_budget_defers_remaining_backlog_to_next_tick(self, team, monkeypatch):
        schema_ids, db_url = self._setup_due_schemas(team, 3)
        monkeypatch.setattr(
            scheduler_runner.JobsTable,
            "try_acquire_sentinel_slot",
            AsyncMock(side_effect=[True, False, True, False]),
        )
        scheduler = ShadowScheduler(ShadowSchedulerConfig(database_url=db_url, claim_limit=2, drain_budget_seconds=0))

        async_to_sync(scheduler._tick)(lambda: None)
        first_tick_keys = self._decided_keys(db_url)
        assert len(first_tick_keys) == 2
        assert self._overdue_keys(db_url) == schema_ids - first_tick_keys

        async_to_sync(scheduler._tick)(lambda: None)
        assert self._decided_keys(db_url) == schema_ids
        assert self._overdue_keys(db_url) == set()

    def _record(self, schema_id: str, team_id: int, due_at: datetime) -> DecisionRecord:
        return DecisionRecord(
            team_id=team_id,
            kind=SYNC_EXTRACT_KIND,
            schedule_key=schema_id,
            window_boundary=due_at,
            due_at=due_at,
            decision=DECISION_WOULD_FIRE,
            interval_seconds=3600,
            late_seconds=60.0,
        )

    def test_failed_decision_write_rolls_back_state_advance(self, team, monkeypatch):
        schema_id, due_at, db_url = self._setup_due_state(team.pk)
        record = self._record(schema_id, team.pk, due_at)
        original_insert = SchedulerStateTable.insert_decisions

        async def insert_then_fail(conn, records):
            await original_insert(conn, records)
            raise RuntimeError("decision write failed")

        monkeypatch.setattr(
            scheduler_runner.JobsTable,
            "try_acquire_sentinel_slot",
            AsyncMock(side_effect=[True, False]),
        )
        monkeypatch.setattr(
            scheduler_runner,
            "evaluate_due",
            AsyncMock(return_value=EvaluationResult(records=(record,), missed_windows=0)),
        )
        monkeypatch.setattr(SchedulerStateTable, "insert_decisions", insert_then_fail)

        scheduler = ShadowScheduler(ShadowSchedulerConfig(database_url=db_url))
        with pytest.raises(RuntimeError, match="decision write failed"):
            async_to_sync(scheduler._tick)(lambda: None)

        with psycopg.Connection.connect(db_url) as conn:
            assert conn.execute(
                f"SELECT next_due_at FROM {SCHEDULER_STATE_TABLE} WHERE kind = %s AND schedule_key = %s",
                (SYNC_EXTRACT_KIND, schema_id),
            ).fetchone() == (due_at,)
            assert conn.execute(f"SELECT count(*) FROM {SCHEDULER_DECISION_TABLE}").fetchone() == (0,)

    def test_duplicate_decision_does_not_emit_outcome_metrics(self, team, monkeypatch):
        schema_id, due_at, db_url = self._setup_due_state(team.pk)
        record = self._record(schema_id, team.pk, due_at)
        with psycopg.Connection.connect(db_url, autocommit=True) as conn:
            conn.execute(
                f"""
                INSERT INTO {SCHEDULER_DECISION_TABLE}
                    (team_id, kind, schedule_key, window_boundary, due_at, decision, interval_seconds, late_seconds)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    record.team_id,
                    record.kind,
                    record.schedule_key,
                    record.window_boundary,
                    record.due_at,
                    record.decision,
                    record.interval_seconds,
                    record.late_seconds,
                ),
            )

        monkeypatch.setattr(
            scheduler_runner.JobsTable,
            "try_acquire_sentinel_slot",
            AsyncMock(side_effect=[True, False]),
        )
        monkeypatch.setattr(
            scheduler_runner,
            "evaluate_due",
            AsyncMock(return_value=EvaluationResult(records=(record,), missed_windows=0)),
        )
        would_fire = MagicMock()
        skips = MagicMock()
        lateness = MagicMock()
        duplicate_windows = MagicMock()
        monkeypatch.setattr(scheduler_runner, "WOULD_FIRE_TOTAL", would_fire)
        monkeypatch.setattr(scheduler_runner, "SKIPS_TOTAL", skips)
        monkeypatch.setattr(scheduler_runner, "FIRE_LATENESS_SECONDS", lateness)
        monkeypatch.setattr(scheduler_runner, "DUPLICATE_WINDOWS_TOTAL", duplicate_windows)

        scheduler = ShadowScheduler(ShadowSchedulerConfig(database_url=db_url))
        async_to_sync(scheduler._tick)(lambda: None)

        would_fire.inc.assert_not_called()
        skips.labels.assert_not_called()
        lateness.observe.assert_not_called()
        duplicate_windows.inc.assert_called_once_with(1)


@pytest.mark.django_db(transaction=True)
class TestShadowSchedulerRefresh:
    def _refresh(self, db_url: str, page_size: int, health_reporter: Callable[[], None] = lambda: None) -> None:
        async def run() -> None:
            scheduler = ShadowScheduler(ShadowSchedulerConfig(database_url=db_url, refresh_page_size=page_size))
            async with await psycopg.AsyncConnection.connect(db_url, autocommit=True) as conn:
                await scheduler._refresh(conn, health_reporter)

        async_to_sync(run)()

    def _state_keys(self, db_url: str) -> set[str]:
        with psycopg.Connection.connect(db_url) as conn:
            rows = conn.execute(
                f"SELECT schedule_key FROM {SCHEDULER_STATE_TABLE} WHERE kind = %s", (SYNC_EXTRACT_KIND,)
            ).fetchall()
        return {row[0] for row in rows}

    def _reset_state(self) -> str:
        db_url = get_test_database_url()
        with psycopg.Connection.connect(db_url, autocommit=True) as conn:
            ensure_scheduler_tables(conn)
            conn.execute(f"TRUNCATE {SCHEDULER_DECISION_TABLE}, {SCHEDULER_STATE_TABLE}")
        return db_url

    @pytest.mark.parametrize("page_size", [1, 2, 3, 100])
    @pytest.mark.parametrize("schema_count", [0, 1, 2, 5])
    def test_paged_refresh_upserts_every_in_scope_schema(self, team, monkeypatch, schema_count, page_size):
        db_url = self._reset_state()
        source = _create_source(team)
        schema_ids = {str(_create_schema(team, source, name=f"table_{i}").id) for i in range(schema_count)}
        _create_schema(team, source, name="out_of_scope", should_sync=False)
        in_scope_gauge = MagicMock()
        monkeypatch.setattr(scheduler_runner, "SCHEMAS_IN_SCOPE", in_scope_gauge)
        health_reporter = MagicMock()

        self._refresh(db_url, page_size, health_reporter)

        assert self._state_keys(db_url) == schema_ids
        in_scope_gauge.set.assert_called_once_with(schema_count)
        assert health_reporter.call_count >= math.ceil(schema_count / page_size)

    @pytest.mark.parametrize("page_size", [1, 2, 10])
    def test_paged_refresh_deletes_schemas_that_left_scope(self, team, page_size):
        db_url = self._reset_state()
        source = _create_source(team)
        schemas = [_create_schema(team, source, name=f"table_{i}") for i in range(5)]
        self._refresh(db_url, page_size)
        assert self._state_keys(db_url) == {str(schema.id) for schema in schemas}

        schemas[0].should_sync = False
        schemas[0].save()
        ExternalDataSchema.objects.filter(pk=schemas[4].pk).update(deleted=True)
        self._refresh(db_url, page_size)

        assert self._state_keys(db_url) == {str(schema.id) for schema in schemas[1:4]}


class TestSchedulerMetricsEndpoint:
    def test_metrics_endpoint_serves_scheduler_metrics(self):
        scheduler_runner.TICKS_TOTAL.labels(outcome="follower").inc()
        free_port = _free_port()
        start_health_server(port=free_port, health_state=HealthState(timeout_seconds=60))

        with urllib.request.urlopen(f"http://127.0.0.1:{free_port}/_metrics", timeout=5) as response:
            body = response.read().decode()

        assert "warehouse_pg_scheduler_ticks_total" in body


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.django_db
class TestShadowReport:
    @pytest.mark.parametrize(
        "fired_offset_minutes,due_offset_minutes,expected_matched,expected_temporal_only",
        [
            pytest.param(-10, 5, 1, 0, id="pre_window_job_matches"),
            pytest.param(-10, None, 0, 0, id="unmatched_pre_window_job"),
            pytest.param(10, None, 0, 1, id="unmatched_in_window_job"),
        ],
    )
    def test_report_counts_jobs_at_window_start(
        self, team, monkeypatch, fired_offset_minutes, due_offset_minutes, expected_matched, expected_temporal_only
    ):
        db_url = get_test_database_url()
        with psycopg.Connection.connect(db_url, autocommit=True) as conn:
            ensure_scheduler_tables(conn)
            conn.execute(f"TRUNCATE {SCHEDULER_DECISION_TABLE}")
        monkeypatch.setattr(
            "products.warehouse_sources.backend.management.commands.report_warehouse_scheduler_shadow"
            ".WAREHOUSE_SOURCES_DATABASE_URL",
            db_url,
        )

        source = _create_source(team)
        schema = _create_schema(team, source)
        since = (datetime.now(UTC) - timedelta(hours=2)).replace(microsecond=0)
        if due_offset_minutes is not None:
            due_at = since + timedelta(minutes=due_offset_minutes)
            with psycopg.Connection.connect(db_url, autocommit=True) as conn:
                conn.execute(
                    f"""
                    INSERT INTO {SCHEDULER_DECISION_TABLE}
                        (team_id, kind, schedule_key, window_boundary, due_at, decision, interval_seconds, late_seconds)
                    VALUES (%(team_id)s, %(kind)s, %(schedule_key)s, %(due_at)s, %(due_at)s, 'would_fire', 21600, 1.0)
                    """,
                    {"team_id": team.pk, "kind": SYNC_EXTRACT_KIND, "schedule_key": str(schema.id), "due_at": due_at},
                )

        fired_at = since + timedelta(minutes=fired_offset_minutes)
        ExternalDataJob.objects.create(
            team=team,
            pipeline=source,
            schema=schema,
            status="Running",
            workflow_id=f"{schema.id}-{fired_at.isoformat()}",
        )

        out = io.StringIO()
        err = io.StringIO()
        call_command(
            "report_warehouse_scheduler_shadow",
            "--since",
            since.isoformat(),
            "--team-id",
            str(team.pk),
            stdout=out,
            stderr=err,
        )

        output = out.getvalue()
        decision_count = int(due_offset_minutes is not None)
        assert f"matched: {expected_matched}" in output
        assert "shadow_only (shadow would fire, no job): 0" in output
        assert f"temporal_only (schedule-fired job, no decision): {expected_temporal_only}" in output
        stderr = err.getvalue().splitlines()
        assert "fetching decisions..." in stderr
        assert any(line.startswith(f"fetched {decision_count} decisions in ") for line in stderr)
        assert "fetching jobs..." in stderr
        assert any(line.startswith("fetched 1 jobs in ") for line in stderr)
        assert any(line.startswith("matching: done in ") for line in stderr)

    def test_report_matches_jobs_and_counts_adhoc(self, team, monkeypatch):
        db_url = get_test_database_url()
        with psycopg.Connection.connect(db_url, autocommit=True) as conn:
            ensure_scheduler_tables(conn)
            conn.execute(f"TRUNCATE {SCHEDULER_DECISION_TABLE}")
        monkeypatch.setattr(
            "products.warehouse_sources.backend.management.commands.report_warehouse_scheduler_shadow"
            ".WAREHOUSE_SOURCES_DATABASE_URL",
            db_url,
        )

        source = _create_source(team)
        matched_schema = _create_schema(team, source)
        adhoc_schema = _create_schema(team, source, name="other_table")

        due_at = (datetime.now(UTC) - timedelta(minutes=10)).replace(microsecond=0)
        with psycopg.Connection.connect(db_url, autocommit=True) as conn:
            conn.execute(
                f"""
                INSERT INTO {SCHEDULER_DECISION_TABLE}
                    (team_id, kind, schedule_key, window_boundary, due_at, decision, interval_seconds, late_seconds)
                VALUES (%(team_id)s, %(kind)s, %(schedule_key)s, %(due_at)s, %(due_at)s, 'would_fire', 21600, 1.0)
                """,
                {
                    "team_id": team.pk,
                    "kind": SYNC_EXTRACT_KIND,
                    "schedule_key": str(matched_schema.id),
                    "due_at": due_at,
                },
            )
            conn.execute(
                f"""
                INSERT INTO {SCHEDULER_DECISION_TABLE}
                    (team_id, kind, schedule_key, window_boundary, due_at, decision, interval_seconds, late_seconds)
                VALUES (%(team_id)s, 'other.kind', %(schedule_key)s, %(due_at)s, %(due_at)s, 'would_fire', 21600, 1.0)
                """,
                {"team_id": team.pk, "schedule_key": str(matched_schema.id), "due_at": due_at},
            )

        ExternalDataJob.objects.create(
            team=team,
            pipeline=source,
            schema=matched_schema,
            status="Running",
            workflow_id=f"{matched_schema.id}-{due_at.isoformat()}",
        )
        ExternalDataJob.objects.create(
            team=team, pipeline=source, schema=adhoc_schema, status="Running", workflow_id=None
        )

        out = io.StringIO()
        call_command("report_warehouse_scheduler_shadow", "--team-id", str(team.pk), stdout=out)
        output = out.getvalue()

        assert "matched: 1" in output
        assert "shadow_only (shadow would fire, no job): 0" in output
        assert "temporal_only (schedule-fired job, no decision): 0" in output
        assert "adhoc (manual/backfill runs, excluded): 1" in output

    def test_adhoc_job_does_not_consume_nearby_decision(self, team, monkeypatch):
        db_url = get_test_database_url()
        with psycopg.Connection.connect(db_url, autocommit=True) as conn:
            ensure_scheduler_tables(conn)
            conn.execute(f"TRUNCATE {SCHEDULER_DECISION_TABLE}")
        monkeypatch.setattr(
            "products.warehouse_sources.backend.management.commands.report_warehouse_scheduler_shadow"
            ".WAREHOUSE_SOURCES_DATABASE_URL",
            db_url,
        )

        source = _create_source(team)
        schema = _create_schema(team, source)
        due_at = (datetime.now(UTC) - timedelta(minutes=10)).replace(microsecond=0)
        with psycopg.Connection.connect(db_url, autocommit=True) as conn:
            conn.execute(
                f"""
                INSERT INTO {SCHEDULER_DECISION_TABLE}
                    (team_id, kind, schedule_key, window_boundary, due_at, decision, interval_seconds, late_seconds)
                VALUES (%(team_id)s, %(kind)s, %(schedule_key)s, %(due_at)s, %(due_at)s, 'would_fire', 21600, 1.0)
                """,
                {"team_id": team.pk, "kind": SYNC_EXTRACT_KIND, "schedule_key": str(schema.id), "due_at": due_at},
            )
        ExternalDataJob.objects.create(team=team, pipeline=source, schema=schema, status="Running", workflow_id=None)

        out = io.StringIO()
        call_command("report_warehouse_scheduler_shadow", "--team-id", str(team.pk), stdout=out)
        output = out.getvalue()

        assert "matched: 0" in output
        assert "shadow_only (shadow would fire, no job): 1" in output
        assert "temporal_only (schedule-fired job, no decision): 0" in output
        assert "adhoc (manual/backfill runs, excluded): 1" in output

    @pytest.mark.parametrize(
        "workflow_id,expected",
        [
            pytest.param(None, None, id="no_workflow_id"),
            pytest.param("manual-run", None, id="no_schema_prefix"),
            pytest.param("SCHEMA-not-a-timestamp", None, id="unparseable_suffix"),
            pytest.param("SCHEMA-2026-08-31T12:00:00+00:00", datetime(2026, 8, 31, 12, 0, tzinfo=UTC), id="iso_suffix"),
            pytest.param(
                "SCHEMA-2026-08-31T12:00:00", datetime(2026, 8, 31, 12, 0, tzinfo=UTC), id="naive_iso_becomes_utc"
            ),
        ],
    )
    def test_parse_schedule_fired_at(self, workflow_id, expected):
        workflow_id = workflow_id.replace("SCHEMA", "abc123") if workflow_id else workflow_id
        assert parse_schedule_fired_at("abc123", workflow_id) == expected
