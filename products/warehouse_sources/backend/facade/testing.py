"""
Shared test-infrastructure wiring for warehouse_sources.

Many sibling products' test suites build a real warehouse table (to exercise queries over
imported data) or subclass the warehouse access-control test mixin. Those helpers live in
this product's test tree; re-export them here so cross-product tests reach them through the
facade rather than importing the internal test modules directly.

Resolved lazily (PEP 562) so the test-only dependencies (S3 fixtures, ``APIBaseTest``) never
load unless a test actually imports one of these — keeping them off the ``django.setup()`` path.
"""

_MODULES = {
    "create_data_warehouse_table_from_csv": "products.warehouse_sources.backend.test.utils",
    "WarehouseAccessControlTestMixin": "products.warehouse_sources.backend.tests.api._access_control_base",
}

__all__ = sorted(_MODULES)


def __getattr__(name: str):
    module = _MODULES.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(module), name)
