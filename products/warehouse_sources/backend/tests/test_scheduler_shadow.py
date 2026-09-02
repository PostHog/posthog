import io
import time
import uuid
from datetime import (
    UTC,
    datetime,
    time as dt_time,
    timedelta,
)

import pytest

from django.core.management import call_command

import psycopg
from asgiref.sync import async_to_sync

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team

from products.data_warehouse.backend.logic.data_load.service import get_sync_schedule
from products.warehouse_sources.backend.management.commands.report_warehouse_scheduler_shadow import (
    parse_schedule_fired_at,
)
from products.warehouse_sources.backend.models import ExternalDataJob, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.scheduling.shadow import (
    DECISION_SKIP_CDC_HALTED,
    DECISION_SKIP_OUT_OF_SCOPE,
    DECISION_SKIP_OVERLAP,
    DECISION_WOULD_FIRE,
    SchemaCadence,
    evaluate_due,
    fetch_in_scope_schemas,
    latest_fire_at,
    next_due_after,
    schedule_offset,
    window_boundary,
)
from products.warehouse_sources_queue.backend.core.scheduler_state import SCHEDULER_DECISION_TABLE
from products.warehouse_sources_queue.backend.sdk import DueSchedule
from products.warehouse_sources_queue.backend.testing import ensure_scheduler_tables, get_test_database_url

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

        in_scope_ids = {row[0] for row in fetch_in_scope_schemas()}
        assert (str(schema.id) in in_scope_ids) == expected_in_scope


def _due_row(schema_id: str, team_id: int, now_epoch: int) -> DueSchedule:
    cadence = SchemaCadence(interval_seconds=21600, offset_seconds=0)
    return DueSchedule(
        schema_id=schema_id,
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
        if job_status is not None:
            ExternalDataJob.objects.create(team=team, pipeline=source, schema=schema, status=job_status)

        now_epoch = int(time.time())
        result = async_to_sync(evaluate_due)([_due_row(str(schema.id), team.pk, now_epoch)], now_epoch)

        assert len(result.records) == 1
        record = result.records[0]
        assert record.decision == expected_decision
        assert record.due_at == datetime.fromtimestamp(
            latest_fire_at(now_epoch, SchemaCadence(interval_seconds=21600, offset_seconds=0)), tz=UTC
        )
        assert result.missed_windows == 0

    def test_unknown_schema_is_out_of_scope(self, team):
        now_epoch = int(time.time())
        result = async_to_sync(evaluate_due)([_due_row(str(uuid.uuid4()), team.pk, now_epoch)], now_epoch)
        assert [record.decision for record in result.records] == [DECISION_SKIP_OUT_OF_SCOPE]


@pytest.mark.django_db
class TestShadowReport:
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
                    (team_id, schema_id, window_boundary, due_at, decision, interval_seconds, late_seconds)
                VALUES (%(team_id)s, %(schema_id)s, %(due_at)s, %(due_at)s, 'would_fire', 21600, 1.0)
                """,
                {"team_id": team.pk, "schema_id": str(matched_schema.id), "due_at": due_at},
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
