import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import DatabaseError, OperationalError, connection, transaction
from django.db.models import Model
from django.test import SimpleTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from dateutil import parser
from parameterized import parameterized

from posthog.models.signals import model_activity_signal
from posthog.models.team import Team

from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    REPARTITION_HOLD_MAX_AGE,
    ExternalDataSchema,
    apply_incremental_lookback,
    complete_schema_run,
    mark_initial_sync_complete,
    process_incremental_value,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.oom_event import ExternalDataSchemaOOMEvent
from products.warehouse_sources.backend.models.ssh_tunnel import SSHTunnel
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.models.util import (
    CLICKHOUSE_HOGQL_MAPPING,
    clean_type,
    clickhouse_column_to_dwh_column,
)
from products.warehouse_sources.backend.types import IncrementalFieldType


@pytest.mark.parametrize(
    "model,expected_db_table",
    [
        (DataWarehouseCredential, "posthog_datawarehousecredential"),
        (DataWarehouseTable, "posthog_datawarehousetable"),
        (ExternalDataJob, "posthog_externaldatajob"),
        (ExternalDataSchema, "posthog_externaldataschema"),
        (ExternalDataSource, "posthog_externaldatasource"),
    ],
)
def test_db_table_preserved_across_split(model: type[Model], expected_db_table: str) -> None:
    """The split moved these models to a new Django app via SeparateDatabaseAndState;
    the `posthog_*` table names must remain unchanged or prod reads break silently."""
    assert model._meta.db_table == expected_db_table


@pytest.mark.parametrize(
    "s3_folder_name,sync_type_config,expected",
    [
        ("legacy_users", {"dwh_storage_key": "ignored"}, "legacy_users"),
        (None, {"dwh_storage_key": "legacy_users"}, "legacy_users"),
        ("", {"dwh_storage_key": "legacy_users"}, "legacy_users"),
        (None, {"dwh_storage_key": ""}, None),
        (None, {"dwh_storage_key": 123}, None),
        (None, {}, None),
        (None, None, None),
    ],
)
def test_resolved_s3_folder_name(
    s3_folder_name: str | None, sync_type_config: dict | None, expected: str | None
) -> None:
    """Column wins; rows written by pre-column workers fall back to the JSON key; junk yields None
    so callers fall back to the schema name."""
    schema = ExternalDataSchema(s3_folder_name=s3_folder_name, sync_type_config=sync_type_config)
    assert schema.resolved_s3_folder_name == expected


class TestExternalDataSchemaSave(BaseTest):
    def _source(self) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type="Postgres",
        )

    def _create(self, name: str, **kwargs) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(team_id=self.team.pk, source=self._source(), name=name, **kwargs)

    def test_save_populates_s3_folder_name_from_name(self) -> None:
        # The folder is the normalized name — never NULL for a new row.
        schema = self._create("My Table")
        assert schema.s3_folder_name == "my_table"
        schema.refresh_from_db()
        assert schema.s3_folder_name == "my_table"

    def test_save_uses_legacy_key_when_present(self) -> None:
        schema = self._create("public.users", sync_type_config={"dwh_storage_key": "users"})
        assert schema.s3_folder_name == "users"

    def test_save_does_not_overwrite_existing_folder(self) -> None:
        schema = self._create("My Table", s3_folder_name="pinned")
        assert schema.s3_folder_name == "pinned"

    def test_partial_update_backfills_null_folder(self) -> None:
        # A pre-existing NULL row heals on its next save, even a partial one.
        schema = self._create("orders")
        ExternalDataSchema.objects.filter(pk=schema.pk).update(s3_folder_name=None)
        schema.refresh_from_db()
        assert schema.s3_folder_name is None

        schema.status = "Completed"
        schema.save(update_fields=["status", "updated_at"])
        schema.refresh_from_db()
        assert schema.s3_folder_name == "orders"


class TestExternalDataSchemaActivityLogging(BaseTest):
    """Internal pipeline-driven bookkeeping saves must bypass ModelActivityMixin so they neither
    emit a (low-value) activity signal nor perform the extra `_get_before_update` SELECT — that
    read can raise OperationalError when the transaction pooler drops the connection mid-sync."""

    def setUp(self) -> None:
        super().setUp()
        self.signal_received = False
        self.source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type="Postgres",
        )

    def _signal_handler(self, sender, **kwargs) -> None:
        self.signal_received = True

    def _create(self, **kwargs) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(team_id=self.team.pk, source=self.source, name="users", **kwargs)

    def test_normal_update_triggers_activity_signal(self) -> None:
        schema = self._create()
        model_activity_signal.connect(self._signal_handler, sender=ExternalDataSchema)
        try:
            schema.should_sync = False
            schema.save()
            assert self.signal_received
        finally:
            model_activity_signal.disconnect(self._signal_handler, sender=ExternalDataSchema)

    def test_skip_activity_log_bypasses_before_update_read(self) -> None:
        schema = self._create()
        with patch.object(ExternalDataSchema, "_get_before_update") as before_update:
            schema.status = "Running"
            schema.save(skip_activity_log=True)
            assert not before_update.called

    def test_default_save_performs_before_update_read(self) -> None:
        schema = self._create()
        # return_value=None matches the "no prior row" path the activity handler already tolerates.
        with patch.object(ExternalDataSchema, "_get_before_update", return_value=None) as before_update:
            schema.status = "Running"
            schema.save()
            assert before_update.called

    def test_reset_pipeline_save_skips_activity_log(self) -> None:
        schema = self._create(
            sync_type=ExternalDataSchema.SyncType.XMIN,
            sync_type_config={"xmin_last_value": 100, "xmin_ceiling": 4294967396, "xmin_num_wraparound": 1},
            initial_sync_complete=True,
        )
        model_activity_signal.connect(self._signal_handler, sender=ExternalDataSchema)
        try:
            with patch.object(ExternalDataSchema, "_get_before_update") as before_update:
                schema.update_sync_type_config_for_reset_pipeline()
                assert not before_update.called
            assert not self.signal_received
        finally:
            model_activity_signal.disconnect(self._signal_handler, sender=ExternalDataSchema)
        schema.refresh_from_db()
        assert schema.initial_sync_complete is False
        assert "xmin_last_value" not in schema.sync_type_config

    def test_update_xmin_state_save_skips_activity_log(self) -> None:
        schema = self._create(sync_type=ExternalDataSchema.SyncType.XMIN, sync_type_config={})
        model_activity_signal.connect(self._signal_handler, sender=ExternalDataSchema)
        try:
            schema.update_xmin_state(ceiling_xid=100, ceiling_xid8=4294967396, num_wraparound=1)
            assert not self.signal_received
        finally:
            model_activity_signal.disconnect(self._signal_handler, sender=ExternalDataSchema)
        schema.refresh_from_db()
        assert schema.xmin_last_value == 100

    def test_update_incremental_field_value_save_skips_activity_log(self) -> None:
        schema = self._create(
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field_type": IncrementalFieldType.Integer},
        )
        model_activity_signal.connect(self._signal_handler, sender=ExternalDataSchema)
        try:
            schema.update_incremental_field_value(42)
            assert not self.signal_received
        finally:
            model_activity_signal.disconnect(self._signal_handler, sender=ExternalDataSchema)
        schema.refresh_from_db()
        assert schema.incremental_field_last_value == 42

    def test_set_partitioning_enabled_save_skips_activity_log(self) -> None:
        schema = self._create(sync_type_config={})
        model_activity_signal.connect(self._signal_handler, sender=ExternalDataSchema)
        try:
            schema.set_partitioning_enabled(
                partitioning_keys=["id"],
                partition_count=10,
                partition_size=None,
                partition_mode="md5",
                partition_format=None,
            )
            assert not self.signal_received
        finally:
            model_activity_signal.disconnect(self._signal_handler, sender=ExternalDataSchema)
        schema.refresh_from_db()
        assert schema.sync_type_config["partitioning_enabled"] is True

    def test_stage_incremental_field_value_save_skips_activity_log(self) -> None:
        schema = self._create(
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field_type": IncrementalFieldType.Integer},
        )
        model_activity_signal.connect(self._signal_handler, sender=ExternalDataSchema)
        try:
            schema.stage_incremental_field_value("run-1", 42)
            assert not self.signal_received
        finally:
            model_activity_signal.disconnect(self._signal_handler, sender=ExternalDataSchema)
        schema.refresh_from_db()
        assert schema.sync_type_config["incremental_staged"]["last_value"] == 42

    def test_promote_staged_incremental_values_save_skips_activity_log(self) -> None:
        schema = self._create(
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={
                "incremental_field_type": IncrementalFieldType.Integer,
                "incremental_staged": {"run_uuid": "run-1", "last_value": 42},
            },
        )
        model_activity_signal.connect(self._signal_handler, sender=ExternalDataSchema)
        try:
            assert schema.promote_staged_incremental_values("run-1")
            assert not self.signal_received
        finally:
            model_activity_signal.disconnect(self._signal_handler, sender=ExternalDataSchema)
        schema.refresh_from_db()
        assert schema.sync_type_config["incremental_field_last_value"] == 42

    def test_bookkeeping_save_raises_instead_of_resurrecting_deleted_row(self) -> None:
        # Source (and its schema, via CASCADE) deleted concurrently with a sync still holding a
        # stale in-memory schema reference. Without force_update, Django's UUID-pk insert fallback
        # would silently recreate the row here and hit an FK violation on source_id instead.
        schema = self._create(
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field_type": IncrementalFieldType.Integer},
        )
        schema_id = schema.pk
        # A queryset delete (unlike self.source.delete()) doesn't null out this process's cached
        # `schema.source`, matching production where the delete happens on another connection.
        ExternalDataSource.objects.filter(pk=self.source.pk).delete()

        # Postgres aborts the whole transaction on an unhandled DatabaseError; a savepoint keeps
        # the failure scoped so the existence check below can still run.
        with self.assertRaises(DatabaseError), transaction.atomic():
            schema.update_incremental_field_value(42)

        assert not ExternalDataSchema.objects.filter(pk=schema_id).exists()


class TestSaveSyncTypeConfigRetriesOnConnectionDrop(BaseTest):
    """A pgbouncer `query_wait_timeout` (surfaced as `OperationalError`) on this per-batch
    bookkeeping write used to propagate straight past `record_partition_measurement` and get
    swallowed by the caller's broad except, silently losing the write for that run."""

    def setUp(self) -> None:
        super().setUp()
        self.source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type="Postgres",
        )

    def _create(self, **kwargs) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(team_id=self.team.pk, source=self.source, name="users", **kwargs)

    def test_retries_once_on_operational_error_then_succeeds(self) -> None:
        schema = self._create()
        real_save = ExternalDataSchema.save
        calls = 0

        def flaky_save(self: ExternalDataSchema, *args: Any, **kwargs: Any) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OperationalError("query_wait_timeout")
            real_save(self, *args, **kwargs)

        with patch.object(ExternalDataSchema, "save", flaky_save):
            schema.record_partition_measurement(123)

        assert calls == 2
        schema.refresh_from_db()
        assert schema.sync_type_config["max_partition_bytes"] == 123

    def test_second_consecutive_operational_error_propagates(self) -> None:
        schema = self._create()
        with patch.object(ExternalDataSchema, "save", side_effect=OperationalError("query_wait_timeout")):
            with self.assertRaises(OperationalError):
                schema.record_partition_measurement(123)


class TestExternalDataSchemaOOMEvent(BaseTest):
    def _source(self, team_id: int | None = None) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team_id=team_id if team_id is not None else self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type="Postgres",
        )

    def _schema(self, name: str, team_id: int | None = None) -> ExternalDataSchema:
        team_id = team_id if team_id is not None else self.team.pk
        return ExternalDataSchema.objects.create(team_id=team_id, source=self._source(team_id), name=name)

    def _other_team(self) -> Team:
        return Team.objects.create(organization=self.organization)

    def _oom(
        self,
        schema: ExternalDataSchema,
        *,
        age_days: float = 0,
        run_id: str | None = None,
        self_phase: str | None = None,
        # Fresh by default: the recorder snapshots the age from the same report as the rest of the
        # evidence, so evidence-carrying rows always have one. Tests override it to model staleness.
        self_report_age_at_death_seconds: float | None = 1.0,
        self_peak_buffer_bytes: int | None = None,
        co_tenant_correlated_max_peak_buffer_bytes: int | None = None,
    ) -> ExternalDataSchemaOOMEvent:
        event = ExternalDataSchemaOOMEvent.objects.for_team(schema.team_id).create(
            team_id=schema.team_id,
            schema=schema,
            run_id=run_id,
            self_phase=self_phase,
            self_report_age_at_death_seconds=self_report_age_at_death_seconds,
            self_peak_buffer_bytes=self_peak_buffer_bytes,
            co_tenant_correlated_max_peak_buffer_bytes=co_tenant_correlated_max_peak_buffer_bytes,
        )
        if age_days:
            # created_at is auto_now_add, so backdate via an update to place the row outside the window.
            ExternalDataSchemaOOMEvent.objects.unscoped().filter(pk=event.pk).update(
                created_at=timezone.now() - timedelta(days=age_days)
            )
        return event

    def test_recent_count_windows_and_scopes_to_schema(self) -> None:
        # A miscounted window or a dropped schema filter would force-repartition a healthy table
        # (or never fire): recent_count must count only this schema's occurrences inside the window.
        schema_a = self._schema("orders")
        schema_b = self._schema("events")
        self._oom(schema_a)
        self._oom(schema_a)
        self._oom(schema_a, age_days=10)  # outside a 7-day window
        self._oom(schema_b)  # different schema

        assert ExternalDataSchemaOOMEvent.recent_count(schema_a, days=7) == 2
        assert ExternalDataSchemaOOMEvent.recent_count(schema_a, days=30) == 3
        assert ExternalDataSchemaOOMEvent.recent_count(schema_b, days=7) == 1

    def test_recent_count_ignores_ooms_before_last_repartition(self) -> None:
        # A repartition fixes the OOMs that preceded it. Without this floor, those OOMs keep counting
        # and re-trigger a repartition on the same healthy table every cooldown until they age out.
        schema = self._schema("orders")
        self._oom(schema, age_days=2)
        self._oom(schema, age_days=2)
        self._oom(schema, age_days=2)
        schema.sync_type_config = {
            **(schema.sync_type_config or {}),
            "last_repartition_at": (timezone.now() - timedelta(days=1)).isoformat(),
        }
        schema.save()

        # All three OOMs predate the repartition, so none count toward re-triggering it.
        assert ExternalDataSchemaOOMEvent.recent_count(schema, days=7) == 0

        # An OOM recorded after the repartition still counts: the rewrite did not fix it, so this is a
        # real escalation the controller should act on.
        self._oom(schema)
        assert ExternalDataSchemaOOMEvent.recent_count(schema, days=7) == 1

    def test_recent_count_counts_every_retry_attempt(self) -> None:
        # Retries of one job are separate attempts at the same merge, each rescheduled onto whichever
        # worker picks it up. A job that OOMs attempt after attempt is a table failing deterministically,
        # so collapsing those into one occurrence would discard the clearest evidence this log carries.
        schema = self._schema("orders")
        for _ in range(5):
            self._oom(schema, run_id="run-1")

        assert ExternalDataSchemaOOMEvent.recent_count(schema, days=7) == 5

    @parameterized.expand(
        [
            # A death self-reported mid-extract (or in the consumer's pre-merge load, or after
            # finishing) is not a merge memory problem, so a finer partition layout cannot fix it.
            # Counting these is how tables that OOM on big fetches get wrongly repartitioned.
            ("extract_phase_does_not_count", {"self_phase": "extract"}, 0),
            ("load_phase_does_not_count", {"self_phase": "load"}, 0),
            ("finished_phase_does_not_count", {"self_phase": "finished"}, 0),
            ("merge_phase_counts", {"self_phase": "merge"}, 1),
            # No workload report (rollout gap, expired key, Redis down) must fail open, or a partial
            # rollout would silently switch the trigger off.
            ("unknown_phase_counts", {}, 1),
            # A co-tenant that self-reported a strictly larger working set is the likelier culprit for
            # a pod kill; counting the victim would repartition the wrong table.
            (
                "larger_co_tenant_exonerates",
                {
                    "self_phase": "merge",
                    "self_peak_buffer_bytes": 1_000,
                    "co_tenant_correlated_max_peak_buffer_bytes": 900_000,
                },
                0,
            ),
            (
                "smaller_co_tenant_does_not_exonerate",
                {
                    "self_phase": "merge",
                    "self_peak_buffer_bytes": 900_000,
                    "co_tenant_correlated_max_peak_buffer_bytes": 1_000,
                },
                1,
            ),
            # Unknown on either side never exonerates: blame requires evidence, absence of it does not.
            (
                "unknown_own_size_still_counts",
                {"self_phase": "merge", "co_tenant_correlated_max_peak_buffer_bytes": 900_000},
                1,
            ),
            # Reports are periodic, so a snapshot flushed long before the death describes an earlier
            # phase of the run: a merge that OOMs within one report interval of leaving extract still
            # shows "extract" in Redis. Stale or unknown-age evidence must not exonerate.
            (
                "stale_extract_phase_still_counts",
                {"self_phase": "extract", "self_report_age_at_death_seconds": 999.0},
                1,
            ),
            (
                "unknown_age_extract_phase_still_counts",
                {"self_phase": "extract", "self_report_age_at_death_seconds": None},
                1,
            ),
            (
                "stale_larger_co_tenant_still_counts",
                {
                    "self_phase": "merge",
                    "self_report_age_at_death_seconds": 999.0,
                    "self_peak_buffer_bytes": 1_000,
                    "co_tenant_correlated_max_peak_buffer_bytes": 900_000,
                },
                1,
            ),
        ]
    )
    def test_recent_count_applies_workload_evidence_rules(self, _name: str, evidence: dict, expected: int) -> None:
        schema = self._schema("orders")
        self._oom(schema, **evidence)

        assert ExternalDataSchemaOOMEvent.recent_count(schema, days=7) == expected

    @override_settings(DATA_WAREHOUSE_OOM_INFRA_BURST_MIN_SCHEMAS=3, DATA_WAREHOUSE_OOM_INFRA_BURST_MIN_TEAMS=3)
    def test_recent_count_ignores_occurrences_inside_a_fleet_wide_burst(self) -> None:
        # A deploy or node drain kills workers fleet-wide and every syncing schema records an
        # occurrence. Counting those is what repartitioned healthy tables for reasons that had
        # nothing to do with their partitions; a burst is judged from the rows themselves.
        schema = self._schema("orders")
        self._oom(schema, self_phase="merge")
        for name in ("events", "persons"):
            self._oom(self._schema(name, team_id=self._other_team().pk))

        assert ExternalDataSchemaOOMEvent.recent_count(schema, days=7) == 0

    @override_settings(DATA_WAREHOUSE_OOM_INFRA_BURST_MIN_SCHEMAS=3, DATA_WAREHOUSE_OOM_INFRA_BURST_MIN_TEAMS=3)
    def test_recent_count_keeps_occurrences_when_a_burst_spans_only_one_tenant(self) -> None:
        # One tenant's source outage kills all of that tenant's schemas at once — many schemas, one
        # team. That is the tenant's own problem, not infrastructure: classifying it as a burst would
        # let one tenant's failures suppress another tenant's remediation, and (without this floor)
        # its own.
        schema = self._schema("orders")
        self._oom(schema, self_phase="merge")
        for name in ("events", "persons", "invoices"):
            self._oom(self._schema(name))

        assert ExternalDataSchemaOOMEvent.recent_count(schema, days=7) == 1

    def test_recent_count_screens_bursts_with_one_aggregate_on_a_quiet_fleet(self) -> None:
        # The burst rule must not cost one aggregate per row: a schema can carry dozens of
        # occurrences, and this runs on every detection pass. One bucketed aggregate over the whole
        # window screens them all; on a quiet fleet no bucket crosses the thresholds, so everything
        # counts.
        schema = self._schema("orders")
        for _ in range(6):
            self._oom(schema, self_phase="merge")
        self._oom(schema, self_phase="merge", age_days=5)  # days apart must change nothing

        # Bounded, not exact: the team-scoped manager adds constant overhead we don't want to pin.
        with CaptureQueriesContext(connection) as queries:
            assert ExternalDataSchemaOOMEvent.recent_count(schema, days=7) == 7
        assert len(queries) <= 4, [q["sql"][:120] for q in queries.captured_queries]

    @override_settings(DATA_WAREHOUSE_OOM_INFRA_BURST_MIN_SCHEMAS=1, DATA_WAREHOUSE_OOM_INFRA_BURST_MIN_TEAMS=1)
    def test_recent_count_burst_screening_work_does_not_grow_with_retained_history(self) -> None:
        # The shape an adversarially (or chronically) failing schema can induce: many occurrences
        # spaced just under the window across days. Screening must stay a constant number of queries
        # — one bucketed aggregate for the whole window — never a query per occurrence.
        schema = self._schema("orders")
        for i in range(40):
            self._oom(schema, self_phase="merge", age_days=(40 - i) * 25 / (60 * 24))

        with CaptureQueriesContext(connection) as queries:
            # Thresholds of 1/1 make every occurrence its own crossing bucket, so all are excluded —
            # the point here is the query count, not the (absurd) threshold configuration.
            assert ExternalDataSchemaOOMEvent.recent_count(schema, days=7) == 0
        assert len(queries) <= 4, [q["sql"][:120] for q in queries.captured_queries]

    @override_settings(DATA_WAREHOUSE_OOM_INFRA_BURST_MIN_SCHEMAS=10)
    def test_recent_count_keeps_occurrences_below_the_burst_threshold(self) -> None:
        # The mirror case: a handful of schemas failing in one window is normal operation, and
        # discarding those would leave the trigger unable to fire at all.
        schema = self._schema("orders")
        self._oom(schema, self_phase="merge")
        for name in ("events", "persons"):
            self._oom(self._schema(name))

        assert ExternalDataSchemaOOMEvent.recent_count(schema, days=7) == 1


class TestUpdateSyncTypeConfigKeys(BaseTest):
    """The locked-merge helper that keeps the CDC extract activity and concurrent API PATCHes from
    clobbering each other's sync_type_config keys."""

    def setUp(self) -> None:
        super().setUp()
        self.source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type="Postgres",
        )

    def _create(self, sync_type_config: dict) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(
            team_id=self.team.pk, source=self.source, name="users", sync_type_config=sync_type_config
        )

    def test_updates_merge_and_preserve_unrelated_keys(self) -> None:
        schema = self._create({"cdc_mode": "streaming", "cdc_last_log_position": "0/100"})
        result = update_sync_type_config_keys(schema.id, self.team.pk, updates={"cdc_last_log_position": "0/200"})
        assert result == {"cdc_mode": "streaming", "cdc_last_log_position": "0/200"}
        schema.refresh_from_db()
        assert schema.sync_type_config == {"cdc_mode": "streaming", "cdc_last_log_position": "0/200"}

    def test_removes_pop_keys(self) -> None:
        schema = self._create(
            {"cdc_mode": "snapshot", "cdc_last_log_position": "0/100", "cdc_deferred_runs": [{"x": 1}]}
        )
        result = update_sync_type_config_keys(
            schema.id,
            self.team.pk,
            updates={"cdc_mode": "snapshot"},
            removes=["cdc_last_log_position", "cdc_deferred_runs"],
        )
        assert result == {"cdc_mode": "snapshot"}
        schema.refresh_from_db()
        assert schema.sync_type_config == {"cdc_mode": "snapshot"}

    def test_remove_of_absent_key_is_noop(self) -> None:
        schema = self._create({"cdc_mode": "streaming"})
        update_sync_type_config_keys(schema.id, self.team.pk, removes=["not_there"])
        schema.refresh_from_db()
        assert schema.sync_type_config == {"cdc_mode": "streaming"}

    def test_mutate_appends_inside_critical_section(self) -> None:
        schema = self._create({"cdc_deferred_runs": [{"run_uuid": "a", "batch_results": []}]})

        def _mutate(config: dict) -> None:
            for entry in config["cdc_deferred_runs"]:
                if entry["run_uuid"] == "a":
                    entry["batch_results"].append({"s3_path": "s3://x"})

        update_sync_type_config_keys(schema.id, self.team.pk, mutate=_mutate)
        schema.refresh_from_db()
        assert schema.sync_type_config["cdc_deferred_runs"][0]["batch_results"] == [{"s3_path": "s3://x"}]

    def test_apply_order_is_updates_removes_mutate(self) -> None:
        schema = self._create({"a": 1})

        def _mutate(config: dict) -> None:
            config["seen"] = sorted(config.keys())

        result = update_sync_type_config_keys(schema.id, self.team.pk, updates={"b": 2}, removes=["a"], mutate=_mutate)
        assert "a" not in result
        assert result["seen"] == ["b"]

    def test_wrong_team_id_does_not_match(self) -> None:
        schema = self._create({"cdc_mode": "streaming"})
        with self.assertRaises(ExternalDataSchema.DoesNotExist):
            update_sync_type_config_keys(schema.id, self.team.pk + 12345, updates={"cdc_mode": "snapshot"})

    def test_skips_activity_log(self) -> None:
        schema = self._create({"cdc_mode": "streaming"})
        received: list = []

        def _handler(sender, **kwargs) -> None:
            received.append(kwargs)

        model_activity_signal.connect(_handler, sender=ExternalDataSchema, weak=False)
        try:
            with patch.object(ExternalDataSchema, "_get_before_update") as before_update:
                update_sync_type_config_keys(schema.id, self.team.pk, updates={"cdc_last_log_position": "0/5"})
                assert not before_update.called
            assert received == []
        finally:
            model_activity_signal.disconnect(_handler, sender=ExternalDataSchema)

    def test_interleaved_writes_do_not_clobber(self) -> None:
        # Two activity-style position writes with an API-style cdc_table_mode write in between —
        # every key survives because each call re-reads the row before merging.
        schema = self._create({"cdc_mode": "streaming", "cdc_table_mode": "consolidated"})
        update_sync_type_config_keys(schema.id, self.team.pk, updates={"cdc_last_log_position": "0/100"})
        update_sync_type_config_keys(schema.id, self.team.pk, updates={"cdc_table_mode": "both"})
        update_sync_type_config_keys(schema.id, self.team.pk, updates={"cdc_last_log_position": "0/200"})
        schema.refresh_from_db()
        assert schema.sync_type_config == {
            "cdc_mode": "streaming",
            "cdc_table_mode": "both",
            "cdc_last_log_position": "0/200",
        }

    def test_merges_onto_latest_committed_not_stale_in_memory_copy(self) -> None:
        # A writer holding a copy loaded before a concurrent commit must not revert that commit.
        schema = self._create({"cdc_mode": "streaming", "cdc_last_log_position": "0/100"})
        stale = ExternalDataSchema.objects.get(id=schema.id)  # in-memory copy: position 0/100
        # A concurrent committed write moves the position forward:
        update_sync_type_config_keys(schema.id, self.team.pk, updates={"cdc_last_log_position": "0/900"})
        # The holder of the stale copy now persists an unrelated key through the helper:
        result = update_sync_type_config_keys(schema.id, self.team.pk, updates={"cdc_table_mode": "both"})
        # The concurrent position survives; the stale 0/100 never reaches the row.
        assert result["cdc_last_log_position"] == "0/900"
        assert result["cdc_table_mode"] == "both"
        assert stale.sync_type_config["cdc_last_log_position"] == "0/100"  # the copy really was stale
        schema.refresh_from_db()
        assert schema.sync_type_config["cdc_last_log_position"] == "0/900"


class TestMarkInitialSyncComplete(BaseTest):
    """The shared first-sync-complete transition (V2 pipelines + V3 loader post-load), whose
    False→True edge is what moves a CDC schema out of snapshot mode into streaming."""

    def setUp(self) -> None:
        super().setUp()
        self.source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type="Postgres",
        )

    def _create(
        self, sync_type: str, sync_type_config: dict, *, initial_sync_complete: bool = False
    ) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source=self.source,
            name="users",
            sync_type=sync_type,
            sync_type_config=sync_type_config,
            initial_sync_complete=initial_sync_complete,
        )

    @parameterized.expand(
        [
            (
                # First completion of a CDC snapshot flips it to streaming; keys written
                # concurrently by the CDC extract activity (deferred runs) must survive the flip.
                "cdc_snapshot_flips_to_streaming_preserving_other_keys",
                "cdc",
                {"cdc_mode": "snapshot", "cdc_deferred_runs": [{"run_uuid": "a"}], "dwh_storage_key": "users"},
                False,
                True,
                {"cdc_mode": "streaming", "cdc_deferred_runs": [{"run_uuid": "a"}], "dwh_storage_key": "users"},
            ),
            (
                # Already-streaming CDC schema (re-run after a reset) completes without a config rewrite.
                "cdc_already_streaming_config_unchanged",
                "cdc",
                {"cdc_mode": "streaming"},
                False,
                True,
                {"cdc_mode": "streaming"},
            ),
            (
                # Non-CDC schemas must never get a cdc_mode key injected.
                "non_cdc_config_untouched",
                "incremental",
                {"incremental_field": "id"},
                False,
                True,
                {"incremental_field": "id"},
            ),
            (
                # Only the False→True transition flips: a schema manually put back into snapshot
                # mode must not be flipped to streaming by a later run's completion.
                "already_complete_is_noop_even_in_snapshot_mode",
                "cdc",
                {"cdc_mode": "snapshot"},
                True,
                True,
                {"cdc_mode": "snapshot"},
            ),
        ]
    )
    def test_transition(
        self,
        _name: str,
        sync_type: str,
        config: dict,
        initial_flag: bool,
        expected_flag: bool,
        expected_config: dict,
    ) -> None:
        schema = self._create(sync_type, config, initial_sync_complete=initial_flag)
        mark_initial_sync_complete(schema.id, self.team.pk)
        schema.refresh_from_db()
        assert schema.initial_sync_complete == expected_flag
        assert schema.sync_type_config == expected_config


class TestCompleteSchemaRun(BaseTest):
    """The success repaint checks the broken marker under the row lock: the sweeper can mark the
    source broken while a run is in flight, and an unlocked check on a stale instance would
    overwrite the sweeper's FAILED with COMPLETED, hiding the breakage from the failure digest."""

    def _schema(self, sync_type_config: dict) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type="Postgres",
        )
        return ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source=source,
            name="users",
            sync_type="cdc",
            sync_type_config=sync_type_config,
            status=ExternalDataSchema.Status.FAILED,
            latest_error="boom",
        )

    @parameterized.expand(
        [
            (
                # The sweeper marked the source broken after this run's instance was loaded;
                # the stale instance must not repaint FAILED away.
                "broken_marker_blocks_repaint",
                {"cdc_mode": "streaming", "cdc_broken": {"reason": "slot_missing"}},
                False,
                ExternalDataSchema.Status.FAILED,
                {"cdc_mode": "streaming", "cdc_broken": {"reason": "slot_missing"}},
            ),
            (
                # A successful run proves extraction resumed: the pause marker is cleared in the
                # same transaction as the repaint.
                "paused_marker_cleared_on_repaint",
                {"cdc_mode": "streaming", "cdc_extraction_paused": {"reason": "auth_failed"}},
                True,
                ExternalDataSchema.Status.COMPLETED,
                {"cdc_mode": "streaming"},
            ),
            (
                "healthy_schema_repaints",
                {"cdc_mode": "streaming"},
                True,
                ExternalDataSchema.Status.COMPLETED,
                {"cdc_mode": "streaming"},
            ),
        ]
    )
    def test_repaint_respects_markers(
        self,
        _name: str,
        config: dict,
        expected_repainted: bool,
        expected_status: str,
        expected_config: dict,
    ) -> None:
        schema = self._schema({"cdc_mode": "streaming"})
        # The instance the activity holds predates the sweeper's marker write — a check against
        # its in-memory config would see no marker and repaint every case below.
        stale_instance = ExternalDataSchema.objects.get(id=schema.id)
        ExternalDataSchema.objects.filter(id=schema.id).update(sync_type_config=config)

        now = timezone.now()
        repainted = complete_schema_run(stale_instance, last_synced_at=now)

        assert repainted is expected_repainted
        schema.refresh_from_db()
        assert schema.status == expected_status
        assert schema.sync_type_config == expected_config
        assert schema.latest_error == ("boom" if not expected_repainted else None)
        # The passed instance mirrors the persisted outcome either way.
        assert stale_instance.status == expected_status
        assert stale_instance.sync_type_config == expected_config


@pytest.mark.parametrize(
    "clickhouse_type,expected",
    [
        ("String", "String"),
        ("Nullable(String)", "String"),
        ("LowCardinality(String)", "String"),
        ("LowCardinality(Nullable(String))", "String"),
    ],
)
def test_clean_type_unwraps_low_cardinality(clickhouse_type: str, expected: str) -> None:
    """`ai_events` exposes LowCardinality columns (event, model, provider, ...). clean_type must
    unwrap LowCardinality so the ClickHouse->HogQL mapping lookup resolves instead of KeyError-ing."""
    cleaned = clean_type(clickhouse_type)
    assert cleaned == expected
    assert cleaned in CLICKHOUSE_HOGQL_MAPPING


@pytest.mark.parametrize(
    "clickhouse_type,nullable,expected",
    [
        ("String", False, "String"),
        ("String", True, "Nullable(String)"),
        ("Nullable(String)", True, "Nullable(String)"),
        # LowCardinality must stay outermost — ClickHouse rejects Nullable(LowCardinality(...)).
        ("LowCardinality(String)", True, "LowCardinality(Nullable(String))"),
        ("LowCardinality(Nullable(String))", True, "LowCardinality(Nullable(String))"),
    ],
)
def test_clickhouse_column_to_dwh_column_nullable_wrapping(clickhouse_type: str, nullable: bool, expected: str) -> None:
    assert clickhouse_column_to_dwh_column("col", clickhouse_type, nullable)["clickhouse"] == expected


@pytest.mark.parametrize(
    "sync_type,expected",
    [
        (ExternalDataSchema.SyncType.XMIN, True),
        (ExternalDataSchema.SyncType.INCREMENTAL, False),
        (ExternalDataSchema.SyncType.CDC, False),
        (None, False),
    ],
)
def test_is_xmin(sync_type: str | None, expected: bool) -> None:
    assert ExternalDataSchema(sync_type=sync_type).is_xmin is expected


@pytest.mark.parametrize(
    "sync_type,expected",
    [
        (ExternalDataSchema.SyncType.XMIN, True),
        (ExternalDataSchema.SyncType.INCREMENTAL, True),
        (ExternalDataSchema.SyncType.APPEND, True),
        (ExternalDataSchema.SyncType.WEBHOOK, True),
        (ExternalDataSchema.SyncType.CDC, True),
        (ExternalDataSchema.SyncType.FULL_REFRESH, False),
        (None, False),
    ],
)
def test_table_row_count_is_cumulative(sync_type: str | None, expected: bool) -> None:
    assert ExternalDataSchema(sync_type=sync_type).table_row_count_is_cumulative is expected


@pytest.mark.parametrize(
    "sync_type_config,expected",
    [
        ({"xmin_last_value": 42, "xmin_ceiling": (1 << 32) + 42, "xmin_num_wraparound": 1}, (42, (1 << 32) + 42, 1)),
        ({}, (None, None, None)),
        (None, (None, None, None)),
    ],
)
def test_xmin_accessors(sync_type_config: dict | None, expected: tuple) -> None:
    schema = ExternalDataSchema(sync_type_config=sync_type_config)
    assert (schema.xmin_last_value, schema.xmin_ceiling, schema.xmin_num_wraparound) == expected


def test_update_xmin_state_writes_all_keys() -> None:
    schema = ExternalDataSchema(sync_type_config={})
    schema.update_xmin_state(ceiling_xid=100, ceiling_xid8=4294967396, num_wraparound=1, save=False)
    assert (schema.xmin_last_value, schema.xmin_ceiling, schema.xmin_num_wraparound) == (100, 4294967396, 1)


def test_reset_pipeline_clears_xmin_state() -> None:
    schema = ExternalDataSchema(
        sync_type=ExternalDataSchema.SyncType.XMIN,
        sync_type_config={"xmin_last_value": 100, "xmin_ceiling": 4294967396, "xmin_num_wraparound": 1},
        initial_sync_complete=True,
    )
    with patch.object(schema, "save"):
        schema.update_sync_type_config_for_reset_pipeline()
    assert "xmin_last_value" not in schema.sync_type_config
    assert "xmin_ceiling" not in schema.sync_type_config
    assert "xmin_num_wraparound" not in schema.sync_type_config
    assert schema.initial_sync_complete is False


def test_reset_pipeline_preserves_partition_overrides_but_clears_auto_detected() -> None:
    # The operator pins a count via the admin repartition action; it must survive the reset
    # that repartition bundles, while the auto-detected partition_count is wiped so it gets
    # re-derived (and then loses to the override) on the resync.
    schema = ExternalDataSchema(
        sync_type_config={
            "partition_count": 72,
            "partition_count_override": 10,
            "partition_size_override": 5,
            "partitioning_enabled": True,
            "partition_mode": "md5",
        }
    )
    with patch.object(schema, "save"):
        schema.update_sync_type_config_for_reset_pipeline()
    assert "partition_count" not in schema.sync_type_config
    assert "partitioning_enabled" not in schema.sync_type_config
    assert schema.partition_count_override == 10
    assert schema.partition_size_override == 5


def test_set_partitioning_enabled_consumes_partition_overrides() -> None:
    # Once the override is baked into the effective settings, it's a one-shot pin: drop it so
    # a later reset re-detects instead of re-applying a stale value.
    schema = ExternalDataSchema(sync_type_config={"partition_count_override": 10, "partition_size_override": 5})
    with patch.object(schema, "save"):
        schema.set_partitioning_enabled(
            partitioning_keys=["id"],
            partition_count=10,
            partition_size=None,
            partition_mode="md5",
            partition_format=None,
        )
    assert schema.partition_count == 10
    assert schema.partition_count_override is None
    assert schema.partition_size_override is None


def test_reset_pipeline_preserves_partition_mode_override() -> None:
    # Operator switches a table from md5 to datetime via the admin change-partition-mode action.
    # The mode/keys overrides must survive the bundled reset (which wipes the auto-detected
    # partition_mode and partitioning_keys) so the new mode wins the resync.
    schema = ExternalDataSchema(
        sync_type_config={
            "partition_mode": "md5",
            "partitioning_keys": ["record_id", "action_date"],
            "partition_count": 30,
            "partition_mode_override": "datetime",
            "partitioning_keys_override": ["action_date"],
            "partition_format": "month",
            "partitioning_enabled": True,
        }
    )
    with patch.object(schema, "save"):
        schema.update_sync_type_config_for_reset_pipeline()
    assert "partition_mode" not in schema.sync_type_config
    assert "partitioning_keys" not in schema.sync_type_config
    assert schema.partition_mode_override == "datetime"
    assert schema.partitioning_keys_override == ["action_date"]
    # partition_format is never reset, so the datetime granularity carries into the resync.
    assert schema.partition_format == "month"


def test_set_partitioning_enabled_consumes_partition_mode_override() -> None:
    schema = ExternalDataSchema(
        sync_type_config={"partition_mode_override": "datetime", "partitioning_keys_override": ["action_date"]}
    )
    with patch.object(schema, "save"):
        schema.set_partitioning_enabled(
            partitioning_keys=["action_date"],
            partition_count=None,
            partition_size=None,
            partition_mode="datetime",
            partition_format="month",
        )
    assert schema.partition_mode == "datetime"
    assert schema.partitioning_keys == ["action_date"]
    assert schema.partition_mode_override is None
    assert schema.partitioning_keys_override is None


def test_process_incremental_value_xid_returns_value_as_is() -> None:
    assert process_incremental_value(4294967396, IncrementalFieldType.XID) == 4294967396
    assert process_incremental_value(None, IncrementalFieldType.XID) is None


@pytest.mark.parametrize(
    "value,field_type,expected",
    [
        # Unix-epoch cursors (e.g. Stripe `created`) arrive as numbers on datetime-typed fields;
        # dateutil raised "Parser must be a string or character stream, not int" before this passthrough.
        (1718377611, IncrementalFieldType.DateTime, 1718377611),
        (1718377611, IncrementalFieldType.Timestamp, 1718377611),
        (1718377611, IncrementalFieldType.Date, 1718377611),
        (1718377611.5, IncrementalFieldType.DateTime, 1718377611.5),
        (datetime(2024, 6, 14, 15, 33, 31), IncrementalFieldType.DateTime, datetime(2024, 6, 14, 15, 33, 31)),
        ("2024-06-14T15:33:31", IncrementalFieldType.DateTime, datetime(2024, 6, 14, 15, 33, 31)),
        ("2024-06-14", IncrementalFieldType.Date, date(2024, 6, 14)),
        # JS `Date.prototype.toString()` cursors carry a parenthetical timezone name dateutil
        # can't parse on its own, even though the GMT offset earlier in the string is sufficient.
        (
            "Sun Mar 15 2026 16:59:47 GMT+0000 (Coordinated Universal Time)",
            IncrementalFieldType.DateTime,
            datetime(2026, 3, 15, 16, 59, 47, tzinfo=timezone.get_fixed_timezone(0)),
        ),
        (
            "Mon Jan 05 2026 09:15:00 GMT-0800 (Pacific Standard Time)",
            IncrementalFieldType.Date,
            date(2026, 1, 5),
        ),
        # A bare digit-string cursor on a date/time-typed field (e.g. a ClickHouse column Arrow
        # casts to String) crashed here: dateutil misreads it as a calendar year and overflows
        # past datetime's year-9999 ceiling. Fall back to the raw integer instead of crashing.
        ("20662", IncrementalFieldType.Timestamp, 20662),
        ("20662", IncrementalFieldType.DateTime, 20662),
        ("20662", IncrementalFieldType.Date, 20662),
        # Longer digit runs overflow C's int range and raise `OverflowError` instead of
        # `ParserError` - same fallback must catch both.
        ("20662123456", IncrementalFieldType.DateTime, 20662123456),
        # A genuine compact date string (YYYYMMDD) must still parse as a real date, not fall
        # back to the raw-integer path.
        ("20240115", IncrementalFieldType.Date, date(2024, 1, 15)),
    ],
)
def test_process_incremental_value_datetime_handles_epoch_numbers(value, field_type, expected) -> None:
    assert process_incremental_value(value, field_type) == expected


@pytest.mark.parametrize(
    "field_type",
    [IncrementalFieldType.DateTime, IncrementalFieldType.Timestamp, IncrementalFieldType.Date],
)
def test_process_incremental_value_datetime_reraises_unparseable_non_numeric_string(field_type) -> None:
    with pytest.raises(parser.ParserError):
        process_incremental_value("not-a-date-at-all", field_type)


@pytest.mark.parametrize(
    "value,field_type,lookback_seconds,expected",
    [
        (datetime(2026, 6, 14, 15, 33, 31), IncrementalFieldType.Timestamp, 3600, datetime(2026, 6, 14, 14, 33, 31)),
        (datetime(2026, 6, 14, 15, 33, 31), IncrementalFieldType.DateTime, 86400, datetime(2026, 6, 13, 15, 33, 31)),
        (date(2026, 6, 14), IncrementalFieldType.Date, 86400, date(2026, 6, 13)),
        # Date arithmetic ignores the sub-day part of the delta, so a <1-day lookback is a no-op for date fields.
        (date(2026, 6, 14), IncrementalFieldType.Date, 3600, date(2026, 6, 14)),
        (datetime(2026, 6, 14, 15, 33, 31), IncrementalFieldType.Timestamp, None, datetime(2026, 6, 14, 15, 33, 31)),
        (datetime(2026, 6, 14, 15, 33, 31), IncrementalFieldType.Timestamp, 0, datetime(2026, 6, 14, 15, 33, 31)),
        (datetime(2026, 6, 14, 15, 33, 31), IncrementalFieldType.Timestamp, -5, datetime(2026, 6, 14, 15, 33, 31)),
        (100, IncrementalFieldType.Integer, 3600, 100),
        (100, IncrementalFieldType.Numeric, 3600, 100),
        # Epoch-second cursor on a datetime field shifts directly instead of crashing on int - timedelta.
        (1718377611, IncrementalFieldType.DateTime, 3600, 1718374011),
        ("abc123", IncrementalFieldType.ObjectID, 3600, "abc123"),
        (None, IncrementalFieldType.Timestamp, 3600, None),
        (datetime(2026, 6, 14, 15, 33, 31), None, 3600, datetime(2026, 6, 14, 15, 33, 31)),
    ],
)
def test_apply_incremental_lookback(value, field_type, lookback_seconds, expected) -> None:
    assert apply_incremental_lookback(value, field_type, lookback_seconds) == expected


class TestStagedIncrementalCursor:
    def _make_schema(self, **config: object) -> ExternalDataSchema:
        schema = ExternalDataSchema(
            sync_type_config={
                "incremental_field_type": IncrementalFieldType.Integer,
                **config,
            }
        )
        return schema

    def test_stage_writes_run_uuid_and_last_value(self) -> None:
        schema = self._make_schema()
        with patch.object(schema, "save"):
            schema.stage_incremental_field_value("run-1", 42)
        staged = schema.sync_type_config["incremental_staged"]
        assert staged == {"run_uuid": "run-1", "last_value": 42}

    def test_stage_keeps_epoch_number_for_datetime_field(self) -> None:
        # A datetime-typed epoch cursor must round-trip as a number, not "1718377611", so the next
        # run's read-back doesn't feed a numeric string into dateutil and crash.
        schema = self._make_schema(incremental_field_type=IncrementalFieldType.DateTime)
        with patch.object(schema, "save"):
            schema.stage_incremental_field_value("run-1", 1718377611)
        assert schema.sync_type_config["incremental_staged"]["last_value"] == 1718377611

    def test_update_incremental_field_value_keeps_epoch_number_for_datetime_field(self) -> None:
        schema = self._make_schema(incremental_field_type=IncrementalFieldType.DateTime)
        schema.update_incremental_field_value(1718377611, save=False)
        assert schema.sync_type_config["incremental_field_last_value"] == 1718377611

    def test_stage_writes_earliest_value(self) -> None:
        schema = self._make_schema()
        with patch.object(schema, "save"):
            schema.stage_incremental_field_value("run-1", None, earliest_value=10)
        staged = schema.sync_type_config["incremental_staged"]
        assert staged == {"run_uuid": "run-1", "earliest_value": 10}

    def test_stage_overwrites_when_different_run_uuid(self) -> None:
        schema = self._make_schema(incremental_staged={"run_uuid": "old", "last_value": 1, "earliest_value": 5})
        with patch.object(schema, "save"):
            schema.stage_incremental_field_value("run-2", 99)
        staged = schema.sync_type_config["incremental_staged"]
        assert staged["run_uuid"] == "run-2"
        assert staged["last_value"] == 99
        assert "earliest_value" not in staged

    def test_stage_merges_when_same_run_uuid(self) -> None:
        schema = self._make_schema()
        with patch.object(schema, "save"):
            schema.stage_incremental_field_value("run-1", None, earliest_value=10)
            schema.stage_incremental_field_value("run-1", 42)
        staged = schema.sync_type_config["incremental_staged"]
        assert staged == {"run_uuid": "run-1", "earliest_value": 10, "last_value": 42}

    def test_promote_moves_last_value_to_live(self) -> None:
        schema = self._make_schema(incremental_staged={"run_uuid": "run-1", "last_value": 42})
        with patch.object(schema, "save"):
            result = schema.promote_staged_incremental_values("run-1")
        assert result is True
        assert schema.sync_type_config["incremental_field_last_value"] == 42
        assert "incremental_staged" not in schema.sync_type_config

    def test_promote_moves_earliest_value_to_live(self) -> None:
        schema = self._make_schema(incremental_staged={"run_uuid": "run-1", "earliest_value": 5})
        with patch.object(schema, "save"):
            result = schema.promote_staged_incremental_values("run-1")
        assert result is True
        assert schema.sync_type_config["incremental_field_earliest_value"] == 5

    def test_promote_rejects_wrong_run_uuid(self) -> None:
        schema = self._make_schema(incremental_staged={"run_uuid": "run-1", "last_value": 42})
        with patch.object(schema, "save"):
            result = schema.promote_staged_incremental_values("run-WRONG")
        assert result is False
        assert "incremental_field_last_value" not in schema.sync_type_config

    def test_promote_returns_false_when_no_staged(self) -> None:
        schema = self._make_schema()
        with patch.object(schema, "save"):
            result = schema.promote_staged_incremental_values("run-1")
        assert result is False

    def test_reset_pipeline_clears_staged(self) -> None:
        schema = self._make_schema(incremental_staged={"run_uuid": "run-1", "last_value": 42})
        with patch.object(schema, "save"):
            schema.update_sync_type_config_for_reset_pipeline()
        assert "incremental_staged" not in schema.sync_type_config


class TestSSHTunnelPortValidation(SimpleTestCase):
    @parameterized.expand(
        [
            # Out-of-range ports previously slipped through to sshtunnel, which asserted `port >= 0`
            # and crashed credential validation with a bare AssertionError ("PORT < 0 (...)").
            ("negative", -122, False),
            ("zero", 0, False),
            ("too_large", 70000, False),
            ("non_numeric", "not-a-number", False),
            ("http", 80, False),
            ("https", 443, False),
            ("ssh", 22, True),
            ("postgres", 5432, True),
            ("max_valid", 65535, True),
        ]
    )
    def test_has_valid_port(self, _name: str, port: int | str, expected_valid: bool) -> None:
        tunnel = SSHTunnel(
            enabled=True,
            host="ssh.example.com",
            port=port,
            auth_type="password",
            username="user",
            password="pw",
            private_key=None,
            passphrase=None,
        )
        assert tunnel.has_valid_port()[0] is expected_valid


class TestRepartitionHoldsImport:
    """The hold pauses a schema's imports so a multi-budget rewrite can keep its checkpoint.

    Every condition here decides whether a customer's table keeps ingesting, so each case is a
    distinct way of getting that wrong: no rewrite at all, a rewrite still advancing, one that
    stopped, and checkpoints whose stamp we cannot age out.
    """

    def _schema_with(self, rewrite: dict[str, Any] | None) -> ExternalDataSchema:
        config: dict[str, Any] = {}
        if rewrite is not None:
            config["repartition_rewrite"] = rewrite
        return ExternalDataSchema(sync_type_config=config)

    def _stamped(self, ago: timedelta) -> dict[str, Any]:
        return {"temp_uri": "s3://t", "rows_written": 10, "held_at": (datetime.now(UTC) - ago).isoformat()}

    @parameterized.expand(
        [
            ("no_rewrite", None, False),
            ("fresh_checkpoint", timedelta(minutes=5), True),
            ("within_the_window", REPARTITION_HOLD_MAX_AGE - timedelta(hours=1), True),
            ("lapsed", REPARTITION_HOLD_MAX_AGE + timedelta(hours=1), False),
        ]
    )
    def test_hold_tracks_whether_the_rewrite_is_still_advancing(
        self, _name: str, ago: timedelta | None, expected: bool
    ) -> None:
        rewrite = None if ago is None else self._stamped(ago)
        assert self._schema_with(rewrite).repartition_holds_import is expected

    @parameterized.expand(
        [
            # A checkpoint written before `held_at` existed. Holding on it would pause imports with no
            # way to ever age the hold out.
            ("missing_stamp", {"temp_uri": "s3://t", "rows_written": 10}),
            ("unparseable_stamp", {"temp_uri": "s3://t", "held_at": "not-a-timestamp"}),
            ("non_string_stamp", {"temp_uri": "s3://t", "held_at": 1234}),
        ]
    )
    def test_an_unusable_stamp_never_holds(self, _name: str, rewrite: dict[str, Any]) -> None:
        assert self._schema_with(rewrite).repartition_holds_import is False

    def test_a_naive_stamp_is_read_as_utc(self) -> None:
        # `held_at` is written with `datetime.now(UTC).isoformat()`, but a hand-edited or older row
        # can carry a naive string. Comparing that against an aware now() raises, which would fail
        # the import activity rather than skip the hold.
        naive = (datetime.now(UTC) - timedelta(minutes=5)).replace(tzinfo=None).isoformat()
        schema = self._schema_with({"temp_uri": "s3://t", "held_at": naive})
        assert schema.repartition_holds_import is True
