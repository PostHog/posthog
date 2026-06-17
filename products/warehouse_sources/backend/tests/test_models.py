import pytest
from unittest.mock import patch

from django.db.models import Model

from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.models.util import CLICKHOUSE_HOGQL_MAPPING, clean_type


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
    "sync_type_config,expected",
    [
        # xmin_ceiling here is epoch 1: (1 << 32) + 42 = 4294967338.
        ({"xmin_last_value": 42, "xmin_ceiling": 4294967338, "xmin_num_wraparound": 1}, (42, 4294967338, 1)),
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
