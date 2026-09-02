"""
External-product hook wiring for warehouse_sources.

Light re-exports of the data-import hook-inversion surface that sibling products
register during ``django.setup()`` (in ``AppConfig.ready()``). Deliberately kept
separate from the heavy temporal registration in ``facade.temporal`` (which imports
the data-import settings — temporalio, dlt, pandas, ...) so that importing the hooks
on the startup path does not drag the whole pipeline onto every process boot.
"""

from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    BINDING_KIND_SAVED_QUERY,
    BINDING_KIND_SCHEMA,
    MATERIALIZED_VIEW_SOURCE_TYPE,
    AccountPropertySourceProjection,
    EmitSignalsActivityInputs,
    PersonPropertySourceProjection,
    PersonPropertySyncActivityInputs,
    PersonPropertySyncRunRecord,
    PersonPropertySyncSource,
    WarehouseBinding,
    account_property_projection_for,
    person_property_projection_for,
    register_account_property_projection,
    register_data_quality_checks_gate,
    register_emit_signals_gate,
    register_engineering_analytics_view_sync,
    register_person_property_projection,
    register_person_property_sync_recorder,
    register_person_property_sync_sources,
    register_revenue_view_sync,
    run_revenue_view_sync,
    saved_query_binding,
    schema_binding,
)

from .contracts import RevenueViewSyncInput

__all__ = [
    "BINDING_KIND_SAVED_QUERY",
    "BINDING_KIND_SCHEMA",
    "MATERIALIZED_VIEW_SOURCE_TYPE",
    "AccountPropertySourceProjection",
    "EmitSignalsActivityInputs",
    "PersonPropertySourceProjection",
    "PersonPropertySyncActivityInputs",
    "PersonPropertySyncRunRecord",
    "PersonPropertySyncSource",
    "RevenueViewSyncInput",
    "WarehouseBinding",
    "account_property_projection_for",
    "person_property_projection_for",
    "register_account_property_projection",
    "register_data_quality_checks_gate",
    "register_emit_signals_gate",
    "register_engineering_analytics_view_sync",
    "register_person_property_projection",
    "register_person_property_sync_recorder",
    "register_person_property_sync_sources",
    "register_revenue_view_sync",
    "run_revenue_view_sync",
    "saved_query_binding",
    "schema_binding",
]
