from typing import TYPE_CHECKING

from posthog.models import Team
from posthog.models.scoping.manager import resolve_effective_team_id

from products.marketing_analytics.backend.hogql_queries.marketing_recommendations_query_runner import (
    RECOMMENDATION_SOURCE_TYPES,
)
from products.warehouse_sources.backend.facade.api import denied_table_ids, list_schemas_for_source, list_sources

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl


def can_resolve(team_id: int, user_access_control: "UserAccessControl") -> bool:
    # A resolve answers whether a guessed search term was already resolved, so it needs every table the
    # recommendations can come from, paused and deleted ones included. Resolutions belong to the project, so
    # every environment's sources count.
    project_id = resolve_effective_team_id(team_id)
    environment_ids = [project_id, *Team.objects.filter(parent_team_id=project_id).values_list("id", flat=True)]
    for environment_id, access in user_access_control.for_team_ids(environment_ids).items():
        table_ids = {
            schema.table_id
            for source in list_sources(environment_id, include_deleted=True)
            if source.source_type in RECOMMENDATION_SOURCE_TYPES
            for schema in list_schemas_for_source(source.id, environment_id)
            if schema.table_id is not None
        }
        if not table_ids:
            continue
        # Table rules fall back to their defaults in an environment the user was denied, so check that first.
        if not access.has_project_access or not table_ids.isdisjoint(denied_table_ids(environment_id, access)):
            return False
    return True
