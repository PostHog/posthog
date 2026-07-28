import re
import base64
import dataclasses
from datetime import date, datetime, timedelta
from typing import Any, Optional

from requests import Response
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.jira.settings import JIRA_ENDPOINTS

# JQL only understands minute precision in this exact layout — it rejects ISO 8601 with seconds or a Z suffix.
JQL_DATETIME_FORMAT = "%Y-%m-%d %H:%M"

# JQL evaluates ``updated >= "..."`` in the Jira instance's timezone, but our stored watermark is UTC.
# Re-scan a day on every incremental run so a timezone offset can't open a gap; merge dedupes the overlap.
INCREMENTAL_LOOKBACK = timedelta(days=1)

# The enhanced ``/search/jql`` endpoint rejects unbounded queries (400 "Unbounded JQL queries are not
# allowed here"). On a full sync there's no watermark, so anchor to an epoch floor to keep the query bounded
# while still scanning every issue.
JQL_FLOOR_DATETIME = "1970-01-01 00:00"

_VALID_SUBDOMAIN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]*$")


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


def _build_issues_jql(incremental_field: str | None, last_value: Any) -> str:
    field = incremental_field or "updated"
    since = _format_jql_datetime(last_value) if last_value else JQL_FLOOR_DATETIME
    return f'{field} >= "{since}" ORDER BY {field} ASC'


def _normalize_issue(issue: dict[str, Any]) -> dict[str, Any]:
    """Lift the stable/incremental timestamps out of the nested ``fields`` object so the
    pipeline can read them as top-level columns for partitioning and the cursor watermark.

    ``fields`` is always present when we request ``fields=*all``; access it directly so a
    malformed response surfaces loudly rather than silently nulling the ``created`` partition key."""
    fields = issue["fields"]
    issue["created"] = fields.get("created")
    issue["updated"] = fields.get("updated")
    return issue


class JiraTokenPaginator(JSONResponseCursorPaginator):
    """Enhanced ``/search/jql`` cursor pagination. Like the base cursor paginator (opaque
    ``nextPageToken`` echoed back on the next request), but also honors Jira's ``isLast`` flag so
    the final page ends the walk even if a token is still present in the body."""

    def __init__(self) -> None:
        super().__init__(cursor_path="nextPageToken", cursor_param="nextPageToken")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page:
            try:
                body = response.json()
            except Exception:
                return
            if isinstance(body, dict) and body.get("isLast"):
                self._has_next_page = False


class JiraOffsetPaginator(OffsetPaginator):
    """Classic ``startAt`` / ``maxResults`` paging that also stops on Jira's ``isLast`` flag, so a
    final page that happens to be exactly ``maxResults`` long doesn't cost one extra empty request."""

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page:
            try:
                body = response.json()
            except Exception:
                return
            if isinstance(body, dict) and body.get("isLast"):
                self._has_next_page = False


def validate_credentials(subdomain: str, email: str, api_token: str) -> tuple[bool, int | None]:
    """Probe ``/myself`` to confirm the token is genuine. Returns ``(ok, status_code)``."""
    if not is_valid_subdomain(subdomain):
        return False, None

    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{base_url(subdomain)}/rest/api/3/myself",
        headers=_auth_headers(email, api_token),
    )


def jira_source(
    subdomain: str,
    email: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JiraResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = JIRA_ENDPOINTS[endpoint]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_paginator_state: Optional[dict[str, Any]] = None

    params: dict[str, Any] = {}
    # The JQL the token walk was minted for, captured for the resume checkpoint (token endpoint only).
    issues_jql: Optional[str] = None
    paginator: SinglePagePaginator | JiraTokenPaginator | JiraOffsetPaginator

    if config.pagination == "none":
        paginator = SinglePagePaginator()
    elif config.pagination == "token":
        last_value = db_incremental_field_last_value if should_use_incremental_field else None
        issues_jql = _build_issues_jql(incremental_field, last_value)
        params = {"jql": issues_jql, "maxResults": config.page_size, "fields": "*all"}
        paginator = JiraTokenPaginator()

        # The JQL moves between runs as the watermark advances. A token minted for a different JQL is a
        # 400, so drop it: issues are scanned in incremental-field ASC order, so the watermark query
        # resumes from where the interrupted run got to (modulo the lookback overlap, which merge dedupes).
        if resume and resume.next_page_token and resume.jql == issues_jql:
            initial_paginator_state = {"cursor": resume.next_page_token}
        elif resume and resume.next_page_token:
            logger.info(
                f"Discarding Jira resume token minted for a different JQL: saved={resume.jql!r}, current={issues_jql!r}"
            )
    else:  # offset
        paginator = JiraOffsetPaginator(
            limit=config.page_size,
            offset_param="startAt",
            limit_param="maxResults",
            total_path=None,
        )
        if resume and resume.start_at is not None:
            initial_paginator_state = {"offset": resume.start_at}

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(subdomain),
            # Auth (Basic) is supplied via the framework auth config so the api_token is redacted from
            # logs and raised error messages; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "http_basic", "username": email, "password": api_token},
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # ``None`` (bare-array endpoints) means the whole body is the row list.
                    "data_selector": config.data_key,
                    "paginator": paginator,
                },
                # Issues nest the partition/cursor timestamps inside ``fields``; lift them to the root.
                **({"data_map": _normalize_issue} if endpoint == "issues" else {}),
            }
        ],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded (only when a next page remains) so a crash re-yields the last
        # page — merge dedupes — rather than skipping it.
        if not state:
            return
        if config.pagination == "token":
            cursor = state.get("cursor")
            if cursor is not None:
                resumable_source_manager.save_state(JiraResumeConfig(next_page_token=cursor, jql=issues_jql))
        elif config.pagination == "offset":
            offset = state.get("offset")
            if offset is not None:
                resumable_source_manager.save_state(JiraResumeConfig(start_at=int(offset)))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_key,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
