import re
import base64
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional, cast

from requests import Response
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    create_response_hooks,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.jira.settings import (
    DEFAULT_PAGE_SIZE,
    JIRA_ENDPOINTS,
    JiraEndpointConfig,
)

# JQL only understands minute precision in this exact layout — it rejects ISO 8601 with seconds or a Z suffix.
JQL_DATETIME_FORMAT = "%Y-%m-%d %H:%M"

# JQL evaluates ``updated >= "..."`` in the Jira instance's timezone, but our stored watermark is UTC.
# Re-scan a day on every incremental run so a timezone offset can't open a gap; merge dedupes the overlap.
INCREMENTAL_LOOKBACK = timedelta(days=1)

# The enhanced ``/search/jql`` endpoint rejects unbounded queries (400 "Unbounded JQL queries are not
# allowed here"). On a full sync there's no watermark, so anchor to an epoch floor to keep the query bounded
# while still scanning every issue.
JQL_FLOOR_DATETIME = "1970-01-01 00:00"

# ``/worklog/updated`` returns worklogs updated strictly after ``since``. Re-read a minute so a worklog
# that shares the watermark's timestamp is not skipped; merge dedupes the overlap.
WORKLOG_SINCE_OVERLAP = timedelta(minutes=1)

SEARCH_JQL_PATH = "/rest/api/3/search/jql"

SPRINT_FIELD_SCHEMA = "com.pyxis.greenhopper.jira:gh-sprint"
SPRINT_ISSUES_JQL = f'sprint is not EMPTY AND created >= "{JQL_FLOOR_DATETIME}" ORDER BY created ASC'

_VALID_SUBDOMAIN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]*$")


@dataclasses.dataclass(frozen=False)
class JiraResumeConfig:
    next_page_token: Optional[str] = None
    start_at: Optional[int] = None
    # The JQL the token was minted for — a token replayed against a different JQL is a 400.
    jql: Optional[str] = None
    # The ``since`` (epoch milliseconds) of the next ``/worklog/updated`` page.
    worklog_since: Optional[int] = None


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


class JiraWorklogPaginator(JSONResponseCursorPaginator):
    """``/worklog/updated`` paging: the next page starts ``since`` the current page's ``until``, and
    ``lastPage`` ends the walk."""

    def __init__(self) -> None:
        super().__init__(cursor_path="until", cursor_param="since", raise_on_repeated_cursor=True)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        # Check ``lastPage`` first: a final page can repeat the previous ``until``, which the
        # repeated-cursor guard would reject.
        try:
            body = response.json()
        except Exception:
            body = None
        if isinstance(body, dict) and body.get("lastPage"):
            self._has_next_page = False
            return
        super().update_state(response, data)


def _to_epoch_millis(value: Any) -> int:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)


def _worklog_since(last_value: Any) -> int:
    if not last_value:
        return 0
    return max(_to_epoch_millis(last_value) - int(WORKLOG_SINCE_OVERLAP.total_seconds() * 1000), 0)


def _sprint_issue_rows(issue: dict[str, Any], sprint_field: str) -> list[dict[str, Any]]:
    sprints = (issue.get("fields") or {}).get(sprint_field) or []
    return [
        {"sprint_id": sprint["id"], "issue_id": issue["id"], "issue_key": issue.get("key")}
        for sprint in sprints
        if isinstance(sprint, dict) and sprint.get("id") is not None
    ]


def _find_sprint_field(fields: list[Any]) -> Optional[str]:
    for field in fields:
        if isinstance(field, dict) and (field.get("schema") or {}).get("custom") == SPRINT_FIELD_SCHEMA:
            return field.get("id")
    return None


def _changelog_rows(
    issue_changelogs: list[dict[str, Any]], created_floor_millis: Optional[int]
) -> list[dict[str, Any]]:
    return [
        {**history, "issue_id": issue_changelog.get("issueId")}
        for issue_changelog in issue_changelogs
        for history in issue_changelog.get("changeHistories") or []
        if created_floor_millis is None or _created_at_or_after(history, created_floor_millis)
    ]


def _created_at_or_after(history: dict[str, Any], floor_millis: int) -> bool:
    try:
        return _to_epoch_millis(history["created"]) >= floor_millis
    except (KeyError, TypeError, ValueError):
        return True


def _comment_rows(issue: dict[str, Any], comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**comment, "issue_id": issue["id"], "issue_key": issue.get("key")} for comment in comments]


def _resume_token_state(
    resumable_source_manager: ResumableSourceManager[JiraResumeConfig], jql: str
) -> Optional[dict[str, Any]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume and resume.next_page_token and resume.jql == jql:
        return {"cursor": resume.next_page_token}
    return None


def _rest_client(subdomain: str, email: str, api_token: str) -> RESTClient:
    return RESTClient(
        base_url=base_url(subdomain),
        headers={"Accept": "application/json"},
        auth=HttpBasicAuth(email, api_token),
    )


def _client_config(subdomain: str, email: str, api_token: str) -> ClientConfig:
    return {
        "base_url": base_url(subdomain),
        # Auth (Basic) is supplied via the framework auth config so the api_token is redacted from
        # logs and raised error messages; only the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "http_basic", "username": email, "password": api_token},
    }


def _offset_paginator(config: JiraEndpointConfig) -> JiraOffsetPaginator:
    return JiraOffsetPaginator(
        limit=config.page_size,
        offset_param="startAt",
        limit_param="maxResults",
        total_path=None,
    )


def _worklogs_source(
    subdomain: str,
    email: str,
    api_token: str,
    resumable_source_manager: ResumableSourceManager[JiraResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    config = JIRA_ENDPOINTS["worklogs"]
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    since = (
        resume.worklog_since
        if resume and resume.worklog_since is not None
        else _worklog_since(db_incremental_field_last_value)
    )

    def items() -> Iterator[list[dict[str, Any]]]:
        client = _rest_client(subdomain, email, api_token)
        next_page: dict[str, Any] = {}

        def stage_next_page(state: Optional[dict[str, Any]], has_next: bool) -> None:
            next_page["since"] = state.get("cursor") if state and has_next else None

        for changed in client.paginate(
            config.path,
            params={"since": since},
            paginator=JiraWorklogPaginator(),
            data_selector="values",
            page_state_hook=stage_next_page,
        ):
            ids = [entry["worklogId"] for entry in changed if entry.get("worklogId") is not None]
            worklogs: list[dict[str, Any]] = []
            if ids:
                for page in client.paginate(
                    "/rest/api/3/worklog/list",
                    method="post",
                    json={"ids": ids},
                    paginator=SinglePagePaginator(),
                ):
                    worklogs.extend(page)
            # ``/worklog/list`` does not promise the request order; keep the feed's oldest-first order
            # so the ``updated`` watermark only moves forward.
            position = {str(worklog_id): index for index, worklog_id in enumerate(ids)}
            worklogs.sort(key=lambda worklog: position.get(str(worklog.get("id")), len(position)))

            if next_page.get("since") is not None:
                resumable_source_manager.save_state(JiraResumeConfig(worklog_since=int(next_page["since"])))
            if worklogs:
                yield worklogs
            else:
                resumable_source_manager.safe_point()

    return SourceResponse(
        name="worklogs",
        items=items,
        primary_keys=config.primary_key,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )


def _sprint_issues_source(
    subdomain: str,
    email: str,
    api_token: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JiraResumeConfig],
) -> SourceResponse:
    config = JIRA_ENDPOINTS["sprint_issues"]
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_paginator_state = (
        {"cursor": resume.next_page_token}
        if resume and resume.next_page_token and resume.jql == SPRINT_ISSUES_JQL
        else None
    )

    def items() -> Iterator[list[dict[str, Any]]]:
        client = _rest_client(subdomain, email, api_token)
        fields = [
            field for page in client.paginate("/rest/api/3/field", paginator=SinglePagePaginator()) for field in page
        ]
        sprint_field = _find_sprint_field(fields)
        if sprint_field is None:
            # Sites without Jira Software have no Sprint field, so there is no membership to sync.
            logger.info("Jira site has no Sprint field, skipping sprint_issues")
            return

        next_page: dict[str, Any] = {}

        def stage_next_page(state: Optional[dict[str, Any]], has_next: bool) -> None:
            next_page["cursor"] = state.get("cursor") if state and has_next else None

        for issues in client.paginate(
            config.path,
            params={"jql": SPRINT_ISSUES_JQL, "maxResults": config.page_size, "fields": sprint_field},
            paginator=JiraTokenPaginator(),
            data_selector=config.data_key,
            initial_paginator_state=initial_paginator_state,
            page_state_hook=stage_next_page,
        ):
            rows = [row for issue in issues for row in _sprint_issue_rows(issue, sprint_field)]
            if next_page.get("cursor") is not None:
                resumable_source_manager.save_state(
                    JiraResumeConfig(next_page_token=next_page["cursor"], jql=SPRINT_ISSUES_JQL)
                )
            if rows:
                yield rows
            else:
                resumable_source_manager.safe_point()

    return SourceResponse(
        name="sprint_issues",
        items=items,
        primary_keys=config.primary_key,
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )


def _issue_changelogs_source(
    subdomain: str,
    email: str,
    api_token: str,
    resumable_source_manager: ResumableSourceManager[JiraResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    config = JIRA_ENDPOINTS["issue_changelogs"]
    # A new changelog entry moves the issue's ``updated``, so issues updated since the watermark carry
    # every changelog entry created since it.
    jql = _build_issues_jql("updated", db_incremental_field_last_value)
    initial_paginator_state = _resume_token_state(resumable_source_manager, jql)
    # Bulkfetch returns the whole history of each issue. Changelog entries never change, so an
    # incremental run keeps only the ones inside the JQL lookback window.
    created_floor_millis = (
        _to_epoch_millis(db_incremental_field_last_value) - int(INCREMENTAL_LOOKBACK.total_seconds() * 1000)
        if db_incremental_field_last_value
        else None
    )

    def items() -> Iterator[list[dict[str, Any]]]:
        client = _rest_client(subdomain, email, api_token)
        next_page: dict[str, Any] = {}

        def stage_next_page(state: Optional[dict[str, Any]], has_next: bool) -> None:
            next_page["cursor"] = state.get("cursor") if state and has_next else None

        def stage_more_changelogs(_state: Optional[dict[str, Any]], has_next: bool) -> None:
            next_page["more_changelogs"] = has_next

        def checkpoint() -> None:
            if next_page.get("cursor") is not None:
                resumable_source_manager.save_state(JiraResumeConfig(next_page_token=next_page["cursor"], jql=jql))

        for issues in client.paginate(
            SEARCH_JQL_PATH,
            params={"jql": jql, "maxResults": config.page_size, "fields": "id"},
            paginator=JiraTokenPaginator(),
            data_selector="issues",
            initial_paginator_state=initial_paginator_state,
            page_state_hook=stage_next_page,
        ):
            issue_ids = [str(issue["id"]) for issue in issues if issue.get("id") is not None]
            if not issue_ids:
                checkpoint()
                resumable_source_manager.safe_point()
                continue

            for issue_changelogs in client.paginate(
                config.path,
                method="post",
                json={"issueIdsOrKeys": issue_ids, "maxResults": config.page_size},
                paginator=JSONResponseCursorPaginator(
                    cursor_path="nextPageToken", cursor_param="nextPageToken", param_location="json"
                ),
                data_selector="issueChangeLogs",
                page_state_hook=stage_more_changelogs,
            ):
                rows = _changelog_rows(issue_changelogs, created_floor_millis)
                # The next issue page is only safe to resume from once this page's last changelogs are in hand.
                if not next_page["more_changelogs"]:
                    checkpoint()
                if rows:
                    yield rows
                else:
                    resumable_source_manager.safe_point()

    return SourceResponse(
        name="issue_changelogs",
        items=items,
        primary_keys=config.primary_key,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def _issue_comments_source(
    subdomain: str,
    email: str,
    api_token: str,
    resumable_source_manager: ResumableSourceManager[JiraResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    config = JIRA_ENDPOINTS["issue_comments"]
    # Adding or editing a comment moves the issue's ``updated``, whichever comment field is the cursor.
    jql = _build_issues_jql("updated", db_incremental_field_last_value)
    initial_paginator_state = _resume_token_state(resumable_source_manager, jql)

    def items() -> Iterator[list[dict[str, Any]]]:
        client = _rest_client(subdomain, email, api_token)
        # An issue deleted after the search answers 404, which reads as an issue with no comments.
        skip_deleted_issue = create_response_hooks(
            [{"status_code": 404, "action": "ignore"}], resource_name="issue_comments"
        )
        next_page: dict[str, Any] = {}

        def stage_next_page(state: Optional[dict[str, Any]], has_next: bool) -> None:
            next_page["cursor"] = state.get("cursor") if state and has_next else None

        for issues in client.paginate(
            config.path,
            params={"jql": jql, "maxResults": config.page_size, "fields": "comment"},
            paginator=JiraTokenPaginator(),
            data_selector=config.data_key,
            initial_paginator_state=initial_paginator_state,
            page_state_hook=stage_next_page,
        ):
            rows: list[dict[str, Any]] = []
            for issue in issues:
                embedded = (issue.get("fields") or {}).get("comment") or {}
                comments = embedded.get("comments") or []
                if (embedded.get("total") or 0) <= len(comments):
                    rows.extend(_comment_rows(issue, comments))
                    continue

                # The search embeds a capped list, so read the whole list for this issue.
                for page in client.paginate(
                    f"/rest/api/3/issue/{issue['id']}/comment",
                    params={"orderBy": "created"},
                    paginator=JiraOffsetPaginator(
                        limit=DEFAULT_PAGE_SIZE, offset_param="startAt", limit_param="maxResults", total_path="total"
                    ),
                    data_selector="comments",
                    hooks=skip_deleted_issue,
                ):
                    rows.extend(_comment_rows(issue, page))
                    # Hand rows on after each request so a worker shutdown can stop between them.
                    if rows:
                        yield rows
                        rows = []
                    else:
                        resumable_source_manager.safe_point()

            if next_page.get("cursor") is not None:
                resumable_source_manager.save_state(JiraResumeConfig(next_page_token=next_page["cursor"], jql=jql))
            if rows:
                yield rows
            else:
                resumable_source_manager.safe_point()

    return SourceResponse(
        name="issue_comments",
        items=items,
        primary_keys=config.primary_key,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def _fanout_resource(endpoint: str, subdomain: str, email: str, api_token: str, team_id: int, job_id: str) -> Resource:
    config = JIRA_ENDPOINTS[endpoint]
    assert config.fanout is not None
    parent_config = JIRA_ENDPOINTS[config.fanout.parent_name]

    return cast(
        Resource,
        build_dependent_resource(
            endpoint_configs=JIRA_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=_client_config(subdomain, email, api_token),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra={
                "data_selector": parent_config.data_key,
                "paginator": _offset_paginator(parent_config),
            },
            child_endpoint_extra={"data_selector": config.data_key, "paginator": _offset_paginator(config)},
            page_size_param=None,
        ),
    )


def _fanout_source(
    endpoint: str, subdomain: str, email: str, api_token: str, team_id: int, job_id: str
) -> SourceResponse:
    resource = _fanout_resource(endpoint, subdomain, email, api_token, team_id, job_id)
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=JIRA_ENDPOINTS[endpoint].primary_key,
        partition_count=1,
        partition_size=1,
    )


def _sprints_source(subdomain: str, email: str, api_token: str, team_id: int, job_id: str) -> SourceResponse:
    config = JIRA_ENDPOINTS["sprints"]
    resource = _fanout_resource("sprints", subdomain, email, api_token, team_id, job_id)

    seen: set[Any] = set()

    def first_listing(sprint: dict[str, Any]) -> bool:
        if sprint.get("id") in seen:
            return False
        seen.add(sprint.get("id"))
        return True

    resource.add_filter(first_listing)

    return SourceResponse(
        name="sprints",
        items=lambda: resource,
        primary_keys=config.primary_key,
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )


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

    if endpoint == "worklogs":
        return _worklogs_source(
            subdomain,
            email,
            api_token,
            resumable_source_manager,
            db_incremental_field_last_value if should_use_incremental_field else None,
        )
    if endpoint == "sprint_issues":
        return _sprint_issues_source(subdomain, email, api_token, logger, resumable_source_manager)
    if endpoint == "sprints":
        return _sprints_source(subdomain, email, api_token, team_id, job_id)
    if endpoint in ("group_members", "versions"):
        return _fanout_source(endpoint, subdomain, email, api_token, team_id, job_id)
    if endpoint == "issue_changelogs":
        return _issue_changelogs_source(
            subdomain,
            email,
            api_token,
            resumable_source_manager,
            db_incremental_field_last_value if should_use_incremental_field else None,
        )
    if endpoint == "issue_comments":
        return _issue_comments_source(
            subdomain,
            email,
            api_token,
            resumable_source_manager,
            db_incremental_field_last_value if should_use_incremental_field else None,
        )

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
        paginator = _offset_paginator(config)
        if resume and resume.start_at is not None:
            initial_paginator_state = {"offset": resume.start_at}

    rest_config: RESTAPIConfig = {
        "client": _client_config(subdomain, email, api_token),
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
