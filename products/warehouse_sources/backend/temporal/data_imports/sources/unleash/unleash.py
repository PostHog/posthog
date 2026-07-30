import re
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlparse

import requests

from posthog.cloud_utils import is_cloud

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    Endpoint,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.unleash.settings import UNLEASH_ENDPOINTS

# The feature search endpoint documents a default limit of 50; 100 verified working against a
# live instance and keeps round trips low.
PAGE_SIZE = 100
# Cheap list endpoint used to confirm the token is genuine. Every admin-capable token (personal
# access token, service account token) can read projects.
DEFAULT_PROBE_PATH = "/api/admin/projects"

HOST_NOT_ALLOWED_ERROR = "Unleash instance URL is not allowed"


class UnleashHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class UnleashResumeConfig:
    # Offset of the next feature-search page to fetch. Only the features endpoint paginates;
    # a crashed sync resumes from the page after the last one yielded and merge dedupes the
    # re-pulled page on the primary key. The other endpoints return the whole collection in one
    # request, so there is nothing to resume.
    offset: int = 0


def normalize_instance_url(instance_url: str) -> str:
    """Turn whatever the user typed into a consistent instance base URL.

    Unleash instances live at a per-customer URL that may include a path prefix (e.g.
    ``https://us.app.unleash-hosted.com/some-instance`` on Unleash cloud), so the path must be
    preserved — we only strip a scheme-less prefix, trailing slashes, and an accidentally-pasted
    ``/api`` or ``/api/admin`` suffix.
    """
    url = instance_url.strip().rstrip("/")
    # Only default the scheme for bare hosts — a non-http(s) scheme must survive normalization
    # so _validated_hostname can reject it.
    if url and "://" not in url:
        url = f"https://{url}"
    for suffix in ("/api/admin", "/api"):
        if url.lower().endswith(suffix):
            url = url[: -len(suffix)]
            break
    return url.rstrip("/")


def _headers(api_token: str) -> dict[str, str]:
    # Unleash expects the token as the raw Authorization header value — no Bearer prefix
    # (verified against a live instance; a Bearer-prefixed token is rejected).
    return {"Authorization": api_token, "Accept": "application/json"}


def _get_session(api_token: str) -> requests.Session:
    # The instance URL is user-supplied, so pin redirects off so host validation and the
    # outbound request stay on the same target (SSRF defense-in-depth). Redact the token
    # from logs.
    return make_tracked_session(headers=_headers(api_token), redact_values=(api_token,), allow_redirects=False)


def _validated_hostname(base_url: str) -> Optional[str]:
    """Hostname of the normalized instance URL, or None when the URL is malformed or ambiguous.

    SSRF guard: urlparse treats a backslash as ordinary userinfo and an "@" as a userinfo
    separator, but urllib3/requests treat the backslash as an authority separator, so
    `https://127.0.0.1\\@example.com` validates as example.com yet connects to 127.0.0.1.
    A legitimate instance URL has no userinfo, so reject either construct outright (same
    guard as the n8n source) and require a plain http(s) URL with a clean hostname.
    """
    if "\\" in base_url or "%5c" in base_url.lower():
        return None
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or "@" in parsed.netloc:
        return None
    # The API token rides in the Authorization header on every request, so plaintext http would
    # leak it to any network observer. On PostHog Cloud the request egresses over the public
    # internet, so require https. Self-hosted operators control their own network path (e.g. an
    # internal Unleash reachable only over http), so http stays allowed there — mirroring how host
    # IP safety is only enforced on cloud.
    if parsed.scheme == "http" and is_cloud():
        return None
    hostname = parsed.hostname
    if not hostname or not re.match(r"^[A-Za-z0-9.\-]+$", hostname):
        return None
    return hostname


def _check_host(instance_url: str, team_id: int) -> None:
    hostname = _validated_hostname(normalize_instance_url(instance_url))
    if not hostname:
        raise UnleashHostNotAllowedError(HOST_NOT_ALLOWED_ERROR)
    host_ok, host_err = _is_host_safe(hostname, team_id)
    if not host_ok:
        raise UnleashHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)


def unleash_source(
    instance_url: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[UnleashResumeConfig],
) -> SourceResponse:
    config = UNLEASH_ENDPOINTS[endpoint]
    base_url = normalize_instance_url(instance_url)

    endpoint_config: Endpoint = {
        "path": config.path,
        # A 200 whose body isn't the expected list shape (missing data key, wrong type) is treated
        # as a transient upstream glitch and retried — the retryable counterpart of the old
        # _extract_rows guard, which raised a retryable error on an unexpected payload.
        "data_selector_malformed_retryable": True,
    }
    if config.data_selector is not None:
        endpoint_config["data_selector"] = config.data_selector

    if config.paginated:
        # Sort by createdAt ascending so page boundaries stay stable while we walk the offsets —
        # flags created mid-sync land at the end instead of shifting earlier pages.
        endpoint_config["params"] = {"sortBy": "createdAt", "sortOrder": "asc"}
        paginator: OffsetPaginator | SinglePagePaginator = OffsetPaginator(limit=PAGE_SIZE, total_path="total")
    else:
        paginator = SinglePagePaginator()

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url,
            # Auth (raw token, no Bearer prefix) is supplied via the framework auth config so its
            # value is redacted from logs and raised errors; only the non-secret Accept header here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "api_key", "api_key": api_token, "name": "Authorization", "location": "header"},
            "paginator": paginator,
            # The instance URL is user-supplied: pin every request (including pagination) to the
            # base host and refuse redirects so the credentialed request can't be bounced off-host.
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": endpoint_config,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(UnleashResumeConfig(offset=int(state["offset"])))

    def items() -> Iterator[list[dict[str, Any]]]:
        # Re-check at run time (not just at source-create) in case the instance URL was edited or
        # now resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
        _check_host(instance_url, team_id)
        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint if config.paginated else None,
            initial_paginator_state=initial_paginator_state,
        )
        for batch in resource:
            # An empty collection/page must not push an empty batch into the pipeline.
            if batch:
                yield batch

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def _error_message(response: requests.Response) -> Optional[str]:
    # Unleash error bodies carry a human-readable `message` (e.g. PermissionError details).
    try:
        body = response.json()
        if isinstance(body, dict) and isinstance(body.get("message"), str):
            return body["message"]
    except Exception:
        pass
    return None


def validate_credentials(
    instance_url: str, api_token: str, schema_name: Optional[str] = None, team_id: Optional[int] = None
) -> tuple[bool, str | None]:
    """Probe a cheap list endpoint to confirm the token is genuine.

    At source-create (``schema_name is None``) a 403 is accepted: the token is valid but may lack
    the permission for this particular probe. A scoped probe (``schema_name`` set) treats 403 as a
    hard failure.
    """
    base_url = normalize_instance_url(instance_url)
    hostname = _validated_hostname(base_url)
    if not hostname:
        return False, "Invalid Unleash instance URL"

    # The instance URL is fully customer-controlled, so block hosts that resolve to private/
    # internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(hostname, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    session = _get_session(api_token)
    try:
        # The session never follows redirects: the validated host could 3xx to an internal
        # address, defeating the host check above (SSRF).
        response = session.get(f"{base_url}{DEFAULT_PROBE_PATH}", timeout=15)
    except requests.exceptions.RequestException as e:
        return False, f"Could not connect to Unleash: {e}"

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Invalid Unleash API token"

    if response.status_code == 403:
        if schema_name is None:
            # Valid token, missing permission for this probe — let source creation through.
            return True, None
        return False, _error_message(response) or "Your Unleash API token lacks the required permissions"

    return False, _error_message(response) or f"Unleash returned HTTP {response.status_code}"


def check_endpoint_permissions(
    instance_url: str, api_token: str, endpoints: list[str], team_id: int
) -> dict[str, str | None]:
    """Probe each endpoint and report which ones the token cannot read.

    Returns ``{endpoint: None}`` when reachable and ``{endpoint: reason}`` on a real denial
    (401/403). Transient failures (throttles, 5xx, network blips) are not permission problems, so
    they report as reachable rather than blocking the schema picker.
    """
    base_url = normalize_instance_url(instance_url)
    hostname = _validated_hostname(base_url)
    if not hostname:
        return dict.fromkeys(endpoints, "Invalid Unleash instance URL")
    host_ok, host_err = _is_host_safe(hostname, team_id)
    if not host_ok:
        return dict.fromkeys(endpoints, host_err or HOST_NOT_ALLOWED_ERROR)

    session = _get_session(api_token)
    results: dict[str, str | None] = {}
    for endpoint in endpoints:
        config = UNLEASH_ENDPOINTS.get(endpoint)
        if config is None:
            results[endpoint] = None
            continue
        params = {"limit": 1} if config.paginated else None
        try:
            response = session.get(f"{base_url}{config.path}", params=params, timeout=15)
        except requests.exceptions.RequestException:
            results[endpoint] = None
            continue
        if response.status_code == 401:
            results[endpoint] = "Invalid Unleash API token"
        elif response.status_code == 403:
            reason = _error_message(response) or "Your Unleash API token lacks the required permissions"
            if config.requires_admin:
                reason = f"{reason} This table requires a token with the Admin root role."
            results[endpoint] = reason
        else:
            results[endpoint] = None
    return results
