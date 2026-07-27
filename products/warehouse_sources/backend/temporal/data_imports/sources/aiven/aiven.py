from collections.abc import Callable
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.aiven.settings import (
    AIVEN_ENDPOINTS,
    AivenEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

AIVEN_BASE_URL = "https://api.aiven.io/v1"

# Aiven list endpoints return the whole collection in one JSON response with no pagination params,
# so every resource is a single unpaginated GET.
_SINGLE_PAGE = SinglePagePaginator

# Parent list endpoints each fan-out mode iterates. `field` is the parent row key bound into the
# child path (also injected into child rows so composite primary keys stay unique table-wide).
_PROJECT_PARENT = {"name": "projects", "path": "/project", "data_key": "projects", "field": "project_name"}
_ORG_PARENT = {
    "name": "organizations",
    "path": "/organizations",
    "data_key": "organizations",
    "field": "organization_id",
}


def _auth_header_value(api_token: str) -> str:
    # Aiven expects the literal `aivenv1` prefix before the token, not `Bearer`.
    return f"aivenv1 {api_token}"


def _client_config(api_token: str) -> ClientConfig:
    # The credential travels via framework api_key auth (not a hand-built header) so its value is
    # registered for redaction wherever it surfaces in logs; only non-secret headers go here.
    return {
        "base_url": AIVEN_BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {
            "type": "api_key",
            "api_key": _auth_header_value(api_token),
            "name": "Authorization",
            "location": "header",
        },
    }


def _stamp_parent_field(
    parent_name: str, parent_field: str, target: str, *, overwrite: bool
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Remap the `_{parent}_{field}` key that ``include_from_parent`` lands onto the clean column the
    row carried before the migration. ``overwrite`` mirrors the old injection: parent keys the child
    never has (``project_name``, ``invoice_number``) are set unconditionally; ``organization_id`` is a
    ``setdefault`` so a row that already carries a real org id keeps it.
    """
    source_key = f"_{parent_name}_{parent_field}"

    def _map(row: dict[str, Any]) -> dict[str, Any]:
        value = row.pop(source_key, None)
        if value is None:
            return row
        if overwrite or target not in row:
            row[target] = value
        return row

    return _map


def _standard_resource(config: AivenEndpointConfig, client_config: ClientConfig, team_id: int, job_id: str) -> Resource:
    # A missing/empty/non-list data key yields no rows (the old `_list` returned []); the selector is
    # deliberately non-required so a changed shape degrades to 0 rows rather than failing loud.
    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path_template,
                    "data_selector": config.data_key,
                    "paginator": _SINGLE_PAGE(),
                },
            }
        ],
    }
    return rest_api_resource(rest_config, team_id, job_id, None)


def _single_parent_resource(
    config: AivenEndpointConfig,
    parent: dict[str, str],
    placeholder: str,
    target: str,
    client_config: ClientConfig,
    team_id: int,
    job_id: str,
    *,
    overwrite: bool,
) -> Resource:
    """Fan out one request per parent (project or organization), stamping the parent id into each row."""
    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resources": [
            {
                "name": parent["name"],
                "endpoint": {
                    "path": parent["path"],
                    "data_selector": parent["data_key"],
                    "paginator": _SINGLE_PAGE(),
                },
            },
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path_template,
                    "params": {placeholder: {"type": "resolve", "resource": parent["name"], "field": parent["field"]}},
                    "data_selector": config.data_key,
                    "paginator": _SINGLE_PAGE(),
                },
                "include_from_parent": [parent["field"]],
                "data_map": _stamp_parent_field(parent["name"], parent["field"], target, overwrite=overwrite),
            },
        ],
    }
    resources = rest_api_resources(rest_config, team_id, job_id, None)
    return next(r for r in resources if r.name == config.name)


def _invoice_lines_resource(
    config: AivenEndpointConfig, client_config: ClientConfig, team_id: int, job_id: str
) -> Resource:
    """Two-level fan-out: organization -> invoice -> lines.

    The intermediate invoices resource carries its organization id down (``include_from_parent``) so
    the lines path can bind both ``{organization_id}`` and ``{invoice_number}`` from the same invoice
    row. Line rows get ``organization_id`` (setdefault) and ``invoice_number`` (overwrite) — the exact
    shape the old two-level loop produced.
    """
    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resources": [
            {
                "name": "organizations",
                "endpoint": {
                    "path": _ORG_PARENT["path"],
                    "data_selector": _ORG_PARENT["data_key"],
                    "paginator": _SINGLE_PAGE(),
                },
            },
            {
                "name": "invoices",
                "endpoint": {
                    "path": "/organization/{organization_id}/invoices",
                    "params": {
                        "organization_id": {"type": "resolve", "resource": "organizations", "field": "organization_id"}
                    },
                    "data_selector": "invoices",
                    "paginator": _SINGLE_PAGE(),
                },
                "include_from_parent": ["organization_id"],
                # Land the grandparent org id as a clean column so the lines resource can resolve it.
                "data_map": _stamp_parent_field("organizations", "organization_id", "organization_id", overwrite=True),
            },
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path_template,
                    "params": {
                        "organization_id": {"type": "resolve", "resource": "invoices", "field": "organization_id"},
                        "invoice_number": {"type": "resolve", "resource": "invoices", "field": "invoice_number"},
                    },
                    "data_selector": config.data_key,
                    "paginator": _SINGLE_PAGE(),
                },
                "include_from_parent": ["organization_id", "invoice_number"],
                "data_map": _compose(
                    _stamp_parent_field("invoices", "organization_id", "organization_id", overwrite=False),
                    _stamp_parent_field("invoices", "invoice_number", "invoice_number", overwrite=True),
                ),
            },
        ],
    }
    resources = rest_api_resources(rest_config, team_id, job_id, None)
    return next(r for r in resources if r.name == config.name)


def _compose(
    *maps: Callable[[dict[str, Any]], dict[str, Any]],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _map(row: dict[str, Any]) -> dict[str, Any]:
        for m in maps:
            row = m(row)
        return row

    return _map


def _build_resource(config: AivenEndpointConfig, api_token: str, team_id: int, job_id: str) -> Resource:
    client_config = _client_config(api_token)

    if config.fan_out == "none":
        return _standard_resource(config, client_config, team_id, job_id)
    if config.fan_out == "project":
        return _single_parent_resource(
            config, _PROJECT_PARENT, "project", "project_name", client_config, team_id, job_id, overwrite=True
        )
    if config.fan_out == "organization":
        return _single_parent_resource(
            config,
            _ORG_PARENT,
            "organization_id",
            "organization_id",
            client_config,
            team_id,
            job_id,
            overwrite=False,
        )
    if config.fan_out == "invoice":
        return _invoice_lines_resource(config, client_config, team_id, job_id)

    raise ValueError(f"Unknown fan_out mode: {config.fan_out}")


def aiven_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    config = AIVEN_ENDPOINTS[endpoint]
    resource = _build_resource(config, api_token, team_id, job_id)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_token: str) -> bool:
    """Confirm the token is valid. ``/me`` reflects the token itself and needs no resource scope."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{AIVEN_BASE_URL}/me",
        headers={"Authorization": _auth_header_value(api_token), "Accept": "application/json"},
    )
    return ok
