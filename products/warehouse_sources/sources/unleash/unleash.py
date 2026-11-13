import re
import math
import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse

import requests

from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    OffsetPaginator,
    Resource,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    _is_host_safe,
    is_cloud,
    make_parent_key_name,
    make_tracked_session,
    rest_api_resources,
)
from products.warehouse_sources.sources.unleash.settings import UNLEASH_ENDPOINTS, UnleashEndpointConfig

FEATURES_ENDPOINT = "features"
# The raw client metrics endpoint accepts hoursBack from 1 to 48 on every instance.
MAX_METRICS_HOURS_BACK = 48
# Cheap list endpoint used to confirm the token is genuine. Every admin-capable token (personal
# access token, service account token) can read projects.
DEFAULT_PROBE_PATH = "/api/admin/projects"

HOST_NOT_ALLOWED_ERROR = "Unleash instance URL is not allowed"


class UnleashHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass(frozen=False)
class UnleashResumeConfig:
    # Offset of the next feature or event search page to fetch; a crashed sync resumes from the
    # page after the last one yielded and merge dedupes the re-pulled page on the primary key.
    # The other list endpoints return the whole collection in one request.
    offset: int = 0
    # Fan-out children: the state rest_source checkpoints over the `features` listing.
    fanout_state: Optional[dict[str, Any]] = None


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


def _list_endpoint(config: UnleashEndpointConfig, params: Optional[dict[str, Any]] = None) -> Endpoint:
    endpoint: Endpoint = {
        "path": config.path,
        # A 200 whose body isn't the expected list shape (missing data key, wrong type) is treated
        # as a transient upstream glitch and retried — the retryable counterpart of the old
        # _extract_rows guard, which raised a retryable error on an unexpected payload.
        "data_selector_malformed_retryable": True,
    }
    if config.data_selector is not None:
        endpoint["data_selector"] = config.data_selector
    request_params: dict[str, Any] = dict(params or {})
    if config.paginated:
        if config.name == FEATURES_ENDPOINT:
            # Sort by createdAt ascending so page boundaries stay stable while we walk the offsets —
            # flags created mid-sync land at the end instead of shifting earlier pages.
            request_params.update({"sortBy": "createdAt", "sortOrder": "asc"})
        endpoint["paginator"] = OffsetPaginator(limit=config.page_size, total_path="total")
    else:
        endpoint["paginator"] = SinglePagePaginator()
    if request_params:
        endpoint["params"] = request_params
    return endpoint


def _as_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def events_params(db_incremental_field_last_value: Any) -> dict[str, Any]:
    last = _as_datetime(db_incremental_field_last_value)
    if last is None:
        return {}
    # `from` takes a date and compares it in the server's time zone, so step back a day. The
    # merge on `id` drops the rows read again.
    return {"from": f"IS:{(last - timedelta(days=1)).date().isoformat()}"}


def metrics_hours_back(db_incremental_field_last_value: Any, now: Optional[datetime] = None) -> int:
    last = _as_datetime(db_incremental_field_last_value)
    if last is None:
        return MAX_METRICS_HOURS_BACK
    elapsed_hours = ((now or datetime.now(UTC)) - last).total_seconds() / 3600
    # One extra hour reads the last synced bucket again, since it can still have been filling.
    return max(1, min(MAX_METRICS_HOURS_BACK, math.ceil(elapsed_hours) + 1))


def _parent_value(row: dict[str, Any], field: str) -> Any:
    return row.pop(make_parent_key_name(FEATURES_ENDPOINT, field), None)


def flatten_feature_strategies(environment: dict[str, Any]) -> list[dict[str, Any]]:
    feature_name = _parent_value(environment, "name")
    project = _parent_value(environment, "project")
    return [
        {
            **strategy,
            "featureName": strategy.get("featureName") or feature_name,
            "project": project,
            "environment": environment.get("name"),
            "environmentEnabled": environment.get("enabled"),
        }
        for strategy in environment.get("strategies") or []
        if isinstance(strategy, dict)
    ]


def shape_feature_metric(row: dict[str, Any]) -> dict[str, Any]:
    feature_name = _parent_value(row, "name")
    if not row.get("featureName"):
        row["featureName"] = feature_name
    return row


ROW_MAPS: dict[str, Callable[[dict[str, Any]], dict[str, Any] | list[dict[str, Any]]]] = {
    "feature_strategies": flatten_feature_strategies,
    "feature_metrics": shape_feature_metric,
}


def _fanout_resources(config: UnleashEndpointConfig, child_params: dict[str, Any]) -> list[str | EndpointResource]:
    child_endpoint: Endpoint = {
        "path": config.path,
        "params": {
            **{
                field: {"type": "resolve", "resource": FEATURES_ENDPOINT, "field": field}
                for field in config.parent_fields
            },
            **child_params,
        },
        "data_selector_malformed_retryable": True,
        "paginator": SinglePagePaginator(),
        # A flag archived between the listing and its child request returns 404.
        "response_actions": [{"status_code": 404, "action": "ignore"}],
    }
    if config.data_selector is not None:
        child_endpoint["data_selector"] = config.data_selector
    return [
        {"name": FEATURES_ENDPOINT, "endpoint": _list_endpoint(UNLEASH_ENDPOINTS[FEATURES_ENDPOINT])},
        {
            "name": config.name,
            "endpoint": child_endpoint,
            "include_from_parent": list(config.parent_fields),
            "data_map": ROW_MAPS[config.name],
            # The checkpoint stores the parent page, not every finished flag.
            "resume_parent_pagination": True,
        },
    ]


def unleash_source(
    instance_url: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[UnleashResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = UNLEASH_ENDPOINTS[endpoint]
    base_url = normalize_instance_url(instance_url)
    last_value = db_incremental_field_last_value if should_use_incremental_field else None

    client_config: ClientConfig = {
        "base_url": base_url,
        # Auth (raw token, no Bearer prefix) is supplied via the framework auth config so its
        # value is redacted from logs and raised errors; only the non-secret Accept header here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "api_key": api_token, "name": "Authorization", "location": "header"},
        # The instance URL is user-supplied: pin every request (including pagination) to the
        # base host and refuse redirects so the credentialed request can't be bounced off-host.
        "allowed_hosts": [],
        "allow_redirects": False,
    }

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    resume_hook: Optional[Callable[[Optional[dict[str, Any]]], None]] = None
    initial_paginator_state: Optional[dict[str, Any]] = None
    resources: list[str | EndpointResource]

    if config.parent_fields:
        child_params = {"hoursBack": metrics_hours_back(last_value)} if endpoint == "feature_metrics" else {}
        resources = _fanout_resources(config, child_params)
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state

        def save_fanout_state(state: Optional[dict[str, Any]]) -> None:
            if state:
                resumable_source_manager.save_state(UnleashResumeConfig(fanout_state=state))

        resume_hook = save_fanout_state
    else:
        params = events_params(last_value) if endpoint == "events" else None
        resources = [{"name": endpoint, "endpoint": _list_endpoint(config, params)}]
        if config.paginated:
            if resume is not None:
                initial_paginator_state = {"offset": resume.offset}

            def save_offset(state: Optional[dict[str, Any]]) -> None:
                # Persist only when a next page remains. The framework stages it with the page it covers.
                if state and state.get("offset") is not None:
                    resumable_source_manager.save_state(UnleashResumeConfig(offset=int(state["offset"])))

            resume_hook = save_offset

    rest_config: RESTAPIConfig = {"client": client_config, "resource_defaults": {}, "resources": resources}

    def items() -> Resource:
        # Re-check at run time (not just at source-create) in case the instance URL was edited or
        # now resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
        _check_host(instance_url, team_id)
        built = rest_api_resources(
            rest_config,
            team_id,
            job_id,
            None,
            resume_hook=resume_hook,
            initial_paginator_state=initial_paginator_state,
        )
        return next(resource for resource in built if resource.name == endpoint)

    partition_kwargs: dict[str, Any] = (
        {"partition_mode": "datetime", "partition_format": "month", "partition_keys": [config.partition_key]}
        if config.partition_key
        else {"partition_count": 1, "partition_size": 1}
    )
    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        **partition_kwargs,
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
        # A fan-out child reads one flag at a time, so probe the flag listing it walks.
        probe = UNLEASH_ENDPOINTS[FEATURES_ENDPOINT] if config.parent_fields else config
        params = {"limit": 1} if probe.paginated else None
        try:
            response = session.get(f"{base_url}{probe.path}", params=params, timeout=15)
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
