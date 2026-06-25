"""
Temporal wiring for warehouse_sources.

Re-exports the objects that cross the boundary for temporal orchestration — the
workflow/activity registration the temporal worker bootstrap loads, the
external-product hook callbacks sibling products register during ``django.setup()``,
and the queryable-table prep helper the data-modeling temporal workflow calls. These
are objects/registration, not contract data.
"""

from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    EmitSignalsActivityInputs,
    register_emit_signals_gate,
    register_revenue_view_sync,
)
from products.warehouse_sources.backend.temporal.data_imports.settings import ACTIVITIES, WORKFLOWS
from products.warehouse_sources.backend.temporal.data_imports.util import prepare_s3_files_for_querying

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "EmitSignalsActivityInputs",
    "prepare_s3_files_for_querying",
    "register_emit_signals_gate",
    "register_revenue_view_sync",
]
