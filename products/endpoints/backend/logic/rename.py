from typing import cast

from django.db import transaction

from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.hogql.rename import rewrite_table_references

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.data_modeling.backend.facade.api import sync_saved_query_to_dag
from products.endpoints.backend.models import EndpointVersion


@transaction.atomic
def rewrite_endpoint_version_sql_references(
    team_id: int, old_name: str, new_name: str, user_access_control: object | None
) -> int:
    """Rewrite saved-query table references in every SQL endpoint version in a team."""
    versions = EndpointVersion.objects.filter(
        endpoint__team_id=team_id,
        query__kind="HogQLQuery",
        query__query__icontains=old_name,
    ).select_related("endpoint", "saved_query")
    rewrites: list[tuple[EndpointVersion, dict]] = []

    for version in versions:
        query = version.query
        if not isinstance(query, dict) or not isinstance(query.get("query"), str):
            continue

        sql = query["query"]
        try:
            rewritten_sql, count = rewrite_table_references(sql, old_name, new_name)
            rewritten_sql, namespace_count = rewrite_table_references(
                rewritten_sql, f"models.{old_name}", f"models.{new_name}"
            )
        except Exception:
            raise ValidationError("Could not safely rewrite an endpoint query. No changes were made.") from None
        if count + namespace_count == 0:
            continue

        rewrites.append((version, {**query, "query": rewritten_sql}))

    if not rewrites:
        return 0
    if user_access_control is None:
        raise PermissionDenied("You need edit access to every affected endpoint to rename this view.")

    access_control = cast(UserAccessControl, user_access_control)
    endpoints = {version.endpoint_id: version.endpoint for version, _ in rewrites}
    access_control.preload_object_access_controls(list(endpoints.values()))
    if any(not access_control.check_access_level_for_object(endpoint, "editor") for endpoint in endpoints.values()):
        raise PermissionDenied("You need edit access to every affected endpoint to rename this view.")

    for version, query in rewrites:
        version.query = query
        version.save(update_fields=["query", "updated_at"])

    updated_saved_query_ids: set[str] = set()
    for version, _ in rewrites:
        if version.saved_query is not None and str(version.saved_query_id) not in updated_saved_query_ids:
            from products.endpoints.backend.logic.materialization import prepare_executable_query

            prepare_executable_query(version.saved_query)
            sync_saved_query_to_dag(version.saved_query)
            updated_saved_query_ids.add(str(version.saved_query_id))

    return len(rewrites)
