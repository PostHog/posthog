"""
Shared type wiring for warehouse_sources.

Re-exports the framework-light shared enums and typed structures that cross-product
consumers compare against or annotate with. These carry Django ``TextChoices`` /
``StrEnum`` semantics (not framework-free), so they are object wiring re-exported here
rather than contracts in ``facade.contracts``.
"""

from products.warehouse_sources.backend.types import (
    DIRECT_ENGINE_BY_SOURCE_TYPE,
    DataWarehouseManagedViewSetKind,
    ExternalDataSourceType,
    IncrementalField,
    IncrementalFieldType,
    PartitionSettings,
)

__all__ = [
    "DIRECT_ENGINE_BY_SOURCE_TYPE",
    "DataWarehouseManagedViewSetKind",
    "ExternalDataSourceType",
    "IncrementalField",
    "IncrementalFieldType",
    "PartitionSettings",
]
