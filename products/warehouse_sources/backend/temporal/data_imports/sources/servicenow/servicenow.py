import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.servicenow.settings import SERVICENOW_ENDPOINTS

# ServiceNow's Table API defaults to a generous page size; we keep it modest so each
# heartbeat-bounded batch stays small and resumable. Offset pagination is simple and
# universally supported. Keyset pagination (ORDERBY sys_created_on with a moving
# floor) performs better on very large tables, but offset keeps resume state trivial
# and is adequate for the table sizes this source targets.
DEFAULT_PAGE_SIZE = 1000
REQUEST_TIMEOUT = 60
MAX_RETRY_ATTEMPTS = 5


class ServiceNowRetryableError(Exception):
    pass


class ServiceNowError(Exception):
    """Non-retryable ServiceNow transport error (e.g. an unexpected redirect)."""


@dataclasses.dataclass
class ServiceNowResumeConfig:
    offset: int


@dataclasses.dataclass
class ServiceNowAuth:
    """Resolved credentials for a single sync. Exactly one auth style is populated."""

    api_key: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None

    def headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["x-sn-apikey"] = self.api_key
        return headers

    def basic_auth(self) -> Optional[tuple[str, str]]:
        if self.username and self.password:
            return (self.username, self.password)
        return None


def normalize_instance_url(instance: str) -> str:
    """Accept a bare subdomain, host, or full URL and return `https://<host>[:port]`.

    Forces HTTPS and strips any path, query, fragment, or userinfo so only the
    host (and optional port) survive. This keeps the value safe to feed into the
    SSRF host check and to build Table API paths against.

    Examples: ``dev12345`` -> ``https://dev12345.service-now.com``;
    ``https://acme.service-now.com/foo?x=1`` -> ``https://acme.service-now.com``.
    """
    value = (instance or "").strip().rstrip("/")
    if not value:
        raise ValueError("ServiceNow instance URL is required")

    # Bare subdomain (no scheme, no dot) expands to the standard ServiceNow domain.
    if "://" not in value and "." not in value:
        return f"https://{value}.service-now.com"

    if "://" not in value:
        value = f"https://{value}"

    parsed = urlparse(value)
    host = parsed.hostname
    if not host:
        raise ValueError("Invalid ServiceNow instance URL")

    netloc = f"{host}:{parsed.port}" if parsed.port else host
    return f"https://{netloc}"


def _resolve_base_url(instance_url: str, team_id: int) -> str:
    """Normalize the instance URL and reject internal/private hosts (SSRF guard).

    ``_is_host_safe`` is a no-op outside of PostHog Cloud, so self-hosted
    instances can still reach any host.
    """
    base_url = normalize_instance_url(instance_url)
    hostname = urlparse(base_url).hostname or ""
    is_safe, error = _is_host_safe(hostname, team_id)
    if not is_safe:
        raise ValueError(error or "ServiceNow instance host is not allowed.")
    return base_url


def _format_datetime(value: Any) -> Optional[str]:
    """Format an incremental cursor value as ServiceNow's `YYYY-MM-DD HH:MM:SS` (UTC).

    With ``sysparm_display_value=false`` ServiceNow returns and filters audit
    timestamps in UTC, so we coerce everything to UTC before formatting.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d 00:00:00")
    return str(value)


def build_sysparm_query(cursor_field: Optional[str], last_value: Optional[str], sort_field: str) -> str:
    """Build a ServiceNow encoded query.

    Filters server-side on ``<cursor_field>>=<last_value>`` when incremental, and
    always pins an explicit ascending order on ``sort_field`` so pagination is stable
    and the pipeline's cursor watermark advances correctly.
    """
    clauses: list[str] = []
    if cursor_field and last_value:
        clauses.append(f"{cursor_field}>={last_value}")
    clauses.append(f"ORDERBY{sort_field}")
    return "^".join(clauses)


def validate_credentials(
    instance_url: str,
    auth: ServiceNowAuth,
    team_id: int,
    table: Optional[str] = None,
) -> tuple[bool, str | None]:
    try:
        base_url = _resolve_base_url(instance_url, team_id)
    except ValueError as exc:
        return False, str(exc)

    # Probe a cheap single-row read. At source-create (no specific table) we probe
    # `sys_user`; otherwise probe the requested table to confirm scope for it.
    probe_table = table or "sys_user"
    url = f"{base_url}/api/now/table/{probe_table}"
    params: dict[str, Any] = {"sysparm_limit": 1, "sysparm_fields": "sys_id"}

    try:
        # `instance_url` is user-supplied; don't follow redirects so a safe-looking
        # host can't bounce us to an internal one (SSRF guard).
        response = make_tracked_session().get(
            url,
            params=params,
            headers=auth.headers(),
            auth=auth.basic_auth(),
            timeout=10,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        return False, str(exc)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid ServiceNow credentials. Please check your instance URL and credentials."
    if response.status_code == 403:
        # Valid credentials, but no read access to this table. Accept at source-create
        # (the user may only intend to sync the tables they have access to) and only
        # surface the error when validating a specific table.
        if table is None:
            return True, None
        return False, f"Your ServiceNow account does not have read access to the '{table}' table."
    if response.status_code == 404:
        return False, f"ServiceNow table '{probe_table}' was not found on this instance."

    return False, f"ServiceNow returned an unexpected status ({response.status_code})."


def get_rows(
    base_url: str,
    table: str,
    auth: ServiceNowAuth,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ServiceNowResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    headers = auth.headers()
    basic_auth = auth.basic_auth()

    if should_use_incremental_field:
        cursor_field = incremental_field or "sys_updated_on"
        last_value = _format_datetime(db_incremental_field_last_value)
        sort_field = cursor_field
    else:
        cursor_field = None
        last_value = None
        # Partition by creation time, so a full refresh is ordered by the same stable field.
        sort_field = "sys_created_on"

    query = build_sysparm_query(cursor_field, last_value, sort_field)
    url = f"{base_url}/api/now/table/{table}"

    # One session for the whole paginated fetch so the TCP/TLS connection is reused
    # across pages. Disable urllib3-level retries — `tenacity` below is the single
    # retry mechanism (otherwise a 429 would be retried by both layers).
    session = make_tracked_session(retry=Retry(total=0))

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume_config.offset if resume_config else 0
    if resume_config:
        logger.debug(f"ServiceNow: resuming '{table}' from offset {offset}")

    @retry(
        retry=retry_if_exception_type((ServiceNowRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(page_offset: int) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "sysparm_query": query,
            "sysparm_limit": DEFAULT_PAGE_SIZE,
            "sysparm_offset": page_offset,
            "sysparm_display_value": "false",
            "sysparm_exclude_reference_link": "true",
        }
        # `base_url` is user-supplied; refuse redirects so a safe-looking host can't
        # bounce us to an internal one (SSRF guard).
        response = session.get(
            url,
            params=params,
            headers=headers,
            auth=basic_auth,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
        )

        if response.status_code == 429 or response.status_code >= 500:
            raise ServiceNowRetryableError(
                f"ServiceNow API error (retryable): status={response.status_code}, table={table}"
            )

        if 300 <= response.status_code < 400:
            raise ServiceNowError(
                f"ServiceNow returned an unexpected redirect (status={response.status_code}, table={table}); refusing to follow"
            )

        if not response.ok:
            logger.error(f"ServiceNow API error: status={response.status_code}, body={response.text}, table={table}")
            response.raise_for_status()

        return response.json().get("result", [])

    while True:
        rows = fetch_page(offset)
        if not rows:
            break

        yield rows

        offset += DEFAULT_PAGE_SIZE
        # Save state AFTER yielding so a crash re-yields the last batch (merge dedupes
        # on the primary key) rather than skipping it.
        resumable_source_manager.save_state(ServiceNowResumeConfig(offset=offset))

        if len(rows) < DEFAULT_PAGE_SIZE:
            break


def servicenow_source(
    instance_url: str,
    auth: ServiceNowAuth,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ServiceNowResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = SERVICENOW_ENDPOINTS[endpoint]
    base_url = _resolve_base_url(instance_url, team_id)

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            base_url=base_url,
            table=endpoint_config.table,
            auth=auth,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=[endpoint_config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="week",
        partition_keys=[endpoint_config.partition_key],
        sort_mode="asc",
    )
