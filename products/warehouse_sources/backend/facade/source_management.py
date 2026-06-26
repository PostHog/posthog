"""
Source-management wiring for warehouse_sources.

Re-exports the source-config, CDC, and row-filter helpers that the data_warehouse
source/schema management API uses to validate and configure data sources. These live
deep under ``temporal.data_imports.sources`` and pull heavy dependencies (DB drivers,
the source registry), so this module is loaded lazily (PEP 562): names resolve on
first access, keeping it off the ``django.setup()`` path and out of any import cycle.
"""

_B = "products.warehouse_sources.backend.temporal.data_imports."

_LAZY = {
    "SourceRegistry": "sources",
    "get_cdc_adapter": "cdc.adapters",
    "source_type_supports_cdc": "cdc.adapters",
    "WebhookSource": "sources.common.base",
    "RowFilterValidationError": "sources.common.sql",
    "filter_dwh_columns_by_enabled_columns": "sources.common.sql",
    "validate_and_coerce_row_filters": "sources.common.sql",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(_B + module), name)
