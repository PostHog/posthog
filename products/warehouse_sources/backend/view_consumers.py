from collections.abc import Collection
from uuid import UUID

from products.cdp.backend.facade.api import warehouse_tables_with_enabled_hog_functions
from products.data_modeling.backend.facade.api import all_saved_query_names
from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    saved_queries_with_property_sources,
)
from products.workflows.backend.facade.api import active_workflow_warehouse_table_names

VIEW_TRIGGER_SOURCE = "data-warehouse-view"


def saved_queries_feeding_consumers(team_id: int, saved_query_ids: Collection[UUID]) -> frozenset[UUID]:
    """The given saved queries whose refreshes feed person, group or account properties, a hog function or a workflow."""
    team_names = all_saved_query_names(team_id)
    names = {
        saved_query_id: team_names[str(saved_query_id)]
        for saved_query_id in saved_query_ids
        if str(saved_query_id) in team_names
    }
    if not names:
        return frozenset()
    triggered_names = warehouse_tables_with_enabled_hog_functions(
        team_id=team_id, trigger_source=VIEW_TRIGGER_SOURCE, table_names=names.values()
    ) | active_workflow_warehouse_table_names(
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
