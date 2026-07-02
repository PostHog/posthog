import uuid
from datetime import date, datetime

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db.models import Model

from posthog.models.signals import model_activity_signal

from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    apply_incremental_lookback,
    process_incremental_value,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.models.util import CLICKHOUSE_HOGQL_MAPPING, clean_type
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
