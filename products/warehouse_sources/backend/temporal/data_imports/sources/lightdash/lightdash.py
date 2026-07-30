import re
from collections.abc import Callable, Iterable
from typing import Any, Optional, cast
from urllib.parse import urlparse

import requests

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightdash.settings import (
    LIGHTDASH_ENDPOINTS,
    LightdashEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60

HOST_NOT_ALLOWED_ERROR = "Lightdash instance URL is not allowed"

# The full-collection response envelope every Lightdash list endpoint shares:
# {"status": "ok", "results": [...] | {"data": [...], "pagination": {...}}}.
_PAGINATED_TOTAL_PATH = "results.pagination.totalPageCount"

# Loopback hosts where plaintext HTTP carries no network-exposure risk (local dev / self-hosted on
# the same box). Every other host is forced to HTTPS so the personal access token never travels in
# cleartext.
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}

# Lightdash instance hostnames are a plain DNS name or IP (with optional port) — anything else
# (path, query, userinfo) could disagree with what the HTTP client actually connects to.
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9.\-]+(?::\d+)?$")


class LightdashHostNotAllowedError(Exception):
    pass


def normalize_host(instance_url: str) -> str:
    """Turn whatever the user typed into a bare instance base URL (scheme + host, no path).

    Accepts ``https://app.lightdash.cloud``, ``app.lightdash.cloud``, and
    ``https://app.lightdash.cloud/api/v1`` and returns ``https://app.lightdash.cloud``. Forces
    https for any non-loopback host so the personal access token is never sent over the network
    in cleartext.
    """
    host = instance_url.strip()
    if not re.match(r"^https?://", host, flags=re.IGNORECASE):
        host = f"https://{host}"
    parsed = urlparse(host)
    scheme = parsed.scheme.lower()
    if scheme == "http" and (parsed.hostname or "").lower() not in LOOPBACK_HOSTS:
        scheme = "https"
    return f"{scheme}://{parsed.netloc}"


def _hostname(instance_url: str) -> str:
    return (urlparse(normalize_host(instance_url)).hostname or "").lower()


def _client_config(base_url: str, api_token: str) -> ClientConfig:
    return {
        "base_url": base_url,
        "headers": {"Accept": "application/json"},
        # Lightdash personal access tokens authenticate via `Authorization: ApiKey <token>` —
        # a fixed scheme, not the framework's built-in "bearer" (`Bearer <token>`).
        "auth": {"type": "api_key", "name": "Authorization", "api_key": f"ApiKey {api_token}", "location": "header"},
        # The host is customer-controlled (self-hosted Lightdash); refusing redirects closes the
        # redirect-based off-host escape that the host check alone would miss.
        "allow_redirects": False,
        # Bound every sync request so a host that accepts the connection then stalls can't hold an
        # import worker indefinitely (the credential probe in validate_credentials is already
        # bounded separately).
        "request_timeout": REQUEST_TIMEOUT_SECONDS,
    }


def validate_credentials(
    instance_url: str, api_token: str, team_id: Optional[int] = None, schema_name: Optional[str] = None
) -> tuple[bool, str | None]:
    """Confirm the credentials are genuine with a cheap ``GET /api/v1/user`` probe.

    ``schema_name`` is unused (a personal access token grants the same access everywhere; there
    are no per-endpoint OAuth scopes to probe) but kept for the base-class signature. The instance
    URL is customer-controlled, so block internal/private addresses (SSRF, cloud only) and refuse
    to follow redirects.
    """
    hostname = _hostname(instance_url)
    if not hostname or not _HOSTNAME_RE.match(hostname):
        return False, "Invalid Lightdash instance URL"

    if team_id is not None:
        host_ok, host_err = _is_host_safe(hostname, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    base_url = normalize_host(instance_url)
    session = make_tracked_session(redact_values=(api_token,))
    try:
        response = session.get(
            f"{base_url}/api/v1/user",
            headers={"Authorization": f"ApiKey {api_token}", "Accept": "application/json"},
            timeout=10,
            allow_redirects=False,
        )
    except requests.exceptions.RequestException as e:
        return False, f"Could not reach the Lightdash instance: {e}"

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR
    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Lightdash rejected the personal access token. Generate a new token and reconnect."
    if response.status_code == 403:
        # A personal access token grants the same access as its owning user everywhere, so a 403
        # here means the user itself lacks access rather than a missing scope — still let source
        # creation through and surface it per-table via the sync-time non-retryable error.
        if schema_name is None:
            return True, None
        return False, "Your Lightdash personal access token does not have access to this resource."
    return False, f"Lightdash returned an unexpected response (HTTP {response.status_code})."


def _paginator(config: LightdashEndpointConfig) -> BasePaginator:
    if not config.paginated:
        return SinglePagePaginator()
    return PageNumberPaginator(base_page=1, page_param="page", total_path=_PAGINATED_TOTAL_PATH)


def get_resource(config: LightdashEndpointConfig) -> EndpointResource:
    if config.fanout:
        raise ValueError(f"Fan-out endpoint '{config.name}' must use the fan-out path")

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": {"pageSize": config.page_size} if config.paginated else {},
        "data_selector": config.data_selector,
        "paginator": _paginator(config),
    }
    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def _make_source_response(config: LightdashEndpointConfig, items_fn: Callable[[], Any]) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items_fn,
        primary_keys=config.primary_key if isinstance(config.primary_key, list) else [config.primary_key],
        # Full refresh only — Lightdash exposes no server-side updated-since filter on any endpoint.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def lightdash_source(
    instance_url: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    config = LIGHTDASH_ENDPOINTS[endpoint]
    base_url = normalize_host(instance_url)

    # Re-check at run time (not just source-create) in case the instance URL was edited or now
    # resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(_hostname(instance_url), team_id)
    if not host_ok:
        raise LightdashHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

    client_config = _client_config(base_url, api_token)

    if config.fanout is not None:
        dependent_resource = cast(
            Iterable[Any],
            build_dependent_resource(
                endpoint_configs=LIGHTDASH_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=config.fanout,
                client_config=client_config,
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=None,
                # `GET /api/v1/org/projects` (the parent) takes no page-size param at all — it
                # always returns the full collection — so no size param is added to it. Only
                # metrics_catalog's child request needs one, added below via child_params_extra.
                page_size_param=None,
                parent_endpoint_extra={
                    "paginator": SinglePagePaginator(),
                    "data_selector": "results",
                },
                child_endpoint_extra={
                    "paginator": _paginator(config),
                    "data_selector": config.data_selector,
                },
                child_params_extra={"pageSize": config.page_size} if config.paginated else None,
            ),
        )
        return _make_source_response(config, lambda: dependent_resource)

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {"write_disposition": "replace"},
        "resources": [get_resource(config)],
    }
    resource = rest_api_resource(rest_config, team_id, job_id, None)
    return _make_source_response(config, lambda: resource)
