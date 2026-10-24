from collections.abc import Iterable
from typing import TYPE_CHECKING
from uuid import UUID

from products.endpoints.backend.models import Endpoint, EndpointVersion

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import AccessControlLevel, UserAccessControl


def denied_endpoint_saved_query_ids(
    team_id: int,
    user_access_control: "UserAccessControl",
    required_level: "AccessControlLevel" = "viewer",
    saved_query_ids: Iterable[UUID | str] | None = None,
) -> frozenset[UUID]:
    versions = EndpointVersion.objects.filter(endpoint__team_id=team_id, saved_query_id__isnull=False)
    if saved_query_ids is not None:
        versions = versions.filter(saved_query_id__in=saved_query_ids)
    publications = list(versions.values_list("endpoint_id", "saved_query_id"))
    endpoints = list(Endpoint.objects.filter(team_id=team_id, id__in={row[0] for row in publications}))
    user_access_control.preload_object_access_controls(list(endpoints))
    denied_endpoints = {
        endpoint.id
        for endpoint in endpoints
        if endpoint.deleted or not user_access_control.check_access_level_for_object(endpoint, required_level)
    }
    return frozenset(saved_query_id for endpoint_id, saved_query_id in publications if endpoint_id in denied_endpoints)
