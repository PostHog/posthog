import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.cloud_utils import is_cloud

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.dynatrace.settings import (
    DYNATRACE_ENDPOINTS,
    ENDPOINT_SCOPES,
    DynatraceEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
# Cheap probe used to confirm the token is genuine at source-create. A 403 still proves the token
# is real (it authenticated but lacks the problems.read scope), so it's accepted there.
PROBE_PATH = "/api/v2/problems"

HOST_NOT_ALLOWED_ERROR = "Dynatrace environment URL is not allowed"


class DynatraceRetryableError(Exception):
    pass


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
    return make_tracked_session(headers=_headers(api_token), redact_values=(api_token,), allow_redirects=False)


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


def _build_first_page_params(
    config: DynatraceEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, str]:
    params: dict[str, str] = {"pageSize": str(config.page_size)}

    if config.entity_selector:
        params["entitySelector"] = config.entity_selector

    if config.supports_time_filter or config.default_from:
        # Continue from the stored watermark on incremental runs; otherwise seed the first sync /
        # full refresh with the endpoint's lookback so Dynatrace doesn't fall back to its very
        # narrow defaults (problems/events default to now-2h).
        if config.supports_time_filter and should_use_incremental_field and db_incremental_field_last_value:
            params["from"] = _format_from_value(db_incremental_field_last_value)
        elif config.default_from:
            params["from"] = config.default_from

    params.update(config.extra_params)
    return params


def _build_url(base_url: str, path: str, params: dict[str, str]) -> str:
    url = f"{base_url}{path}"
    if not params:
        return url
    return f"{url}?{urlencode(params)}"


def _next_page_url(base_url: str, config: DynatraceEndpointConfig, next_page_key: str) -> str:
    # Dynatrace requires follow-up pages to carry ONLY nextPageKey — the key encodes the original
    # query (filters, page size, fields), and mixing it with other params is rejected.
    return _build_url(base_url, config.path, {"nextPageKey": next_page_key})


def _extract_items(response_json: Any, config: DynatraceEndpointConfig) -> list[dict[str, Any]]:
    if not isinstance(response_json, dict):
        return []
    items = response_json.get(config.data_key, [])
    return items if isinstance(items, list) else []


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

    try:
        session = _get_session(api_token)
        response = session.get(url, timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Dynatrace API token. Check the token and environment URL, then try again."
    if response.status_code == 403:
        if schema_name is None:
            return True, None
        scope_hint = f" (`{required_scope}`)" if required_scope else ""
        return False, f"Your Dynatrace API token is missing the scope required for this table{scope_hint}."
    if 300 <= response.status_code < 400:
        return False, HOST_NOT_ALLOWED_ERROR
    return False, f"Dynatrace credential validation failed (status {response.status_code})."


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


def get_rows(
    environment_url: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DynatraceResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = DYNATRACE_ENDPOINTS[endpoint]
    # Re-check at run time (not just at source-create) in case the environment URL was edited or
    # now resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    _check_host(environment_url, team_id)

    base_url = normalize_environment_url(environment_url)
    # One tracked session reused across pages and retries; the token is redacted from logged URLs
    # and captured samples.
    session = _get_session(api_token)

    @retry(
        retry=retry_if_exception_type(
            (
                DynatraceRetryableError,
                requests.ReadTimeout,
                requests.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            )
        ),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(page_url: str) -> Any:
        response = session.get(page_url, timeout=REQUEST_TIMEOUT_SECONDS)

        # The session never follows redirects: a 3xx would move the sync off the validated host
        # (SSRF), so refuse it rather than silently fetching an empty body.
        if 300 <= response.status_code < 400:
            raise DynatraceHostNotAllowedError(HOST_NOT_ALLOWED_ERROR)

        if response.status_code == 429 or response.status_code >= 500:
            raise DynatraceRetryableError(
                f"Dynatrace API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"Dynatrace API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None and resume_config.next_page_key:
        url = _next_page_url(base_url, config, resume_config.next_page_key)
        logger.debug(f"Dynatrace: resuming {endpoint} from saved nextPageKey")
    else:
        params = _build_first_page_params(config, should_use_incremental_field, db_incremental_field_last_value)
        url = _build_url(base_url, config.path, params)

    while True:
        data = fetch_page(url)

        items = _extract_items(data, config)
        if items:
            yield items

        next_page_key = data.get("nextPageKey") if isinstance(data, dict) else None
        if not next_page_key:
            break

        # Save state AFTER yielding the batch — a crash re-yields the last batch (merge dedupes on
        # the primary key) instead of skipping it.
        resumable_source_manager.save_state(DynatraceResumeConfig(next_page_key=next_page_key))
        url = _next_page_url(base_url, config, next_page_key)


def dynatrace_source(
    environment_url: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DynatraceResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = DYNATRACE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            environment_url=environment_url,
            api_token=api_token,
            endpoint=endpoint,
            team_id=team_id,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        # Dynatrace documents no reliable ascending sort we can verify for the time-filtered
        # endpoints (audit logs default to newest-first), so incremental endpoints run in desc
        # mode: the watermark is the max seen across the run, persisted only at successful job
        # end — correct regardless of the order rows actually arrive in.
        sort_mode="desc" if config.supports_time_filter else "asc",
        partition_count=1,
        partition_size=1,
    )
