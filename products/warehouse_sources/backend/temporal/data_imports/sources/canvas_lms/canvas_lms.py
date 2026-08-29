import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Optional, cast
from urllib.parse import urlparse

import requests
from requests import Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.canvas_lms.settings import (
    CANVAS_ENDPOINTS,
    CanvasEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
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
    HeaderLinkPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

REQUEST_TIMEOUT_SECONDS = 30

HOST_NOT_ALLOWED_ERROR = "Canvas domain is not allowed"


class CanvasHostNotAllowedError(Exception):
    pass


@frozen
class CanvasLmsResumeConfig:
    # Top-level endpoints (courses, users) resume from the opaque Link-header `next` URL.
    next_url: Optional[str] = None
    # Fan-out endpoints (enrollments, assignments, submissions) resume by parent: course paths
    # already fully synced, the course in progress, and that course's paginator state -- see
    # `common.rest_source.__init__._make_paginate_dependent_resource`.
    completed: Optional[list[str]] = None
    current: Optional[str] = None
    child_state: Optional[dict[str, Any]] = None


def normalize_domain(domain: str) -> str:
    """Turn whatever the user typed into a bare Canvas host.

    Accepts values like ``yourschool.instructure.com``, ``https://yourschool.instructure.com/``,
    or a custom vanity domain, and returns just the host.
    """
    domain = domain.strip()
    domain = re.sub(r"^https?://", "", domain, flags=re.IGNORECASE)
    domain = domain.split("/")[0]
    return domain.strip().rstrip("/")


def _base_url(domain: str) -> str:
    return f"https://{normalize_domain(domain)}/api/v1"


def _get_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def _is_same_host(url: str, domain: str) -> bool:
    """Whether ``url`` points at the configured Canvas host.

    Pagination/resume URLs are server-controlled (they arrive in the Link header), so they're
    pinned to the validated institution host to avoid being redirected at an arbitrary internal
    address (SSRF).
    """
    try:
        return (urlparse(url).hostname or "").lower() == normalize_domain(domain).lower()
    except Exception:
        return False


class CanvasLinkPaginator(HeaderLinkPaginator):
    """Canvas paginates via the ``Link`` response header (RFC 5988, ``rel="next"``). The link is
    server-controlled, so it's pinned to the configured Canvas domain -- an off-host link stops
    pagination (SSRF guard) instead of being followed."""

    def __init__(self, domain: str) -> None:
        super().__init__()
        self._domain = domain

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and self._next_url is not None and not _is_same_host(self._next_url, self._domain):
            self._has_next_page = False
            self._next_url = None


def _format_canvas_datetime(value: Any) -> str:
    """Format a date/datetime-like value as the ISO 8601 UTC string Canvas's
    `submitted_since`/`graded_since` filters expect. Falls back to `str(value)` for values that are
    already a formatted string (e.g. our own `initial_value` seed)."""
    normalized = coerce_datetime_to_utc(value)
    if normalized is None:
        return str(value)
    capped = min(normalized, datetime.now(UTC))
    return capped.strftime("%Y-%m-%dT%H:%M:%SZ")


def _incremental_window(field_name: str, query_param: str) -> IncrementalConfig:
    return {
        "cursor_path": field_name,
        "start_param": query_param,
        "initial_value": "1970-01-01T00:00:00Z",
        "convert": _format_canvas_datetime,
    }


def _client_config(domain: str, api_key: str) -> ClientConfig:
    return {
        "base_url": _base_url(domain),
        # Auth (the bearer token) rides the framework auth config so it's redacted from logs and
        # raised error messages; only the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_key},
        "paginator": CanvasLinkPaginator(domain),
        # A validated host could 3xx to an internal address; refuse to follow redirects (SSRF).
        "allow_redirects": False,
        # Pins every outgoing request -- including Link-header pagination and resumed fan-out
        # checkpoint URLs -- to the configured domain's exact scheme/host/port (the base_url host
        # is implicitly allowed). The `_is_same_host`/paginator checks above only compare hostname,
        # so this is what actually rejects a same-host scheme downgrade (https->http) or a
        # different port before the Authorization header goes out (SSRF / credential exfiltration).
        "allowed_hosts": [],
        # A source pointed at a customer-controlled host that accepts a connection and then never
        # responds would otherwise hold an import worker forever; bound every request.
        "request_timeout": REQUEST_TIMEOUT_SECONDS,
        # Canvas responses carry student/staff PII and grading data (SIS identifiers, assignment
        # HTML, scores) that the name-based sample scrubbers aren't guaranteed to catch, so keep
        # raw bodies out of HTTP sample capture even where an operator enables it -- same pattern
        # as the Clever source, which carries comparable student/guardian/staff PII.
        "capture": False,
    }


def _make_source_response(config: CanvasEndpointConfig, items: Any) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Neither `submitted_since`/`graded_since` (submissions) nor plain account-level listings
        # guarantee response ordering, but each sync re-applies the filter and paginates every
        # page, so completeness doesn't depend on it. Merge dedupes on the primary key regardless.
        sort_mode="asc",
    )


def validate_credentials(
    domain: str,
    account_id: str,
    api_key: str,
    schema_name: Optional[str] = None,
    team_id: Optional[int] = None,
) -> tuple[bool, str | None]:
    """Probe the account-level courses listing to confirm the domain, account ID, and token
    together resolve to something real.

    At source-create (``schema_name is None``) a 403 is accepted: the token may be valid but
    simply lack admin rights on this particular account, which is fine if the user only wants the
    endpoints they can already read. A scoped probe (``schema_name`` set) treats 403 as a hard
    failure.
    """
    try:
        normalized = normalize_domain(domain)
    except Exception:
        return False, "Invalid Canvas domain"

    if not normalized or not re.match(r"^[A-Za-z0-9.\-]+$", normalized):
        return (
            False,
            "That doesn't look like a Canvas domain. Enter your institution's domain, "
            "e.g. 'yourschool.instructure.com'.",
        )

    # The institution domain is fully customer-controlled, so block hosts that resolve to
    # private/internal addresses (SSRF). Only enforced on cloud -- see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(normalized, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    url = f"{_base_url(domain)}/accounts/{account_id}/courses"
    try:
        # Don't follow redirects: the validated host could 3xx to an internal address, defeating
        # the host check above (SSRF). The probe response body carries real course data, so also
        # keep it out of HTTP sample capture -- same reasoning as `_client_config`.
        response = make_tracked_session(redact_values=(api_key,), capture=False).get(
            url,
            headers=_get_headers(api_key),
            params={"per_page": 1},
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Canvas access token"
    if response.status_code == 404:
        return False, "Canvas account not found. Check the account ID and try again."
    if response.status_code == 403:
        if schema_name is None:
            # Valid token, missing admin rights on this account -- let source creation through.
            return True, None
        return False, "Your Canvas access token doesn't have admin access to this account."

    return False, f"Could not connect to Canvas (HTTP {response.status_code})"


def _non_fanout_source(
    config: CanvasEndpointConfig,
    domain: str,
    account_id: str,
    api_key: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CanvasLmsResumeConfig],
) -> SourceResponse:
    path = config.path.replace("{account_id}", account_id)

    rest_config: RESTAPIConfig = {
        "client": _client_config(domain, api_key),
        "resource_defaults": {},
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": path,
                    "params": {"per_page": config.page_size},
                },
                "table_format": "delta",
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url and _is_same_host(resume.next_url, domain):
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # the next page (merge dedupes) rather than skipping data.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(CanvasLmsResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    def items() -> Iterable[Any]:
        # Re-check at run time (not just at source-create) in case the domain was edited or now
        # resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
        host_ok, host_err = _is_host_safe(normalize_domain(domain), team_id)
        if not host_ok:
            raise CanvasHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)
        yield from resource

    return _make_source_response(config, items)


def _fanout_source(
    config: CanvasEndpointConfig,
    domain: str,
    account_id: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CanvasLmsResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    incremental_field: str | None,
) -> SourceResponse:
    assert config.fanout is not None

    initial_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and (resume.completed or resume.current):
            initial_state = {
                "completed": resume.completed or [],
                "current": resume.current,
                "child_state": resume.child_state,
            }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(
                CanvasLmsResumeConfig(
                    completed=state.get("completed"),
                    current=state.get("current"),
                    child_state=state.get("child_state"),
                )
            )

    dependent_resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=CANVAS_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=_client_config(domain, api_key),
            path_format_values={"account_id": account_id},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
            incremental_field=incremental_field,
            incremental_config_factory=lambda field_name: _incremental_window(
                field_name, config.incremental_query_params[field_name]
            ),
            page_size_param="per_page",
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        ),
    )

    def items() -> Iterable[Any]:
        host_ok, host_err = _is_host_safe(normalize_domain(domain), team_id)
        if not host_ok:
            raise CanvasHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)
        yield from dependent_resource

    return _make_source_response(config, items)


def canvas_lms_source(
    domain: str,
    account_id: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CanvasLmsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = CANVAS_ENDPOINTS[endpoint]

    if config.fanout is not None:
        return _fanout_source(
            config,
            domain,
            account_id,
            api_key,
            endpoint,
            team_id,
            job_id,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
            incremental_field,
        )

    return _non_fanout_source(config, domain, account_id, api_key, team_id, job_id, resumable_source_manager)


__all__ = [
    "CanvasHostNotAllowedError",
    "CanvasLmsResumeConfig",
    "HOST_NOT_ALLOWED_ERROR",
    "canvas_lms_source",
    "normalize_domain",
    "validate_credentials",
]
