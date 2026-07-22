import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from requests import Request, Response

from posthog.cloud_utils import is_cloud

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.dynatrace.settings import (
    DYNATRACE_ENDPOINTS,
    ENDPOINT_SCOPES,
    DynatraceEndpointConfig,
)

# Cheap probe used to confirm the token is genuine at source-create. A 403 still proves the token
# is real (it authenticated but lacks the problems.read scope), so it's accepted there.
PROBE_PATH = "/api/v2/problems"

HOST_NOT_ALLOWED_ERROR = "Dynatrace environment URL is not allowed"


class DynatraceHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class DynatraceResumeConfig:
    # Cursor from the last yielded page. Follow-up URLs are rebuilt from the configured
    # environment URL, so tampered resume state can't redirect the authenticated request.
    next_page_key: str


def normalize_environment_url(environment_url: str) -> str:
    """Turn whatever the user typed into a consistent environment base URL.

    SaaS environments live at ``https://{env-id}.live.dynatrace.com``; Managed deployments at
    ``https://{domain}/e/{env-id}``, so a path prefix must be preserved — we only strip a
    scheme-less prefix, trailing slashes, and an accidentally-pasted ``/api``-style suffix.
    """
    url = environment_url.strip().rstrip("/")
    # Only default the scheme for bare hosts — a non-http(s) scheme must survive normalization
    # so _validated_hostname can reject it.
    if url and "://" not in url:
        url = f"https://{url}"
    for suffix in ("/api/v2", "/api/v1", "/api"):
        if url.lower().endswith(suffix):
            url = url[: -len(suffix)]
            break
    return url.rstrip("/")


def _headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Api-Token {api_token}", "Accept": "application/json"}


def _get_session(api_token: str) -> requests.Session:
    # The environment URL is user-supplied, so pin redirects off so host validation and the
    # outbound request stay on the same target (SSRF defense-in-depth). Redact the token from logs.
    # Body capture stays off: event properties and audit-log patches are free-form customer data
    # that can carry secrets under keys the name-based scrubbers can't recognize. Requests are
    # still metered and logged.
    return make_tracked_session(
        headers=_headers(api_token), redact_values=(api_token,), allow_redirects=False, capture=False
    )


def _validated_hostname(base_url: str) -> Optional[str]:
    """Hostname of the normalized environment URL, or None when the URL is malformed or ambiguous.

    SSRF guard: urlparse treats a backslash as ordinary userinfo and an "@" as a userinfo
    separator, but urllib3/requests treat the backslash as an authority separator, so
    ``https://127.0.0.1\\@example.com`` validates as example.com yet connects to 127.0.0.1.
    A legitimate environment URL has no userinfo, so reject either construct outright and
    require a plain http(s) URL with a clean hostname.
    """
    if "\\" in base_url or "%5c" in base_url.lower():
        return None
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or "@" in parsed.netloc:
        return None
    # The API token rides in the Authorization header on every request, so plaintext http would
    # leak it to any network observer. On PostHog Cloud the request egresses over the public
    # internet, so require https. Self-hosted operators control their own network path (e.g. a
    # Managed cluster reachable only over http), so http stays allowed there.
    if parsed.scheme == "http" and is_cloud():
        return None
    hostname = parsed.hostname
    if not hostname or not re.match(r"^[A-Za-z0-9.\-]+$", hostname):
        return None
    return hostname


def _check_host(environment_url: str, team_id: int) -> None:
    hostname = _validated_hostname(normalize_environment_url(environment_url))
    if not hostname:
        raise DynatraceHostNotAllowedError(HOST_NOT_ALLOWED_ERROR)
    host_ok, host_err = _is_host_safe(hostname, team_id)
    if not host_ok:
        raise DynatraceHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)


def _format_from_value(value: Any) -> str:
    """Format an incremental cursor value for Dynatrace's ``from`` param.

    Dynatrace timestamps are epoch-ms integers, so the stored watermark is usually an int already;
    datetimes are converted for safety, and relative strings (``now-30d``) pass through.
    """
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return str(int(dt.timestamp() * 1000))
    if isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
        return str(int(dt.timestamp() * 1000))
    return str(value)


def _build_url(base_url: str, path: str, params: dict[str, str]) -> str:
    url = f"{base_url}{path}"
    if not params:
        return url
    return f"{url}?{urlencode(params)}"


def _build_request_params(config: DynatraceEndpointConfig) -> dict[str, Any]:
    """First-page query params for the framework resource.

    Time-filtered endpoints declare ``from`` as a framework incremental param: it's seeded with the
    endpoint's lookback (so a first sync / full refresh isn't clamped to Dynatrace's narrow default
    window) and replaced with the stored watermark on incremental runs. Non-incremental endpoints
    that still carry a ``default_from`` (the entity tables) send it as a static param.
    """
    params: dict[str, Any] = {"pageSize": str(config.page_size)}
    if config.entity_selector:
        params["entitySelector"] = config.entity_selector
    params.update(config.extra_params)

    if config.supports_time_filter and config.incremental_field:
        params["from"] = {
            "type": "incremental",
            "cursor_path": config.incremental_field,
            "initial_value": config.default_from,
            "convert": _format_from_value,
        }
    elif config.default_from:
        params["from"] = config.default_from
    return params


class DynatraceNextPageKeyPaginator(BasePaginator):
    """Cursor pagination via Dynatrace's ``nextPageKey``.

    Dynatrace requires follow-up pages to carry ONLY ``nextPageKey`` — the key encodes the original
    query (filters, page size, fields), and mixing it with any other param is rejected. So each
    follow-up request replaces the whole param set with just the cursor. Resumable: the saved cursor
    reseeds the first request the same way.
    """

    def __init__(self) -> None:
        super().__init__()
        self._next_page_key: Optional[str] = None

    def _apply_cursor(self, request: Request) -> None:
        request.params = {"nextPageKey": self._next_page_key}

    def init_request(self, request: Request) -> None:
        # Only set on a resumed run — start the first request at the saved cursor, dropping the
        # first-page filters the cursor already encodes.
        if self._next_page_key is not None:
            self._apply_cursor(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = None
        key = body.get("nextPageKey") if isinstance(body, dict) else None
        if key:
            self._next_page_key = key
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if self._next_page_key is not None:
            self._apply_cursor(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"next_page_key": self._next_page_key} if self._has_next_page and self._next_page_key else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        key = state.get("next_page_key")
        if key is not None:
            self._next_page_key = key
            self._has_next_page = True

    def __str__(self) -> str:
        return "DynatraceNextPageKeyPaginator()"


def validate_credentials(
    environment_url: str,
    api_token: str,
    team_id: Optional[int] = None,
    schema_name: Optional[str] = None,
) -> tuple[bool, str | None]:
    """Validate Dynatrace credentials with a single cheap probe.

    With no ``schema_name`` (source-create) a 403 is accepted: the token authenticated but lacks
    the probed endpoint's scope, and users may legitimately only grant scopes for the endpoints
    they sync. With a ``schema_name`` the probe must actually reach that endpoint.
    """
    base_url = normalize_environment_url(environment_url)
    hostname = _validated_hostname(base_url)
    if not hostname:
        return (
            False,
            "Dynatrace environment URL is invalid. Enter the full environment URL, e.g. https://abc12345.live.dynatrace.com",
        )
    if team_id is not None:
        host_ok, host_err = _is_host_safe(hostname, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    if schema_name is not None and schema_name in DYNATRACE_ENDPOINTS:
        config = DYNATRACE_ENDPOINTS[schema_name]
        probe_params: dict[str, str] = {"pageSize": "1"}
        if config.entity_selector:
            probe_params["entitySelector"] = config.entity_selector
        if config.supports_time_filter or config.default_from:
            probe_params["from"] = "now-1h"
        url = _build_url(base_url, config.path, probe_params)
        required_scope = ENDPOINT_SCOPES.get(schema_name)
    else:
        url = _build_url(base_url, PROBE_PATH, {"pageSize": "1", "from": "now-1h"})
        required_scope = None

    _ok, status = validate_via_probe(lambda: _get_session(api_token), url, ok_statuses=(200,))

    if status is None:
        return False, "Could not reach Dynatrace to validate credentials. Check the environment URL and try again."
    if status == 200:
        return True, None
    if status == 401:
        return False, "Invalid Dynatrace API token. Check the token and environment URL, then try again."
    if status == 403:
        if schema_name is None:
            return True, None
        scope_hint = f" (`{required_scope}`)" if required_scope else ""
        return False, f"Your Dynatrace API token is missing the scope required for this table{scope_hint}."
    if 300 <= status < 400:
        return False, HOST_NOT_ALLOWED_ERROR
    return False, f"Dynatrace credential validation failed (status {status})."


def check_endpoint_permissions(
    environment_url: str, api_token: str, endpoints: list[str], team_id: int
) -> dict[str, str | None]:
    """Per-endpoint scope probe for the schema picker. ``None`` = reachable, else a short reason.

    Endpoints sharing a scope (the four entity tables) share one probe. Only a real 403 denial is
    reported — throttles, 5xx, and network blips must not mark a table as missing permissions.
    """
    base_url = normalize_environment_url(environment_url)
    hostname = _validated_hostname(base_url)
    if not hostname:
        return dict.fromkeys(endpoints, HOST_NOT_ALLOWED_ERROR)
    host_ok, host_err = _is_host_safe(hostname, team_id)
    if not host_ok:
        return dict.fromkeys(endpoints, host_err or HOST_NOT_ALLOWED_ERROR)

    session = _get_session(api_token)
    results: dict[str, str | None] = {}
    denial_by_scope: dict[str, str | None] = {}

    for endpoint in endpoints:
        config = DYNATRACE_ENDPOINTS.get(endpoint)
        if config is None:
            results[endpoint] = None
            continue

        scope = ENDPOINT_SCOPES.get(endpoint, "")
        if scope in denial_by_scope:
            results[endpoint] = denial_by_scope[scope]
            continue

        probe_params: dict[str, str] = {"pageSize": "1"}
        if config.entity_selector:
            probe_params["entitySelector"] = config.entity_selector
        if config.supports_time_filter or config.default_from:
            probe_params["from"] = "now-1h"

        try:
            response = session.get(
                _build_url(base_url, config.path, probe_params),
                timeout=10,
            )
        except requests.exceptions.RequestException:
            results[endpoint] = None
            continue

        denial = f"Your API token is missing the `{scope}` scope" if response.status_code == 403 else None
        denial_by_scope[scope] = denial
        results[endpoint] = denial

    return results


def dynatrace_source(
    environment_url: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DynatraceResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = DYNATRACE_ENDPOINTS[endpoint]

    def items() -> Iterator[list[dict[str, Any]]]:
        # Re-check at run time (not just at source-create) in case the environment URL was edited or
        # now resolves to an internal address (SSRF / DNS rebinding). Raises before any request — and
        # before a session is built — so an unsafe host never sees a packet. Only enforced on cloud.
        _check_host(environment_url, team_id)
        base_url = normalize_environment_url(environment_url)

        initial_paginator_state: Optional[dict[str, Any]] = None
        if resumable_source_manager.can_resume():
            resume = resumable_source_manager.load_state()
            if resume is not None and resume.next_page_key:
                initial_paginator_state = {"next_page_key": resume.next_page_key}

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
            # the last batch (merge dedupes on the primary key) rather than skipping it.
            if state and state.get("next_page_key"):
                resumable_source_manager.save_state(DynatraceResumeConfig(next_page_key=state["next_page_key"]))

        rest_config: RESTAPIConfig = {
            "client": {
                "base_url": base_url,
                # Non-secret headers only; the token rides the framework api_key auth so it's redacted
                # from logs and raised error messages.
                "headers": {"Accept": "application/json"},
                "auth": {
                    "type": "api_key",
                    "api_key": f"Api-Token {api_token}",
                    "name": "Authorization",
                    "location": "header",
                },
                "paginator": DynatraceNextPageKeyPaginator(),
                # The environment URL is user-supplied: pin every request to its host and refuse any
                # redirect so the Authorization header can't be bounced off the validated target.
                "allowed_hosts": [],
                "allow_redirects": False,
            },
            "resource_defaults": {},
            "resources": [
                {
                    "name": endpoint,
                    "endpoint": {
                        "path": config.path,
                        "params": _build_request_params(config),
                        # Missing key / non-list body yields 0 rows (matches the previous behavior),
                        # so no data_selector_required here.
                        "data_selector": config.data_key,
                    },
                }
            ],
        }

        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
        yield from resource

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=[config.primary_key],
        # Dynatrace documents no reliable ascending sort we can verify for the time-filtered
        # endpoints (audit logs default to newest-first), so incremental endpoints run in desc
        # mode: the watermark is the max seen across the run, persisted only at successful job
        # end — correct regardless of the order rows actually arrive in.
        sort_mode="desc" if config.supports_time_filter else "asc",
        partition_count=1,
        partition_size=1,
    )
