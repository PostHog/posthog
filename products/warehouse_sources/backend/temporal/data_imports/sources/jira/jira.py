import re
import base64
import dataclasses
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.jira.settings import (
    JIRA_ENDPOINTS,
    JiraEndpointConfig,
)

REQUEST_TIMEOUT = 60
MAX_RETRIES = 5

# JQL only understands minute precision in this exact layout — it rejects ISO 8601 with seconds or a Z suffix.
JQL_DATETIME_FORMAT = "%Y-%m-%d %H:%M"

# JQL evaluates ``updated >= "..."`` in the Jira instance's timezone, but our stored watermark is UTC.
# Re-scan a day on every incremental run so a timezone offset can't open a gap; merge dedupes the overlap.
INCREMENTAL_LOOKBACK = timedelta(days=1)

_VALID_SUBDOMAIN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]*$")


class JiraRetryableError(Exception):
    pass


@dataclasses.dataclass
class JiraResumeConfig:
    next_page_token: Optional[str] = None
    start_at: Optional[int] = None
    # The JQL the token was minted for — a token replayed against a different JQL is a 400.
    jql: Optional[str] = None


def is_valid_subdomain(subdomain: str) -> bool:
    return bool(subdomain) and _VALID_SUBDOMAIN.match(subdomain) is not None


def base_url(subdomain: str) -> str:
    return f"https://{subdomain}.atlassian.net"


def _auth_headers(email: str, api_token: str) -> dict[str, str]:
    token = base64.b64encode(f"{email}:{api_token}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def _format_jql_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return (dt - INCREMENTAL_LOOKBACK).strftime(JQL_DATETIME_FORMAT)


# The enhanced ``/search/jql`` endpoint rejects unbounded queries (400 "Unbounded JQL queries are not
# allowed here"). On a full sync there's no watermark, so anchor to an epoch floor to keep the query bounded
# while still scanning every issue.
JQL_FLOOR_DATETIME = "1970-01-01 00:00"


def _build_issues_jql(incremental_field: str | None, last_value: Any) -> str:
    field = incremental_field or "updated"
    since = _format_jql_datetime(last_value) if last_value else JQL_FLOOR_DATETIME
    return f'{field} >= "{since}" ORDER BY {field} ASC'


def _extract_items(data: Any, data_key: str | None) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and data_key:
        return data.get(data_key) or []
    return []


def _normalize_issue(issue: dict[str, Any]) -> dict[str, Any]:
    """Lift the stable/incremental timestamps out of the nested ``fields`` object so the
    pipeline can read them as top-level columns for partitioning and the cursor watermark.

    ``fields`` is always present when we request ``fields=*all``; access it directly so a
    malformed response surfaces loudly rather than silently nulling the ``created`` partition key."""
    fields = issue["fields"]
    issue["created"] = fields.get("created")
    issue["updated"] = fields.get("updated")
    return issue


def validate_credentials(subdomain: str, email: str, api_token: str) -> tuple[bool, int | None]:
    """Probe ``/myself`` to confirm the token is genuine. Returns ``(ok, status_code)``."""
    if not is_valid_subdomain(subdomain):
        return False, None

    url = f"{base_url(subdomain)}/rest/api/3/myself"
    try:
        response = make_tracked_session(headers=_auth_headers(email, api_token)).get(url, timeout=10)
    except Exception:
        return False, None

    return response.status_code == 200, response.status_code


def get_rows(
    config: JiraEndpointConfig,
    subdomain: str,
    email: str,
    api_token: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JiraResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    session = make_tracked_session(headers=_auth_headers(email, api_token), redact_values=(api_token,))
    url = f"{base_url(subdomain)}{config.path}"

    @retry(
        retry=retry_if_exception_type((JiraRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(params: dict[str, Any]) -> Any:
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)

        if response.status_code == 429 or response.status_code >= 500:
            raise JiraRetryableError(f"Jira API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Jira API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    if config.pagination == "none":
        items = _extract_items(fetch_page({}), config.data_key)
        if items:
            yield items
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.pagination == "token":
        last_value = db_incremental_field_last_value if should_use_incremental_field else None
        jql = _build_issues_jql(incremental_field, last_value)

        # The JQL moves between runs as the watermark advances. Dropping a stale token is safe:
        # issues are scanned in incremental-field ASC order, so the watermark query resumes from
        # where the interrupted run got to (modulo the lookback overlap, which merge dedupes).
        next_page_token = resume.next_page_token if resume and resume.jql == jql else None
        if resume and resume.next_page_token and not next_page_token:
            logger.info(
                f"Discarding Jira resume token minted for a different JQL: saved={resume.jql!r}, current={jql!r}"
            )

        while True:
            params: dict[str, Any] = {"jql": jql, "maxResults": config.page_size, "fields": "*all"}
            if next_page_token:
                params["nextPageToken"] = next_page_token

            data = fetch_page(params)
            rows = [_normalize_issue(issue) for issue in data.get("issues", [])]
            if rows:
                yield rows

            next_page_token = data.get("nextPageToken")
            if not next_page_token or data.get("isLast"):
                break

            resumable_source_manager.save_state(JiraResumeConfig(next_page_token=next_page_token, jql=jql))
        return

    # offset pagination (startAt / maxResults)
    start_at = resume.start_at if resume and resume.start_at is not None else 0
    while True:
        data = fetch_page({"startAt": start_at, "maxResults": config.page_size})
        items = _extract_items(data, config.data_key)
        if not items:
            break

        yield items

        start_at += len(items)
        is_last = data.get("isLast") if isinstance(data, dict) else None
        if is_last or len(items) < config.page_size:
            break

        resumable_source_manager.save_state(JiraResumeConfig(start_at=start_at))


def jira_source(
    subdomain: str,
    email: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JiraResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = JIRA_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            config=config,
            subdomain=subdomain,
            email=email,
            api_token=api_token,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_key,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
