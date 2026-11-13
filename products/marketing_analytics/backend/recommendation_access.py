from typing import TYPE_CHECKING

from products.marketing_analytics.backend.hogql_queries.marketing_recommendations_query_runner import (
    RECOMMENDATION_SOURCE_TYPES,
)
from products.warehouse_sources.backend.facade.api import denied_table_ids, list_schemas_for_source, list_sources

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl


def can_resolve(team_id: int, user_access_control: "UserAccessControl") -> bool:
    # A resolve answers whether a guessed search term was already resolved, so it needs every table the
    # recommendations can come from, paused and deleted ones included.
    table_ids = {
        schema.table_id
        for source in list_sources(team_id, include_deleted=True)
        if source.source_type in RECOMMENDATION_SOURCE_TYPES
        for schema in list_schemas_for_source(source.id, team_id)
        if schema.table_id is not None
    }
    return not table_ids or table_ids.isdisjoint(denied_table_ids(team_id, user_access_control))
