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
- Return ORM instances or QuerySets

Wiring that core registers crosses the boundary through the dedicated
submodules instead: ``facade.tasks`` (celery beat), ``facade.temporal``
(data-modeling workflow hooks), ``facade.models`` (model-class consumers),
``facade.enums`` (exported constants).

The service surface the product's own presentation consumes (CRUD/execution/
materialization services, request validation, OpenAPI generation) is resolved
lazily via PEP 562 — those modules pull heavy dependencies (HogQL, query
runners) that must stay off the ``django.setup()`` path.
"""

import importlib
from datetime import datetime
from typing import TYPE_CHECKING

from products.endpoints.backend import rate_limit
from products.endpoints.backend.models import Endpoint, EndpointVersion

from . import contracts

if TYPE_CHECKING:
    from products.endpoints.backend.logic.crud import EndpointCrudService
    from products.endpoints.backend.logic.execution import EndpointExecutionService
    from products.endpoints.backend.logic.materialization import (
        EndpointMaterializationService,
        build_materialization_info,
    )
    from products.endpoints.backend.logic.validation import (
        validate_bucket_overrides,
        validate_endpoint_request,
        validate_update_request,
    )
    from products.endpoints.backend.openapi import generate_openapi_spec

# symbol -> source module (relative to products.endpoints.backend)
_LAZY = {
    "EndpointCrudService": "logic.crud",
    "EndpointExecutionService": "logic.execution",
    "EndpointMaterializationService": "logic.materialization",
    "build_materialization_info": "logic.materialization",
    "validate_bucket_overrides": "logic.validation",
    "validate_endpoint_request": "logic.validation",
    "validate_update_request": "logic.validation",
    "generate_openapi_spec": "openapi",
}


def __getattr__(name: str):
    try:
        module_path = _LAZY[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    module = importlib.import_module(f"products.endpoints.backend.{module_path}")
    return getattr(module, name)


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


def get_last_execution_times(team_id: int, names: list[str]) -> list[tuple[str, datetime]]:
    """Most recent execution time per endpoint, for the endpoints that have one."""
    rows = Endpoint.objects.filter(team_id=team_id, name__in=names, last_executed_at__isnull=False).values_list(
        "name", "last_executed_at"
    )
    # The isnull=False filter already excludes None, but mypy can't narrow through queryset filters.
    return [(name, ts) for name, ts in rows if ts is not None]


def is_materialization_ready(team_id: int, endpoint_name: str, version: int | None = None) -> bool:
    """Whether the targeted version (current when ``version`` is None) is ready for materialized execution."""
    return rate_limit.check_materialization_ready(team_id, endpoint_name, version)


__all__ = [
    "EndpointCrudService",
    "EndpointExecutionService",
    "EndpointMaterializationService",
    "build_materialization_info",
    "generate_openapi_spec",
    "get_endpoint",
    "get_endpoint_version",
    "get_last_execution_times",
    "is_materialization_ready",
    "list_endpoints",
    "validate_bucket_overrides",
    "validate_endpoint_request",
    "validate_update_request",
]
