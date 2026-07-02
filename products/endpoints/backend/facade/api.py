"""
Facade API for endpoints.

This is the ONLY module (with its facade siblings) other apps are allowed
to import.

Responsibilities:
- Call internal logic and models
- Convert Django models to contracts before returning
- Remain thin and stable

Do NOT:
- Implement business logic here
- Import DRF, serializers, or HTTP concerns
- Return ORM instances or QuerySets

Wiring that core registers crosses the boundary through the dedicated
submodules instead: ``facade.tasks`` (celery beat), ``facade.temporal``
(data-modeling workflow hooks), ``facade.models`` (model-class consumers).
"""

from products.endpoints.backend.models import Endpoint, EndpointVersion

from . import contracts


def _to_endpoint_info(endpoint: Endpoint) -> contracts.EndpointInfo:
    return contracts.EndpointInfo(
        id=endpoint.id,
        team_id=endpoint.team_id,
        name=endpoint.name,
        is_active=endpoint.is_active,
        current_version=endpoint.current_version,
        derived_from_insight=endpoint.derived_from_insight,
        created_at=endpoint.created_at,
        updated_at=endpoint.updated_at,
        last_executed_at=endpoint.last_executed_at,
    )


def _to_version_info(version: EndpointVersion) -> contracts.EndpointVersionInfo:
    return contracts.EndpointVersionInfo(
        id=version.id,
        endpoint_id=version.endpoint_id,
        version=version.version,
        query=version.query,
        description=version.description,
        data_freshness_seconds=version.data_freshness_seconds,
        is_active=version.is_active,
        is_materialized=version.is_materialized,
        created_at=version.created_at,
        last_executed_at=version.last_executed_at,
    )


def list_endpoints(team_id: int) -> list[contracts.EndpointInfo]:
    endpoints = Endpoint.objects.filter(team_id=team_id, deleted=False).order_by("name")
    return [_to_endpoint_info(e) for e in endpoints]


def get_endpoint(team_id: int, name: str) -> contracts.EndpointInfo | None:
    endpoint = Endpoint.objects.filter(team_id=team_id, name=name, deleted=False).first()
    return _to_endpoint_info(endpoint) if endpoint is not None else None


def get_endpoint_version(team_id: int, name: str, version: int | None = None) -> contracts.EndpointVersionInfo | None:
    """Get a specific version's snapshot, or the current version when ``version`` is None."""
    endpoint = Endpoint.objects.filter(team_id=team_id, name=name, deleted=False).first()
    if endpoint is None:
        return None
    try:
        return _to_version_info(endpoint.get_version(version))
    except EndpointVersion.DoesNotExist:
        return None
