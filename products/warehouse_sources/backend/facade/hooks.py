"""
External-product hook wiring for warehouse_sources.

Light re-exports of the data-import hook-inversion surface that sibling products
register during ``django.setup()`` (in ``AppConfig.ready()``). Deliberately kept
separate from the heavy temporal registration in ``facade.temporal`` (which imports
the data-import settings — temporalio, dlt, pandas, ...) so that importing the hooks
on the startup path does not drag the whole pipeline onto every process boot.
"""

from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    EmitSignalsActivityInputs,
    register_emit_signals_gate,
    register_revenue_view_sync,
)

__all__ = [
    "EmitSignalsActivityInputs",
    "register_emit_signals_gate",
    "register_revenue_view_sync",
]
