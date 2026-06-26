"""
HogQL system-table wiring for warehouse_sources.

The HogQL database builder (``posthog/hogql/database/database.py``) registers these
model classes as system tables. They cross the boundary as objects — the builder
keys off class identity and calls ORM-bound methods (``hogql_definition()``,
``raw_objects``, ``queryable()``) — not as contract data, so they are re-exported
here rather than through ``facade/api.py``.

Keeping them in their own submodule keeps the heavy HogQL-adjacent model surface off
the ``facade/api.py`` import path, so config-only consumers don't drag it onto the
``django.setup()`` path (see the skill's note on splitting light shared tables out of
the heavy re-exports).
"""

from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import (
    SERIALIZED_FIELD_TO_CLICKHOUSE_MAPPING,
    DataWarehouseTable,
    DataWarehouseTableColumns,
)

# Table/type resolution used by the HogQL database builder and query runners. These return
# ORM objects / reference HogQL field factories, so they belong with the object wiring here
# rather than the contract-returning facade/api.py.
from products.warehouse_sources.backend.models.util import (
    CLICKHOUSE_HOGQL_MAPPING,
    STR_TO_HOGQL_MAPPING,
    clean_type,
    get_view_or_table_by_name,
    remove_named_tuples,
)

__all__ = [
    "CLICKHOUSE_HOGQL_MAPPING",
    "SERIALIZED_FIELD_TO_CLICKHOUSE_MAPPING",
    "STR_TO_HOGQL_MAPPING",
    "DataWarehouseCredential",
    "DataWarehouseTable",
    "DataWarehouseTableColumns",
    "ExternalDataJob",
    "ExternalDataSchema",
    "ExternalDataSource",
    "clean_type",
    "get_view_or_table_by_name",
    "remove_named_tuples",
]
