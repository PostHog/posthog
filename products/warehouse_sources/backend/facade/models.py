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
from products.warehouse_sources.backend.models.custom_oauth2_integration import (
    CustomOAuth2Integration,
    get_custom_oauth2_integration,
)
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob, get_latest_run_if_exists
from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    get_all_schemas_for_source_id,
    sync_frequency_interval_to_sync_frequency,
    sync_frequency_to_sync_frequency_interval,
    sync_old_schemas_with_new_schemas,
    update_should_sync,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.external_data_source import (
    ExternalDataSource,
    get_direct_external_data_source_for_connection,
)
from products.warehouse_sources.backend.models.pending_source_credential import PendingSourceCredential
from products.warehouse_sources.backend.models.ssh_tunnel import SSHTunnel
from products.warehouse_sources.backend.models.table import (
    DataWarehouseTable,
    DataWarehouseTableColumns,
    acreate_datawarehousetable,
    asave_datawarehousetable,
)
from products.warehouse_sources.backend.models.util import (
    mysql_column_to_dwh_column,
    mysql_columns_to_dwh_columns,
    postgres_column_to_dwh_column,
    postgres_columns_to_dwh_columns,
    validate_source_prefix,
    validate_warehouse_table_url_pattern,
)

__all__ = [
    "CustomOAuth2Integration",
    "DataWarehouseCredential",
    "DataWarehouseTable",
    "DataWarehouseTableColumns",
    "ExternalDataJob",
    "ExternalDataSchema",
    "ExternalDataSource",
    "PendingSourceCredential",
    "SSHTunnel",
    "WarehouseColumnAnnotation",
    "WarehouseColumnStatistics",
    "acreate_datawarehousetable",
    "asave_datawarehousetable",
    "get_custom_oauth2_integration",
    "get_all_schemas_for_source_id",
    "get_direct_external_data_source_for_connection",
    "get_latest_run_if_exists",
    "get_or_create_datawarehouse_credential",
    "mysql_column_to_dwh_column",
    "mysql_columns_to_dwh_columns",
    "postgres_column_to_dwh_column",
    "postgres_columns_to_dwh_columns",
    "sync_frequency_interval_to_sync_frequency",
    "sync_frequency_to_sync_frequency_interval",
    "sync_old_schemas_with_new_schemas",
    "update_should_sync",
    "update_sync_type_config_keys",
    "validate_source_prefix",
    "validate_warehouse_table_url_pattern",
]
