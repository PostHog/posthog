import re
import json
import time
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.workday.settings import (
    DEFAULT_PAGE_SIZE,
    WORKDAY_ENDPOINTS,
    build_endpoint_path,
)

HOST_NOT_ALLOWED_ERROR = "Workday hostname is not allowed"
TOKEN_ERROR = "Workday rejected the API client credentials"

_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9.\-]+$")
# Workday tenant names are lowercase alphanumerics with underscores/hyphens (e.g. `acme_pt1`).
_TENANT_RE = re.compile(r"^[A-Za-z0-9_\-]+$")

# (connect, read). Workday tenants are customer-controlled hosts, so an unbounded read would
# pin an import worker on a stalled tenant forever.
REQUEST_TIMEOUT: tuple[float, float] = (10.0, 120.0)
VALIDATE_TIMEOUT = 15

# The tenant host is customer-controlled, so a validation body must never be buffered unbounded:
# requests reads the whole response into memory by default, and the read timeout only guards idle
# gaps between reads, not a steady large transfer. A token/probe body is a few KB, so this cap is
# generous for anything real while refusing an exhaustion attempt outright.
MAX_VALIDATE_RESPONSE_BYTES = 8 * 1024 * 1024
RESPONSE_CHUNK_BYTES = 256 * 1024
# Wall-clock budget for reading one validation body — the per-read timeout can't stop a host that
# dribbles bytes slowly enough to stay under it while holding a worker open.
MAX_VALIDATE_DOWNLOAD_SECONDS = 30

RESPONSE_TOO_LARGE_ERROR = "The Workday token endpoint returned an oversized response"
RESPONSE_TOO_SLOW_ERROR = "The Workday token endpoint response was too slow"


class WorkdayHostNotAllowedError(Exception):
    pass


class WorkdayAuthError(Exception):
    pass


def _read_capped_body(response: requests.Response) -> bytes:
    """Stream a validation body into memory, aborting past the byte or time cap.

    The host is customer-controlled, so the body must never be buffered unbounded (size cap) nor be
    allowed to hold the worker open by dribbling under the per-read timeout (time cap). Raises
    `WorkdayAuthError` on either — re-fetching the same request yields the same oversized/slow body.
    """
    chunks: list[bytes] = []
    total = 0
    deadline = time.monotonic() + MAX_VALIDATE_DOWNLOAD_SECONDS
    try:
        for chunk in response.iter_content(chunk_size=RESPONSE_CHUNK_BYTES):
            if time.monotonic() > deadline:
                raise WorkdayAuthError(f"{RESPONSE_TOO_SLOW_ERROR} (over {MAX_VALIDATE_DOWNLOAD_SECONDS}s)")
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_VALIDATE_RESPONSE_BYTES:
                raise WorkdayAuthError(f"{RESPONSE_TOO_LARGE_ERROR} (over {MAX_VALIDATE_RESPONSE_BYTES} bytes)")
            chunks.append(chunk)
    finally:
        response.close()
    return b"".join(chunks)


@dataclasses.dataclass
class WorkdayResumeConfig:
    offset: int


def normalize_hostname(hostname: str) -> str:
    """Turn whatever the user typed into a bare Workday host.

    Accepts `wd2-impl-services1.workday.com`, `https://wd2-impl-services1.workday.com/`, or
    a value with a trailing path, and returns the bare host.
    """
    hostname = hostname.strip()
    hostname = re.sub(r"^https?://", "", hostname, flags=re.IGNORECASE)
    return hostname.split("/")[0].strip().rstrip("/")


def normalize_tenant(tenant: str) -> str:
    return tenant.strip().strip("/")


def base_url(hostname: str) -> str:
    return f"https://{normalize_hostname(hostname)}/ccx/api"


def token_url(hostname: str, tenant: str) -> str:
    return f"https://{normalize_hostname(hostname)}/ccx/oauth2/{normalize_tenant(tenant)}/token"


def check_connection_target(hostname: str, tenant: str, team_id: Optional[int] = None) -> tuple[bool, str | None]:
    """Reject a malformed or internally-resolving tenant target before any credential is sent."""
    host = normalize_hostname(hostname)
    if not host or not _HOSTNAME_RE.match(host):
        return False, "Invalid Workday hostname"

    if not normalize_tenant(tenant) or not _TENANT_RE.match(normalize_tenant(tenant)):
        return False, "Invalid Workday tenant"

    # The hostname is fully customer-controlled and the OAuth2 client secret is sent to it, so
    # block hosts resolving to private/internal addresses (SSRF). Only enforced on cloud.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(host, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    return True, None


def mint_access_token(
    hostname: str,
    tenant: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    timeout: int = VALIDATE_TIMEOUT,
) -> str:
    """Exchange the API client's refresh token for a ~1h tenant access token.

    Workday's token endpoint takes the client credentials as HTTP Basic and the grant in the
    form body. `allow_redirects=False` keeps the secret pinned to the validated tenant host.
    """
    session = make_tracked_session(redact_values=(client_secret, refresh_token), capture=False)
    # stream=True so a customer-controlled host can't force us to buffer an unbounded token body;
    # the body is read under byte/time caps by _read_capped_body.
    response = session.post(
        token_url(hostname, tenant),
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        auth=(client_id, client_secret),
        timeout=timeout,
        allow_redirects=False,
        stream=True,
    )

    if response.status_code != 200:
        response.close()
        raise WorkdayAuthError(f"{TOKEN_ERROR} (HTTP {response.status_code})")

    body = _read_capped_body(response)
    try:
        token = json.loads(body).get("access_token")
    except ValueError:
        raise WorkdayAuthError("The Workday token endpoint returned a non-JSON response")
    except AttributeError:
        raise WorkdayAuthError("The Workday token endpoint returned an unexpected response")

    if not isinstance(token, str) or not token:
        raise WorkdayAuthError("The Workday token endpoint returned no access token")

    return token


def validate_credentials(
    hostname: str,
    tenant: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    staffing_version: str,
    schema_name: Optional[str] = None,
    team_id: Optional[int] = None,
) -> tuple[bool, str | None]:
    """Mint a token, then probe one cheap collection to confirm the client can read the tenant.

    At source-create (`schema_name is None`) a 403 is accepted: the API client is genuine but
    may simply lack the domain security policy for this probe. A scoped probe treats 403 as a
    hard failure.
    """
    target_ok, target_err = check_connection_target(hostname, tenant, team_id)
    if not target_ok:
        return False, target_err

    try:
        token = mint_access_token(hostname, tenant, client_id, client_secret, refresh_token)
    except WorkdayAuthError as e:
        return False, str(e)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    endpoint = WORKDAY_ENDPOINTS.get(schema_name or "") or WORKDAY_ENDPOINTS["workers"]
    url = f"{base_url(hostname)}{build_endpoint_path(endpoint, normalize_tenant(tenant), staffing_version)}"

    try:
        response = make_tracked_session(redact_values=(client_secret, refresh_token)).get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params={"limit": 1},
            timeout=VALIDATE_TIMEOUT,
            # A validated host could 3xx to an internal address; don't follow it (SSRF).
            allow_redirects=False,
            # stream=True so a customer-controlled host can't force us to buffer an unbounded probe
            # body — only the status line is inspected below, so the body is never read.
            stream=True,
        )
        response.close()
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Workday rejected the access token for this tenant"

    if response.status_code == 403:
        if schema_name is None:
            return True, None
        return False, "The Workday API client is not authorized for this resource"

    if response.status_code == 404:
        return False, "Workday returned 404 — check the tenant name and that the REST API is enabled"

    return False, f"Workday returned an unexpected response (HTTP {response.status_code})"


def workday_source(
    hostname: str,
    tenant: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    endpoint: str,
    staffing_version: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WorkdayResumeConfig],
) -> SourceResponse:
    endpoint_config = WORKDAY_ENDPOINTS[endpoint]
    host = normalize_hostname(hostname)
    normalized_tenant = normalize_tenant(tenant)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(hostname),
            "headers": {"Accept": "application/json"},
            # The framework auth mints (and re-mints on expiry) the ~1h tenant access token, and
            # redacts the client secret / refresh token / access token from logs and samples.
            "auth": {
                "type": "oauth2",
                "token_url": token_url(hostname, tenant),
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                # Workday's token endpoint expects the client credentials as HTTP Basic.
                "client_auth_method": "basic",
            },
            "paginator": OffsetPaginator(limit=DEFAULT_PAGE_SIZE, total_path="total"),
            # Pin every request — including resumed pages — to the validated tenant host, and
            # refuse redirects so a 3xx can't bounce the bearer token off-host (SSRF).
            "allowed_hosts": [host],
            "allow_redirects": False,
            "request_timeout": REQUEST_TIMEOUT,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": build_endpoint_path(endpoint_config, normalized_tenant, staffing_version),
                    "data_selector": "data",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.offset > 0:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Saved AFTER a page is yielded, so a crash re-fetches the last page (merge dedupes)
        # rather than skipping it.
        if state and state.get("offset"):
            resumable_source_manager.save_state(WorkdayResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    def items() -> Iterator[Any]:
        # Re-check at run time in case the hostname was edited, or now resolves to an internal
        # address (DNS rebinding). Only enforced on cloud.
        host_ok, host_err = _is_host_safe(host, team_id)
        if not host_ok:
            raise WorkdayHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)
        yield from resource

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=[endpoint_config.primary_key],
        partition_count=1,
        partition_size=1,
        # Workday's REST collections have no documented ordering guarantee and no server-side
        # time filter, so every run is a full refresh — nothing downstream depends on an order.
        sort_mode=None,
    )
