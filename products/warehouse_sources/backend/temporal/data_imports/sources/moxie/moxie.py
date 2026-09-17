"""Moxie transport layer.

Moxie (withmoxie.com) is an all-in-one business-management app for freelancers, hosted on a
per-workspace pod (e.g. `pod00.withmoxie.dev`), so the API base URL is a user-supplied credential
rather than a constant. Auth is a single `X-API-KEY` header
(https://help.withmoxie.com/en/articles/8154735-public-api-fundamentals).

Every list/search endpoint returns the full collection as one bare JSON array with no pagination and
no server-side timestamp filter, so every table here is full refresh only. Two endpoint shapes exist:
most return an array of objects, but `emailTemplates`, `invoiceTemplates`, `vendors`, and `formNames`
return an array of bare strings (template/vendor/form names). The framework's per-item `data_map` only
runs on dict items (see `Resource._apply_transforms`), so those four are wrapped into a one-column row
after the fact in `moxie_source`, not declared as a `data_map` on the resource.

Moxie enforces a hard rate limit of 100 Public API requests per 5-minute window per workspace,
returning HTTP 429 when exceeded; the tracked session's transport-level retry already honors
`Retry-After` on a 429, so no extra throttling is added here.
"""

import re
from typing import Any, Optional
from urllib.parse import urlparse

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.moxie.settings import (
    MOXIE_API_PATH_PREFIX,
    MOXIE_ENDPOINTS,
)

HOST_NOT_ALLOWED_ERROR = "Moxie workspace base URL is not allowed"
HTTP_NOT_ALLOWED_ERROR = "Moxie workspace base URL must use HTTPS"

# (connect, read) timeout: a customer-controlled host that accepts the connection and then never
# responds (or trickles bytes) would otherwise hold an import worker for the activity's full runtime
# budget, since RESTClient passes this straight to `requests` as `timeout=None` when unset.
REQUEST_TIMEOUT_SECONDS = (10.0, 60.0)


class MoxieHostNotAllowedError(Exception):
    pass


def normalize_base_url(base_url: Optional[str]) -> str:
    """Turn whatever the user pasted from Connected Apps > Integrations into a full base URL.

    Accepts a bare pod host (`pod00.withmoxie.dev`) or the full URL shown in Moxie's UI
    (`https://pod00.withmoxie.dev/api/public`), with or without a trailing slash.
    """
    raw = (base_url or "").strip()
    if not raw:
        return ""
    if not re.match(r"^https?://", raw, flags=re.IGNORECASE):
        raw = f"https://{raw}"
    raw = raw.rstrip("/")
    if not re.search(r"/api/public$", raw, flags=re.IGNORECASE):
        raw = f"{raw}/api/public"
    return raw


def _host_of(base_url: str) -> str:
    # `urlparse` treats a backslash (and its `%5c` encoding) as userinfo, so
    # `https://127.0.0.1\@example.com` parses as host `example.com` while requests/urllib3 (per the
    # WHATWG URL rules) treat `\` as a path separator and connect to `127.0.0.1`. Normalize to `/`
    # first so the host we validate is the host the request actually reaches (SSRF bypass guard).
    normalized = base_url.replace("\\", "/").replace("%5c", "/").replace("%5C", "/")
    return (urlparse(normalized).hostname or "").lower()


def _is_https(base_url: str) -> bool:
    # The API key rides in the X-API-KEY header, so refuse plaintext HTTP to keep an on-path
    # attacker from capturing it.
    return urlparse(base_url).scheme == "https"


def _flatten_workspace_user(item: dict[str, Any]) -> dict[str, Any]:
    """Lift the nested `user.userId` onto the row root as `user_id`, the only stable per-row key
    List Workspace Users exposes (a nested field can't be declared as a `SourceResponse` primary key).
    """
    user = item.get("user") or {}
    return {**item, "user_id": user.get("userId")}


def get_resource(endpoint: str) -> EndpointResource:
    config = MOXIE_ENDPOINTS[endpoint]
    resource: EndpointResource = {
        "name": endpoint,
        "write_disposition": "replace",
        "endpoint": {"path": config.path},
        "table_format": "delta",
    }
    if endpoint == "workspace_users":
        resource["data_map"] = _flatten_workspace_user
    return resource


def moxie_source(
    base_url: Optional[str],
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    resolved_base_url = normalize_base_url(base_url)
    host = _host_of(resolved_base_url)
    config = MOXIE_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": resolved_base_url,
            "headers": {"Accept": "application/json"},
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-API-KEY", "location": "header"},
            # No pagination is documented on any endpoint — each table is a single bare-array page.
            "paginator": "single_page",
            # Don't follow redirects: a compromised/edited base_url could 3xx to an internal address,
            # bypassing the host check below (SSRF).
            "allow_redirects": False,
            "request_timeout": REQUEST_TIMEOUT_SECONDS,
        },
        "resource_defaults": None,
        "resources": [get_resource(endpoint)],
    }

    wrap_field = config.wrap_scalar_as

    def items() -> Any:
        # Re-check at run time, not just at source-create: the base_url can be edited later and now
        # resolve to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
        host_ok, host_err = _is_host_safe(host, team_id)
        if not host_ok:
            raise MoxieHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)
        if not _is_https(resolved_base_url):
            raise MoxieHostNotAllowedError(HTTP_NOT_ALLOWED_ERROR)

        for batch in rest_api_resource(rest_config, team_id, job_id, None):
            if wrap_field:
                yield [{wrap_field: value} for value in batch]
            else:
                yield batch

    has_partition_key = config.partition_key is not None
    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        # Full-refresh replace: there's no incremental watermark to checkpoint, but an explicit sort
        # still guards against a page-boundary shuffle on the (single, unpaginated) response.
        sort_mode="asc",
        partition_mode="datetime" if has_partition_key else None,
        partition_format="month" if has_partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(
    base_url: Optional[str], api_key: str, team_id: Optional[int] = None
) -> tuple[bool, str | None]:
    resolved_base_url = normalize_base_url(base_url)
    host = _host_of(resolved_base_url)

    if not host:
        return False, "That doesn't look like a Moxie workspace base URL."

    # The host is fully customer-controlled (per-workspace pod), so block hosts that resolve to
    # private/internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(host, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    if not _is_https(resolved_base_url):
        return False, HTTP_NOT_ALLOWED_ERROR

    # List Clients takes no parameters and needs no scope beyond the API key itself, so it's the
    # cheapest probe available and doubles as the request the `clients` table itself makes.
    url = f"{resolved_base_url}{MOXIE_API_PATH_PREFIX}/clients/list"
    is_valid, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        headers={"X-API-KEY": api_key, "Accept": "application/json"},
        allow_redirects=False,
    )
    if is_valid:
        return True, None
    if status == 401:
        return False, "Moxie rejected the API key. Check the key and workspace base URL, then try again."
    if status == 403:
        return False, "The Moxie API key does not have permission for this workspace."
    return False, "Could not connect to Moxie with the given credentials."
