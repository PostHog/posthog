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
    "ExternalDataSchemaStatus",  # noqa: F822 — resolved lazily via __getattr__ below
    "ExternalDataSourceType",
    "IncrementalField",
    "IncrementalFieldType",
    "PartitionSettings",
]


def __getattr__(name: str):
    # Status choices live on the Django model; resolve lazily so this module stays
    # importable before django.setup() (it is on the startup path for config consumers).
    if name == "ExternalDataSchemaStatus":
        from products.warehouse_sources.backend.models.external_data_schema import (  # noqa: PLC0415 — keeps the model off the pre-setup import path
            ExternalDataSchema,
        )

        return ExternalDataSchema.Status
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
