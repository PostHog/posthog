import dataclasses
from typing import Any, Optional, cast

from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    EndpointResource,
    JSONResponseCursorPaginator,
    Resource,
    RESTAPIConfig,
    SinglePagePaginator,
    build_dependent_resource,
    make_tracked_session,
    rest_api_resource,
)
from products.warehouse_sources.sources.vultr.settings import ENDPOINTS, VultrEndpointConfig

VULTR_BASE_URL = "https://api.vultr.com"

# Vultr list objects embed live credentials for the resource they describe: instance and bare-metal
# objects carry `default_password`, and managed-database objects carry the admin `password` plus, for
# Kafka, `access_key`/`access_cert` (sometimes nested under credential sub-objects). Persisting these
# to warehouse tables would expose customer server and database credentials to any project member who
# can query the table, so we strip them from every row (at any depth) before it is yielded, and we
# disable HTTP sample capture for the source so raw responses never land in captured samples either.
SECRET_FIELD_NAMES: frozenset[str] = frozenset({"default_password", "password", "access_key", "access_cert", "api_key"})


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_value(sub) for key, sub in value.items() if key not in SECRET_FIELD_NAMES}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def _redact_secrets(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _redact_value(value) for key, value in row.items() if key not in SECRET_FIELD_NAMES}


def _cursor_paginator() -> JSONResponseCursorPaginator:
    # Vultr paginates via a body cursor at meta.links.next, replayed as the `cursor` query param.
    # The final page returns an empty string, which the paginator treats as "no next page".
    return JSONResponseCursorPaginator(cursor_path="meta.links.next", cursor_param="cursor")


def _list_params(config: VultrEndpointConfig) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": config.page_size} if config.paginated else {}
    params.update(config.params)
    return params


def get_resource(endpoint: str) -> EndpointResource:
    config = ENDPOINTS[endpoint]
    return {
        "name": config.name,
        "table_name": config.name,
        # No server-side time filter exists on any Vultr list endpoint, so we always full-refresh.
        "write_disposition": "replace",
        "endpoint": {
            "data_selector": config.data_selector,
            "path": config.path,
            "params": _list_params(config),
        },
        "table_format": "delta",
    }


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": VULTR_BASE_URL,
        "auth": {"type": "bearer", "token": api_key},
        "paginator": _cursor_paginator(),
        # Responses carry live server/database credentials the name-based sample scrubbers don't
        # cover, so we opt the whole source out of HTTP sample capture. `redact_values` keeps the
        # bearer token masked in logs (a pre-built session skips RESTClient's auth-value default).
        "session": make_tracked_session(redact_values=(api_key,), capture=False),
    }


class _InvoiceLineNumberer:
    """Numbers invoice line items 1, 2, 3, ... per invoice, across pages, in response order."""

    def __init__(self) -> None:
        self._counts: dict[Any, int] = {}

    def __call__(self, row: dict[str, Any]) -> dict[str, Any]:
        invoice_id = row["invoice_id"]
        self._counts[invoice_id] = self._counts.get(invoice_id, 0) + 1
        row["line_number"] = self._counts[invoice_id]
        return row


def _explode_bandwidth(row: dict[str, Any]) -> list[dict[str, Any]]:
    # One response row is {"<YYYY-MM-DD>": {"incoming_bytes": ..., "outgoing_bytes": ...}, ...}.
    instance_id = row["instance_id"]
    return [
        {"instance_id": instance_id, "date": date, **usage}
        for date, usage in row.items()
        if date != "instance_id" and isinstance(usage, dict)
    ]


def _fanout_resource(api_key: str, config: VultrEndpointConfig, team_id: int, job_id: str) -> Resource:
    assert config.fanout is not None
    parent_config = ENDPOINTS[config.fanout.parent_name]
    child_paginator = _cursor_paginator() if config.paginated else SinglePagePaginator()
    resource = cast(
        Resource,
        build_dependent_resource(
            endpoint_configs=ENDPOINTS,
            child_endpoint=config.name,
            fanout=dataclasses.replace(
                config.fanout, parent_params=_list_params(parent_config), child_params=_list_params(config)
            ),
            client_config=_client_config(api_key),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            # Page sizes ride parent_params and child_params, because the bandwidth child takes none.
            page_size_param=None,
            parent_endpoint_extra={"data_selector": parent_config.data_selector},
            child_endpoint_extra={"data_selector": config.data_selector, "paginator": child_paginator},
        ),
    )
    if config.name == "invoice_items":
        return resource.add_map(_InvoiceLineNumberer())
    if config.name == "instance_bandwidth":
        return resource.add_map(_explode_bandwidth)
    return resource


def vultr_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> Resource:
    endpoint_config = ENDPOINTS[endpoint]
    if endpoint_config.fanout is not None:
        resource = _fanout_resource(api_key, endpoint_config, team_id, job_id)
    else:
        config: RESTAPIConfig = {
            "client": _client_config(api_key),
            "resource_defaults": {"write_disposition": "replace"},
            "resources": [get_resource(endpoint)],
        }
        resource = rest_api_resource(config, team_id, job_id, db_incremental_field_last_value=None)
    # Strip embedded credentials before rows reach the warehouse table.
    return resource.add_map(_redact_secrets)


VULTR_IP_BLOCK_ERROR = (
    "Your Vultr API key is being blocked. Check the API key's IP access control list in the Vultr customer portal."
)


def _probe(api_key: str, path: str, params: Optional[dict[str, Any]] = None) -> tuple[Optional[int], Optional[str]]:
    """GET a Vultr endpoint, returning (status_code, error). error is set only on transport failure."""
    try:
        response = make_tracked_session().get(
            f"{VULTR_BASE_URL}{path}",
            headers={"Authorization": f"Bearer {api_key}"},
            params=params,
            timeout=30,
        )
    except Exception as e:
        return None, str(e)
    return response.status_code, None


def validate_credentials(api_key: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    """Probe the account endpoint to confirm the API key is genuine.

    A single Vultr API key grants full account access (no per-product scoping), so a 403 is almost
    always the portal's IP access-control list blocking our egress IPs — in which case every request
    (validation and sync alike) is refused and the source would never sync. The one legitimate
    exception is a sub-user token whose ACL excludes the account endpoint but still permits the data
    endpoints. So on a create-time 403 we probe a real data endpoint (`/v2/instances`): if that also
    403s, the token cannot read anything from our IPs and we reject it now rather than saving a
    source that silently fails every run; if it succeeds, the token is a usable sub-user token and we
    accept it. Sync-time 403s remain surfaced by `get_non_retryable_errors`.
    """
    status, error = _probe(api_key, "/v2/account")
    if error is not None:
        return False, error

    if status == 200:
        return True, None
    if status == 401:
        return False, "Invalid Vultr API key. Generate a new key in the Vultr customer portal and try again."
    if status == 403:
        if schema_name is None:
            data_status, data_error = _probe(api_key, "/v2/instances", params={"per_page": 1})
            if data_error is None and data_status == 200:
                return True, None
        return False, VULTR_IP_BLOCK_ERROR
    return False, f"Unexpected response from Vultr (HTTP {status})."
