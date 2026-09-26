import re
from collections.abc import Callable
from typing import Any, Optional, cast
from urllib.parse import urlparse

import requests

from posthog.cloud_utils import is_cloud

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
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coolify.settings import (
    COOLIFY_ENDPOINTS,
    DEPLOYMENTS_PAGE_SIZE,
    MAX_DEPLOYMENTS_OFFSET,
    CoolifyEndpointConfig,
)

# Every Coolify endpoint lives under this prefix, on the customer's own instance
# (or https://app.coolify.io for Coolify Cloud).
API_PATH = "/api/v1"

REQUEST_TIMEOUT_SECONDS = 30

HOST_NOT_ALLOWED_ERROR = "This Coolify instance URL is not allowed"


class CoolifyHostNotAllowedError(Exception):
    pass


def normalize_base_url(base_url: str) -> str:
    """Instance root with no trailing slash and no `/api/v1` suffix.

    Users paste the URL from their browser or from the API docs, so both
    `https://coolify.example.com/` and `https://coolify.example.com/api/v1` must resolve to the
    same instance root; the API path is appended once in `api_base_url`.
    """
    url = base_url.strip()
    if url and "://" not in url:
        url = f"https://{url}"
    url = url.rstrip("/")
    if url.endswith(API_PATH):
        url = url.removesuffix(API_PATH)
    return url.rstrip("/")


def api_base_url(base_url: str) -> str:
    return f"{normalize_base_url(base_url)}{API_PATH}"


def _validated_hostname(base_url: str) -> Optional[str]:
    """Hostname of the normalized instance URL, or None when the URL is malformed or ambiguous.

    SSRF guard: urlparse treats a backslash as ordinary userinfo and an "@" as a userinfo
    separator, but urllib3/requests treat the backslash as an authority separator, so
    `https://127.0.0.1\\@example.com` validates as example.com yet connects to 127.0.0.1. A
    legitimate instance URL has no userinfo, so reject either construct outright.
    """
    if "\\" in base_url or "%5c" in base_url.lower():
        return None
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or "@" in parsed.netloc:
        return None
    # The API token rides in a header on every request, so plaintext http would leak it to any
    # network observer once it egresses over the public internet. Self-hosted PostHog operators
    # control their own network path, so http stays allowed there (mirrors Discourse/Flagsmith).
    if parsed.scheme == "http" and is_cloud():
        return None
    hostname = parsed.hostname
    if not hostname or not re.match(r"^[A-Za-z0-9.\-]+$", hostname):
        return None
    return hostname


def hostname_of(base_url: str) -> Optional[str]:
    return _validated_hostname(normalize_base_url(base_url))


def _check_host(base_url: str, team_id: int) -> None:
    hostname = hostname_of(base_url)
    if not hostname:
        raise CoolifyHostNotAllowedError("Invalid Coolify instance URL")
    host_ok, host_err = _is_host_safe(hostname, team_id)
    if not host_ok:
        raise CoolifyHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)


def _deployments_paginator() -> BasePaginator:
    # `/deployments/applications/{uuid}` pages with `skip`/`take` and reports the grand total
    # under `count` (verified against the controller: rows come newest-first, `take` defaults
    # to 10 server-side). `maximum_offset` bounds the walk against a host that misreports
    # `count` or ignores `skip` (see MAX_DEPLOYMENTS_OFFSET).
    return OffsetPaginator(
        limit=DEPLOYMENTS_PAGE_SIZE,
        offset_param="skip",
        limit_param="take",
        total_path="count",
        maximum_offset=MAX_DEPLOYMENTS_OFFSET,
    )


def _client_config(base_url: str, api_token: str, endpoint_config: CoolifyEndpointConfig) -> ClientConfig:
    client_config: ClientConfig = {
        "base_url": api_base_url(base_url),
        "auth": {
            "type": "bearer",
            "token": api_token,
        },
        # The instance URL is customer-supplied: pin every request (including pagination) to the
        # base host and refuse redirects so the credentialed request can't be bounced off-host.
        "allowed_hosts": [],
        "allow_redirects": False,
        # Bound every sync request so a host that accepts the connection then stalls can't hold
        # an import worker indefinitely.
        "request_timeout": REQUEST_TIMEOUT_SECONDS,
    }
    # Sample capture records the raw response before resource maps run, so stripping a field
    # from storage does not keep it out of a sample. The request stays metered, logged, and
    # token-redacted.
    if endpoint_config.sensitive_fields or not endpoint_config.captures_http_samples:
        client_config["capture"] = False
    return client_config


def _get_resource(endpoint_config: CoolifyEndpointConfig) -> EndpointResource:
    return {
        "name": endpoint_config.name,
        "table_name": endpoint_config.name,
        # No server-side timestamp filter exists on any Coolify list endpoint, so we always
        # replace the whole table rather than merge on an incremental cursor.
        "write_disposition": "replace",
        "endpoint": {
            "data_selector": endpoint_config.data_selector,
            "path": endpoint_config.path,
            "paginator": SinglePagePaginator(),
        },
        "table_format": "delta",
    }


def _strip_sensitive_fields(sensitive_fields: frozenset[str]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    # Drop credential-bearing keys from each record before it's stored. Recurses through nested
    # dicts and lists because e.g. database rows nest their type-specific fields. Runs as a
    # resource map, so it's the last thing to touch a record before persistence.
    def _scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: _scrub(item) for key, item in value.items() if key not in sensitive_fields}
        if isinstance(value, list):
            return [_scrub(item) for item in value]
        return value

    def _strip(record: dict[str, Any]) -> dict[str, Any]:
        return _scrub(record)

    return _strip


def _fanout_resource(
    endpoint_config: CoolifyEndpointConfig, client_config: ClientConfig, endpoint: str, team_id: int, job_id: str
) -> Resource:
    fanout = endpoint_config.fanout
    assert fanout is not None

    return cast(
        Resource,
        build_dependent_resource(
            endpoint_configs=COOLIFY_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=fanout,
            client_config=client_config,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra={
                "data_selector": COOLIFY_ENDPOINTS[fanout.parent_name].data_selector,
                "paginator": SinglePagePaginator(),
            },
            # The child paginator is always explicit: the REST framework defaults a path that
            # ends in its resolved id to a single unpaginated entity, which would sync only the
            # newest page of an application's deployments.
            child_endpoint_extra={
                "data_selector": endpoint_config.data_selector,
                "paginator": _deployments_paginator(),
            },
            # Both paginators own their page params (the parent listing takes none at all), so
            # the builder must not add a `limit` of its own.
            page_size_param=None,
        ),
    )


def coolify_source(base_url: str, api_token: str, endpoint: str, team_id: int, job_id: str) -> Resource:
    # Re-checked at sync time (not just at source-create) in case the instance URL was edited
    # or now resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    _check_host(base_url, team_id)

    endpoint_config = COOLIFY_ENDPOINTS[endpoint]
    client_config = _client_config(base_url, api_token, endpoint_config)

    if endpoint_config.fanout is not None:
        resource = _fanout_resource(endpoint_config, client_config, endpoint, team_id, job_id)
    else:
        config: RESTAPIConfig = {
            "client": client_config,
            "resource_defaults": {
                "write_disposition": "replace",
            },
            "resources": [_get_resource(endpoint_config)],
        }
        # No incremental support, so `db_incremental_field_last_value` is always None.
        resource = rest_api_resource(config, team_id, job_id, None)

    if endpoint_config.sensitive_fields:
        resource.add_map(_strip_sensitive_fields(endpoint_config.sensitive_fields))
    return resource


def validate_credentials(
    base_url: str,
    api_token: str,
    team_id: Optional[int] = None,
    schema_name: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """Probe `/teams` to confirm the token is genuine and carries the `read` ability.

    Coolify tokens carry global abilities (`read`, `write`, `deploy`, `read:sensitive`, `root`)
    rather than per-resource scopes, so one probe covers every table: a token that can read
    `/teams` can read everything this source syncs. `schema_name` therefore changes nothing.
    Coolify answers 400 with "Invalid token." for an unrecognized token and 403 when the token
    lacks the `read` ability.
    """
    normalized_base_url = normalize_base_url(base_url)
    hostname = _validated_hostname(normalized_base_url)
    if not hostname:
        return False, "Enter your Coolify instance URL, like https://coolify.example.com"

    # The instance URL is fully customer-controlled, so block hosts that resolve to private/
    # internal addresses (SSRF). Only enforced on cloud.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(hostname, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    # The session never follows redirects: the validated host could 3xx to an internal address,
    # defeating the host check above (SSRF).
    session = make_tracked_session(
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
        redact_values=(api_token,),
        allow_redirects=False,
    )
    try:
        response = session.get(f"{normalized_base_url}{API_PATH}/teams", timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException:
        return False, "Couldn't reach your Coolify instance. Check the URL and try again."

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code == 200:
        return True, None

    if response.status_code in (400, 401):
        return False, (
            "Coolify rejected the API token. Check the token, or create a new one under "
            "Keys & Tokens > API tokens on your Coolify instance."
        )

    if response.status_code == 403:
        return False, (
            "Your API token doesn't have read permission. Create a token with read permission "
            "under Keys & Tokens > API tokens on your Coolify instance."
        )

    return False, f"Coolify returned HTTP {response.status_code}. Wait a moment and try again."
