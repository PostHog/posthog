"""
Model-class wiring for warehouse_sources.

Light re-exports of the ORM model classes for cross-product object-consumers that
genuinely need the classes — HogQL/query/view builders that traverse relations,
dispatch on class identity (``isinstance``), or call model methods, plus the few
write-path callers. Deliberately free of heavy imports (no ClickHouse→HogQL type
tables or query helpers, unlike ``facade.hogql``), so importing it adds nothing
beyond the models Django already loads at ``django.setup()``.

Consumers that only read fields should use ``facade.api`` (contracts) instead.
"""

from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable, DataWarehouseTableColumns

__all__ = [
    "DataWarehouseCredential",
    "DataWarehouseTable",
    "DataWarehouseTableColumns",
    "ExternalDataJob",
    "ExternalDataSchema",
    "ExternalDataSource",
]
