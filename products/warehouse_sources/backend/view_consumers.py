from collections.abc import Collection
from uuid import UUID

from products.cdp.backend.models.hog_functions import HogFunction
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    saved_queries_with_property_sources,
)
from products.workflows.backend.facade.api import active_workflow_warehouse_table_names

VIEW_TRIGGER_SOURCE = "data-warehouse-view"


def saved_queries_feeding_consumers(team_id: int, saved_query_ids: Collection[UUID]) -> frozenset[UUID]:
    """The given saved queries whose refreshes feed person, group or account properties, a hog function or a workflow."""
    names = dict(
        DataWarehouseSavedQuery.objects.filter(team_id=team_id, id__in=saved_query_ids)
        .exclude(deleted=True)
        .values_list("id", "name")
    )
    if not names:
        return frozenset()
    triggered_names = _hog_function_view_names(team_id) | active_workflow_warehouse_table_names(
        team_id=team_id, trigger_source=VIEW_TRIGGER_SOURCE, table_names=names.values()
    )
    with_property_sources = saved_queries_with_property_sources(
        team_id, [str(saved_query_id) for saved_query_id in names]
    )
    return frozenset(
        saved_query_id
        for saved_query_id, name in names.items()
        if name in triggered_names or str(saved_query_id) in with_property_sources
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
