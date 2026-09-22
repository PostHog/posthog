"""
Shared test-infrastructure wiring for warehouse_sources.

Many sibling products' test suites build a real warehouse table (to exercise queries over
imported data) or subclass the warehouse access-control test mixin. The mixin's module
lives inside facade/ so the contract-check inputs always watch it.

Resolved lazily (PEP 562) so the test-only dependencies (S3 fixtures, ``APIBaseTest``)
never load unless a caller actually imports one of these — non-test code reaches this
module too (demo-data generation uses the table helper), so they must stay off the
module-body import path.
"""

_MODULES = {
    "create_data_warehouse_table_from_csv": "products.warehouse_sources.backend.test.utils",
    "WarehouseAccessControlTestMixin": "products.warehouse_sources.backend.facade._access_control_base",
}

__all__ = sorted(_MODULES)


def __getattr__(name: str):
    module = _MODULES.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(module), name)
