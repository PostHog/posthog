from collections.abc import Collection
from uuid import UUID

from products.cdp.backend.models.hog_functions import HogFunction
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    account_property_projection_for,
    person_property_projection_for,
    saved_query_binding,
)
from products.workflows.backend.facade.api import has_active_workflow_for_warehouse_table

VIEW_TRIGGER_SOURCE = "data-warehouse-view"


def saved_queries_feeding_consumers(team_id: int, saved_query_ids: Collection[UUID]) -> frozenset[UUID]:
    """The given saved queries whose refreshes feed person or account properties, a hog function or a workflow."""
    names = dict(
        DataWarehouseSavedQuery.objects.filter(team_id=team_id, id__in=saved_query_ids)
        .exclude(deleted=True)
        .values_list("id", "name")
    )
    if not names:
        return frozenset()
    hog_function_tables = _hog_function_view_names(team_id)
    return frozenset(
        saved_query_id
        for saved_query_id, name in names.items()
        if name in hog_function_tables
        or has_active_workflow_for_warehouse_table(team_id=team_id, trigger_source=VIEW_TRIGGER_SOURCE, table_name=name)
        or _feeds_properties(team_id, saved_query_id)
    )


def _hog_function_view_names(team_id: int) -> set[str]:
    filters = (
        HogFunction.objects.filter(team_id=team_id, enabled=True, filters__source=VIEW_TRIGGER_SOURCE)
        .exclude(deleted=True)
        .values_list("filters", flat=True)
    )
    return {
        table["table_name"]
        for function_filters in filters
        for table in (function_filters or {}).get("data_warehouse") or []
        if isinstance(table, dict) and table.get("table_name")
    }


def _feeds_properties(team_id: int, saved_query_id: UUID) -> bool:
    binding = saved_query_binding(saved_query_id)
    return bool(person_property_projection_for(team_id, binding) or account_property_projection_for(team_id, binding))
