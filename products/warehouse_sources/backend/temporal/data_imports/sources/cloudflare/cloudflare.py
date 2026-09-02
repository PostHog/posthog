from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.settings import (
    ACCOUNTS_PARENT,
    CLOUDFLARE_ENDPOINTS,
    CURSOR_PAGINATION,
    DNS_ANALYTICS_DIMENSIONS,
    DNS_ANALYTICS_METRICS,
    PAGE_PAGINATION,
    SINGLE_PAGE,
    ZONES_PARENT,
    CloudflareEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.jsonpath_utils import (
    find_values,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

CLOUDFLARE_BASE_URL = "https://api.cloudflare.com/client/v4"
# Cloudflare list pages cap at 50 by default; most endpoints allow more.
PAGE_SIZE = 50
# A token can list zones or accounts (account-level Zone:Read) without holding read
# access on every one of them. Per-parent 403/404s mean "this zone/account is
# inaccessible/gone" — skip it and keep syncing the rest rather than failing the
# whole stream.
FANOUT_SKIP_STATUS_CODES = (403, 404)

# Top-level list each fan-out parent is paginated from, and the path placeholder the
# parent's id is resolved into.
_PARENT_PATHS = {ZONES_PARENT: "/zones", ACCOUNTS_PARENT: "/accounts"}
_PARENT_RESOLVE_PARAMS = {ZONES_PARENT: "zone_id", ACCOUNTS_PARENT: "account_id"}


class CloudflarePaginator(PageNumberPaginator):
    """Cloudflare page-number pagination: stop via ``result_info.total_pages``,
    with a short-page fallback for responses that omit it."""

    def __init__(self) -> None:
        super().__init__(base_page=1, page_param="page", total_path="result_info.total_pages")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not self._has_next_page or not data:
            return
        try:
            values = find_values(self.total_path, response.json())
        except Exception:
            values = []
        total_pages = values[0] if values else None
        # Without a total-pages hint, a short page is the last one — stop rather
        # than paying an extra empty-page request.
        if total_pages is None and len(data) < PAGE_SIZE:
            self._has_next_page = False


def _to_rfc3339(value: Any) -> Optional[str]:
    """Coerce an incremental watermark to the RFC 3339 date-time Cloudflare's `since`
    filter documents. Watermarks arrive as datetimes, dates, or already-formatted
    strings depending on how the pipeline stored them."""
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return moment.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return f"{value.isoformat()}T00:00:00Z"
    return str(value)


def _flatten_dns_analytics_row(row: dict[str, Any]) -> dict[str, Any]:
    """The DNS analytics report returns positional `dimensions`/`metrics` arrays that
    line up with the names we requested, so name them into their own columns."""
    flattened = {key: value for key, value in row.items() if key not in ("dimensions", "metrics")}
    flattened.update(zip(DNS_ANALYTICS_DIMENSIONS, row.get("dimensions") or []))
    flattened.update(zip(DNS_ANALYTICS_METRICS, row.get("metrics") or []))
    return flattened


# A logpush job's `destination_conf` is a URI whose query string can carry the
# credentials a Cloudflare admin configured for the sink — an S3-compatible
# `secret-access-key`, or auth tokens passed as `header_*` params on HTTP sinks.
# Redact those values so a warehouse reader can't recover secrets they were never
# granted, while keeping the destination shape (scheme, bucket, region) legible.
def _is_secret_logpush_param(key: str) -> bool:
    lowered = key.lower()
    return lowered in ("secret-access-key", "access-key-id") or lowered.startswith("header_")


def _redact_logpush_destination(row: dict[str, Any]) -> dict[str, Any]:
    conf = row.get("destination_conf")
    if not isinstance(conf, str):
        return row
    split = urlsplit(conf)
    if not split.query:
        return row
    params = parse_qsl(split.query, keep_blank_values=True)
    if not any(_is_secret_logpush_param(key) for key, _ in params):
        return row
    redacted = [(key, "REDACTED" if _is_secret_logpush_param(key) else value) for key, value in params]
    row["destination_conf"] = urlunsplit(split._replace(query=urlencode(redacted)))
    return row


def _redact_scim_authentication(auth: Any) -> Any:
    """An Access app's SCIM `authentication` block holds the credentials Cloudflare
    uses to push to the customer's SCIM endpoint (basic user/password, a bearer
    token, or an OAuth client secret). Keep only the non-secret `scheme` and redact
    everything else, so a warehouse reader can't recover them."""
    if isinstance(auth, list):
        return [_redact_scim_authentication(item) for item in auth]
    if isinstance(auth, dict):
        return {key: (value if key.lower() == "scheme" else "REDACTED") for key, value in auth.items()}
    return auth


# Keys inside an Access app's `saas_app` block that hold an OIDC client secret.
_SAAS_APP_SECRET_KEYS = frozenset({"client_secret", "secret"})


def _redact_access_app(row: dict[str, Any]) -> dict[str, Any]:
    scim = row.get("scim_config")
    if isinstance(scim, dict) and "authentication" in scim:
        row["scim_config"] = {**scim, "authentication": _redact_scim_authentication(scim["authentication"])}
    saas = row.get("saas_app")
    if isinstance(saas, dict):
        row["saas_app"] = {
            key: ("REDACTED" if key.lower() in _SAAS_APP_SECRET_KEYS else value) for key, value in saas.items()
        }
    return row


def _redact_header_values(value: Any) -> Any:
    if isinstance(value, list):
        return ["REDACTED" for _ in value]
    return "REDACTED"


def _redact_healthcheck(row: dict[str, Any]) -> dict[str, Any]:
    """A health check's `http_config.header` map is user-configured request headers
    that can carry an `Authorization` (or other auth) header. Redact the values while
    keeping the header names, so the check's shape stays legible without leaking secrets."""
    http_config = row.get("http_config")
    if not isinstance(http_config, dict):
        return row
    header = http_config.get("header")
    if not isinstance(header, dict):
        return row
    row["http_config"] = {
        **http_config,
        "header": {name: _redact_header_values(value) for name, value in header.items()},
    }
    return row


def _redact_custom_hostname(row: dict[str, Any]) -> dict[str, Any]:
    """A custom hostname's `ssl` object echoes back the private key uploaded for a
    custom certificate under `custom_key`. Drop it so a warehouse reader can't lift
    the key and impersonate the hostname; the rest of the SSL metadata is safe."""
    ssl = row.get("ssl")
    if isinstance(ssl, dict) and "custom_key" in ssl:
        row["ssl"] = {key: value for key, value in ssl.items() if key != "custom_key"}
    return row


_DATA_MAPS = {
    "dns_analytics_report": _flatten_dns_analytics_row,
    "logpush_jobs": _redact_logpush_destination,
    "access_apps": _redact_access_app,
    "healthchecks": _redact_healthcheck,
    "custom_hostnames": _redact_custom_hostname,
}


def _client_config(api_token: str) -> ClientConfig:
    return {
        "base_url": CLOUDFLARE_BASE_URL,
        "auth": {"type": "bearer", "token": api_token},
        "paginator": CloudflarePaginator(),
    }


def _paginator(config: CloudflareEndpointConfig) -> BasePaginator:
    if config.pagination == SINGLE_PAGE:
        return SinglePagePaginator()
    if config.pagination == CURSOR_PAGINATION:
        assert config.cursor_path is not None, (
            f"Cursor-paginated endpoint '{config.name}' must define cursor_path in CLOUDFLARE_ENDPOINTS"
        )
        return JSONResponseCursorPaginator(cursor_path=config.cursor_path, cursor_param="cursor")
    return CloudflarePaginator()


def _params(config: CloudflareEndpointConfig) -> dict[str, Any]:
    params: dict[str, Any] = dict(config.params)
    if config.pagination in (PAGE_PAGINATION, CURSOR_PAGINATION):
        params["per_page"] = PAGE_SIZE
    return params


def _endpoint(
    config: CloudflareEndpointConfig,
    params: dict[str, Any],
    should_use_incremental_field: bool,
) -> Endpoint:
    endpoint: Endpoint = {
        "path": config.path,
        "params": params,
        "data_selector": config.data_selector,
        "paginator": _paginator(config),
    }
    if should_use_incremental_field and config.incremental_param is not None:
        endpoint["incremental"] = {"start_param": config.incremental_param, "convert": _to_rfc3339}
    return endpoint


def _list_resource(name: str, path: str) -> EndpointResource:
    return {
        "name": name,
        "endpoint": {
            "path": path,
            "params": {"per_page": PAGE_SIZE},
            "data_selector": "result",
        },
    }


def _resource(endpoint: str, endpoint_config: Endpoint) -> EndpointResource:
    resource: EndpointResource = {"name": endpoint, "endpoint": endpoint_config}
    data_map = _DATA_MAPS.get(endpoint)
    if data_map is not None:
        resource["data_map"] = data_map
    return resource


def _flat_resource(
    api_token: str, endpoint: str, config: CloudflareEndpointConfig, team_id: int, job_id: str
) -> Resource:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token),
        "resource_defaults": {},
        "resources": [_resource(endpoint, _endpoint(config, _params(config), False))],
    }
    return rest_api_resource(rest_config, team_id, job_id, None)


def _fanout_resource(
    api_token: str,
    endpoint: str,
    config: CloudflareEndpointConfig,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> Resource:
    assert config.parent is not None and config.parent_key is not None, (
        f"Fan-out endpoint '{endpoint}' must define parent and parent_key in CLOUDFLARE_ENDPOINTS"
    )
    parent = config.parent
    parent_key = config.parent_key
    resolve_param = _PARENT_RESOLVE_PARAMS[parent]

    params = _params(config)
    params[resolve_param] = {"type": "resolve", "resource": parent, "field": "id"}

    child_endpoint = _endpoint(config, params, should_use_incremental_field)
    child_endpoint["response_actions"] = [
        {"status_code": status, "action": "ignore"}
        for status in (*FANOUT_SKIP_STATUS_CODES, *config.extra_skip_status_codes)
    ]

    child = _resource(endpoint, child_endpoint)
    child["include_from_parent"] = ["id"]

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token),
        "resource_defaults": {},
        "resources": [_list_resource(parent, _PARENT_PATHS[parent]), child],
    }
    resources = {r.name: r for r in rest_api_resources(rest_config, team_id, job_id, db_incremental_field_last_value)}
    # A parent row without an id can't be fanned out — skip it rather than failing the stream.
    resources[parent].add_filter(lambda row: bool(row.get("id")))

    injected_key = f"_{parent}_id"

    def _rename_parent_key(row: dict[str, Any]) -> dict[str, Any]:
        if injected_key in row:
            row[parent_key] = row.pop(injected_key)
        return row

    return resources[endpoint].add_map(_rename_parent_key)


def validate_credentials(api_token: str) -> tuple[bool, int | None]:
    """Confirm the API token is valid with Cloudflare's token verify endpoint.

    Returns ``(is_valid, status_code)``. ``status_code`` is ``None`` when Cloudflare was
    unreachable so the caller can tell a rejected token apart from a transient failure and
    avoid telling the user their token is invalid when it may be fine.
    """
    try:
        response = make_tracked_session(redact_values=(api_token,)).get(
            f"{CLOUDFLARE_BASE_URL}/user/tokens/verify",
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=10,
        )
    except Exception:
        return False, None
    try:
        is_valid = response.status_code == 200 and bool(response.json().get("success"))
    except Exception:
        is_valid = False
    return is_valid, response.status_code


def cloudflare_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CLOUDFLARE_ENDPOINTS[endpoint]

    if config.parent is not None:
        resource = _fanout_resource(
            api_token,
            endpoint,
            config,
            team_id,
            job_id,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    else:
        resource = _flat_resource(api_token, endpoint, config, team_id, job_id)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=list(config.primary_keys),
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )
