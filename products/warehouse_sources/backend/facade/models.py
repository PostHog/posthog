"""
Model-class wiring for warehouse_sources.

Light re-exports of the warehouse_sources models package's public surface — the ORM
model classes plus their module-level helper functions — for cross-product
object-consumers that genuinely need them (HogQL/view/query builders that traverse
relations, dispatch on ``isinstance``, call model methods, or use the package's query
helpers). Deliberately free of heavy imports (no ClickHouse→HogQL type tables, unlike
``facade.hogql``), so importing it adds nothing beyond the models Django already loads
at ``django.setup()``.

Consumers that only read fields should use ``facade.api`` (contracts) instead.
"""

from products.warehouse_sources.backend.models.column_annotation import WarehouseColumnAnnotation
from products.warehouse_sources.backend.models.column_statistics import WarehouseColumnStatistics
from products.warehouse_sources.backend.models.credential import (
    DataWarehouseCredential,
    get_or_create_datawarehouse_credential,
)
from products.warehouse_sources.backend.models.external_data_destination import (
    ExternalDataDestination,
    ExternalDataSchemaDestination,
    ExternalDataSourceDestination,
    resolve_destinations,
)
from products.warehouse_sources.backend.models.external_data_job import (
    ExternalDataJob,
    get_latest_run_if_exists,
    latest_completed_job_prefetch,
)
from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    auto_enable_new_schemas,
    get_all_schemas_for_source_id,
    get_schemas_for_direct_reconciliation,
    sync_frequency_interval_to_sync_frequency,
    sync_frequency_to_sync_frequency_interval,
    sync_old_schemas_with_new_schemas,
    update_should_sync,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.external_data_source import (
    MANAGED_WAREHOUSE_LEGACY_CREDENTIAL_KINDS,
    MANAGED_WAREHOUSE_PROJECT_READER_CREDENTIAL_KIND,
    MANAGED_WAREHOUSE_SERVICE_CREDENTIAL_KIND,
    MANAGED_WAREHOUSE_SOURCE_PREFIX,
    ExternalDataSource,
    get_direct_external_data_source_for_connection,
    is_managed_warehouse_connection_ready,
)
from products.warehouse_sources.backend.models.pending_source_credential import PendingSourceCredential
from products.warehouse_sources.backend.models.table import (
    SERIALIZED_FIELD_TO_CLICKHOUSE_MAPPING,
    DataWarehouseTable,
    DataWarehouseTableColumns,
    acreate_datawarehousetable,
    asave_datawarehousetable,
    create_datawarehousetable,
)
from products.warehouse_sources.backend.models.util import (
    clickhouse_column_to_dwh_column,
    clickhouse_columns_to_dwh_columns,
    motherduck_column_to_dwh_column,
    motherduck_columns_to_dwh_columns,
    mysql_column_to_dwh_column,
    mysql_columns_to_dwh_columns,
    postgres_column_to_dwh_column,
    postgres_columns_to_dwh_columns,
    remove_named_tuples,
    snowflake_column_to_dwh_column,
    snowflake_columns_to_dwh_columns,
    trino_column_to_dwh_column,
    trino_columns_to_dwh_columns,
    validate_source_prefix,
    validate_warehouse_table_url_pattern,
)

__all__ = [
    "DataWarehouseCredential",
    "DataWarehouseTable",
    "DataWarehouseTableColumns",
    "ExternalDataDestination",
    "ExternalDataJob",
    "ExternalDataSchema",
    "ExternalDataSchemaDestination",
    "ExternalDataSource",
    "ExternalDataSourceDestination",
    "MANAGED_WAREHOUSE_LEGACY_CREDENTIAL_KINDS",
    "MANAGED_WAREHOUSE_PROJECT_READER_CREDENTIAL_KIND",
    "MANAGED_WAREHOUSE_SERVICE_CREDENTIAL_KIND",
    "MANAGED_WAREHOUSE_SOURCE_PREFIX",
    "PendingSourceCredential",
    "SERIALIZED_FIELD_TO_CLICKHOUSE_MAPPING",
    "WarehouseColumnAnnotation",
    "WarehouseColumnStatistics",
    "acreate_datawarehousetable",
    "asave_datawarehousetable",
    "auto_enable_new_schemas",
    "create_datawarehousetable",
    "get_all_schemas_for_source_id",
    "get_schemas_for_direct_reconciliation",
    "get_direct_external_data_source_for_connection",
    "is_managed_warehouse_connection_ready",
    "get_latest_run_if_exists",
    "latest_completed_job_prefetch",
    "get_or_create_datawarehouse_credential",
    "clickhouse_column_to_dwh_column",
    "clickhouse_columns_to_dwh_columns",
    "motherduck_column_to_dwh_column",
    "motherduck_columns_to_dwh_columns",
    "trino_column_to_dwh_column",
    "trino_columns_to_dwh_columns",
    "mysql_column_to_dwh_column",
    "mysql_columns_to_dwh_columns",
    "postgres_column_to_dwh_column",
    "postgres_columns_to_dwh_columns",
    "remove_named_tuples",
    "resolve_destinations",
    "snowflake_column_to_dwh_column",
    "snowflake_columns_to_dwh_columns",
    "sync_frequency_interval_to_sync_frequency",
    "sync_frequency_to_sync_frequency_interval",
    "sync_old_schemas_with_new_schemas",
    "update_should_sync",
    "update_sync_type_config_keys",
    "validate_source_prefix",
    "validate_warehouse_table_url_pattern",
]
