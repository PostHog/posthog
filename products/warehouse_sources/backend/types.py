"""Product-internal re-export of the shared type surface, which lives in the facade
(``facade/types.py``) so contract-check inputs always watch it."""

from products.warehouse_sources.backend.facade.types import (
    DIRECT_ENGINE_BY_SOURCE_TYPE as DIRECT_ENGINE_BY_SOURCE_TYPE,
    DataWarehouseManagedViewSetKind as DataWarehouseManagedViewSetKind,
    ExternalDataSourceType as ExternalDataSourceType,
    IncrementalField as IncrementalField,
    IncrementalFieldType as IncrementalFieldType,
    ManagedWarehouseSQLMode as ManagedWarehouseSQLMode,
    PartitionSettings as PartitionSettings,
    external_data_source_type_choices as external_data_source_type_choices,
)
