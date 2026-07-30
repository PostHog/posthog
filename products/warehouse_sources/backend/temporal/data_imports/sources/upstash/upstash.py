from collections.abc import Callable
from typing import Any

from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.upstash.settings import (
    UPSTASH_API_BASE_URL,
    UPSTASH_ENDPOINTS,
    UpstashEndpointConfig,
)

# Internal parent resource that lists every Redis database id, used to drive the per-database stats
# fan-out. Named distinctly from the public `redis_databases` endpoint so the two never collide.
_DATABASES_PARENT = "redis_databases_parent"


def validate_credentials(email: str, api_key: str) -> tuple[bool, str | None]:
    """Confirm the email + management API key are genuine via GET /v2/teams.

    /v2/teams is the cheapest authenticated probe available to any native Upstash account regardless
    of which resources exist, and it needs no path parameters. Only a definitive 401/403 rejects the
    credentials; a 429, a 5xx, or an unreachable API is transient and must not block source creation,
    since the same statuses are retried during the sync itself and a genuine auth failure still
    surfaces at sync time via get_non_retryable_errors().
    """
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{UPSTASH_API_BASE_URL}/teams",
        auth=HTTPBasicAuth(email, api_key),
    )
    if status in (401, 403):
        return False, "Invalid Upstash email or management API key"
    return True, None


def _strip_sensitive(sensitive_fields: frozenset[str]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Drop credential-bearing fields (e.g. vector index tokens) before a row reaches the warehouse."""

    def _map(row: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in row.items() if key not in sensitive_fields}

    return _map


def _build_client(email: str, api_key: str, config: UpstashEndpointConfig) -> ClientConfig:
    client: ClientConfig = {
        "base_url": config.base_url,
        # Framework auth so the credential is redacted from logs and raised error messages; only the
        # base64 Authorization header carries it, never the URL.
        "auth": {"type": "http_basic", "username": email, "password": api_key},
        # Endpoints whose responses carry secrets are kept out of HTTP sample capture (the generic
        # scrubber does not redact fields named `token`). One session is reused across the requests.
        "session": make_tracked_session(capture=not bool(config.sensitive_fields), redact_values=(api_key,)),
    }
    return client


def _list_source(
    endpoint: str, config: UpstashEndpointConfig, client: ClientConfig, team_id: int, job_id: str
) -> Resource:
    """A single-request endpoint that returns a bare JSON array of rows."""
    rest_config: RESTAPIConfig = {
        "client": client,
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "paginator": SinglePagePaginator(),
                    # A non-list body is a hard error, not an empty result: silently yielding nothing
                    # would replace the warehouse table with zero rows on an API-shape mismatch or a
                    # transient proxy body, hiding the failure instead of surfacing it.
                    "data_selector_required": True,
                },
            }
        ],
    }
    resource = rest_api_resource(rest_config, team_id, job_id, db_incremental_field_last_value=None)
    if config.sensitive_fields:
        resource.add_map(_strip_sensitive(config.sensitive_fields))
    return resource


def _fan_out_source(
    endpoint: str, config: UpstashEndpointConfig, client: ClientConfig, team_id: int, job_id: str
) -> Resource:
    """Fan out the per-database stats endpoint over every Redis database id.

    The stats object itself carries no id, so the parent database_id is injected into each stats row
    to make the primary key unique table-wide. A database deleted between enumeration and its stats
    fetch 404s; skip it rather than failing the whole sync.
    """
    rest_config: RESTAPIConfig = {
        "client": client,
        "resource_defaults": {},
        "resources": [
            {
                "name": _DATABASES_PARENT,
                "endpoint": {
                    "path": "/redis/databases",
                    "paginator": SinglePagePaginator(),
                    "data_selector_required": True,
                },
            },
            {
                "name": endpoint,
                # Stamp the parent id onto each stats row (renamed to a bare `database_id` below).
                "include_from_parent": ["database_id"],
                "endpoint": {
                    # config.path is "/redis/stats/{database_id}" — a single-entity path, so the
                    # framework auto-selects the whole body ("$") as the one stats row per database.
                    "path": config.path,
                    "params": {
                        "database_id": {"type": "resolve", "resource": _DATABASES_PARENT, "field": "database_id"},
                    },
                    # A database removed between enumeration and its stats fetch 404s: skip it. Any
                    # other error status still fails loud via the framework's default raise_for_status.
                    "response_actions": [{"status_code": 404, "action": "ignore"}],
                },
            },
        ],
    }
    resources = rest_api_resources(rest_config, team_id, job_id, db_incremental_field_last_value=None)
    child = next(resource for resource in resources if resource.name == endpoint)
    # include_from_parent stamps the id under `_<parent>_database_id`; rename it to the bare
    # `database_id` the row (and its primary key) expects, reproducing `{**stats, "database_id": id}`.
    child.add_map(rename_parent_fields(_DATABASES_PARENT, {"database_id": "database_id"}))
    return child


def upstash_source(
    email: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    config = UPSTASH_ENDPOINTS[endpoint]
    client = _build_client(email, api_key, config)

    if config.fan_out_over_databases:
        resource = _fan_out_source(endpoint, config, client, team_id, job_id)
    else:
        resource = _list_source(endpoint, config, client, team_id, job_id)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # Full refresh with no server-side ordering guarantee; asc is the pipeline default and the
        # tables are replaced wholesale each sync, so no incremental watermark depends on the order.
        sort_mode="asc",
    )
