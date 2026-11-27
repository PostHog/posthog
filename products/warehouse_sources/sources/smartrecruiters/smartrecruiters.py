from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

from products.warehouse_sources.sources.sdk import (
    APIKeyAuth,
    BasePaginator,
    ClientConfig,
    Endpoint,
    JSONResponseCursorPaginator,
    OffsetPaginator,
    RESTAPIConfig,
    RESTClient,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    build_dependent_resource,
    create_response_hooks,
    frozen,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)
from products.warehouse_sources.sources.smartrecruiters.settings import (
    BASE_URL,
    PAGE_SIZE,
    SMARTRECRUITERS_ENDPOINTS,
    SmartRecruitersEndpointConfig,
)

# A one-row job search is the cheapest call every API key can make.
PROBE_URL = f"{BASE_URL}/jobs?limit=1"


@frozen
class SmartRecruitersResumeConfig:
    # Top-level endpoints: the next page id (cursor endpoints) or the next offset (offset endpoints).
    page_id: str | None = None
    offset: int | None = None
    # Fan-out endpoints resume by parent job: the parents already synced, the one in progress, and
    # its paginator state. See `_make_paginate_dependent_resource` in the shared rest_source.
    completed: list[str] | None = None
    current: str | None = None
    child_state: dict[str, Any] | None = None
    # Per-application endpoints resume by candidate page (None for the first page) and the last
    # (candidate, job) pair read on it (None when no pair on the page is read yet).
    candidate_page_id: str | None = None
    last_candidate_id: str | None = None
    last_job_id: str | None = None


def format_updated_after(value: Any) -> str:
    """Format a watermark as the `yyyy-MM-ddTHH:mm:ss.SSSZ` UTC string that `updatedAfter` takes."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return str(value)


def _paginator(config: SmartRecruitersEndpointConfig) -> BasePaginator:
    if config.pagination == "offset":
        return OffsetPaginator(limit=PAGE_SIZE, total_path="totalFound")
    if config.pagination == "single":
        return SinglePagePaginator()
    return JSONResponseCursorPaginator(cursor_path=config.cursor_path, cursor_param=config.cursor_param)


def _client_config(api_key: str, paginator: BasePaginator) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "name": "X-SmartToken", "api_key": api_key, "location": "header"},
        "paginator": paginator,
    }


def _build_params(
    config: SmartRecruitersEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = dict(config.params)
    if config.page_size_param is not None:
        params[config.page_size_param] = config.page_size
    if config.incremental_fields and should_use_incremental_field and db_incremental_field_last_value:
        params[config.incremental_param] = format_updated_after(db_incremental_field_last_value)
    elif config.initial_start is not None:
        params[config.incremental_param] = config.initial_start
    return params


def _make_source_response(
    config: SmartRecruitersEndpointConfig, items: Any, column_hints: Any = None
) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=column_hints,
    )


def _top_level_source(
    config: SmartRecruitersEndpointConfig,
    api_key: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SmartRecruitersResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key, _paginator(config)),
        "resource_defaults": {},
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": _build_params(config, should_use_incremental_field, db_incremental_field_last_value),
                    "data_selector": "content",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.page_id:
            initial_paginator_state = {"cursor": resume.page_id}
        elif resume is not None and resume.offset is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The framework calls this only while a next page remains.
        if not state:
            return
        if state.get("cursor"):
            resumable_source_manager.save_state(SmartRecruitersResumeConfig(page_id=str(state["cursor"])))
        elif state.get("offset") is not None:
            resumable_source_manager.save_state(SmartRecruitersResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return _make_source_response(config, lambda: resource, column_hints=resource.column_hints)


def _fanout_source(
    config: SmartRecruitersEndpointConfig,
    api_key: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SmartRecruitersResumeConfig],
) -> SourceResponse:
    assert config.fanout is not None
    parent_config = SMARTRECRUITERS_ENDPOINTS[config.fanout.parent_name]

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
                SmartRecruitersResumeConfig(
                    completed=state.get("completed"),
                    current=state.get("current"),
                    child_state=state.get("child_state"),
                )
            )

    parent_endpoint_extra: Endpoint = {"data_selector": "content"}
    child_endpoint_extra: Endpoint = {"data_selector": "content", "paginator": _paginator(config)}

    dependent_resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=SMARTRECRUITERS_ENDPOINTS,
            child_endpoint=config.name,
            fanout=config.fanout,
            client_config=_client_config(api_key, _paginator(parent_config)),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra=parent_endpoint_extra,
            child_endpoint_extra=child_endpoint_extra,
            # The parent page size rides in `fanout.parent_params`; the child endpoints take none.
            page_size_param=None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        ),
    )
    return _make_source_response(config, lambda: dependent_resource)


@frozen
class ApplicationPair:
    candidate_id: str
    job_id: str


def _application_pairs(candidates: list[dict[str, Any]]) -> list[ApplicationPair]:
    """List the candidate and job of each job application on a candidate listing page."""
    pairs: list[ApplicationPair] = []
    for candidate in candidates:
        assignments = [candidate.get("primaryAssignment"), *(candidate.get("secondaryAssignments") or [])]
        job_ids: list[str] = []
        for assignment in assignments:
            job_id = ((assignment or {}).get("job") or {}).get("id")
            if job_id and job_id not in job_ids:
                job_ids.append(job_id)
        pairs.extend(ApplicationPair(candidate_id=candidate["id"], job_id=job_id) for job_id in job_ids)
    return pairs


def _single_page(client: RESTClient, path: str, hooks: Any, **kwargs: Any) -> list[dict[str, Any]]:
    return next(client.paginate(path=path, paginator=SinglePagePaginator(), hooks=hooks, **kwargs), [])


def _application_rows(
    client: RESTClient, config: SmartRecruitersEndpointConfig, pair: ApplicationPair, hooks: Any
) -> list[dict[str, Any]]:
    candidate_id, job_id = pair.candidate_id, pair.job_id
    if config.name == "candidate_status_history":
        path = config.path.format(candidate_id=candidate_id, job_id=job_id)
        rows = _single_page(client, path, hooks, data_selector="content")
        return [{**row, "candidate_id": candidate_id, "job_id": job_id} for row in rows]

    if config.name == "reviews":
        return _single_page(client, config.path, hooks, params={"candidateId": candidate_id, "jobId": job_id})

    # The Interviews API takes the application id, which only the application details carry.
    applications = _single_page(client, f"/candidates/{candidate_id}/jobs/{job_id}", hooks)
    application_id = applications[0].get("applicationId") if applications else None
    if not application_id:
        return []
    return _single_page(client, config.path, hooks, params={"applicationId": application_id}, data_selector="content")


def _per_application_source(
    config: SmartRecruitersEndpointConfig,
    api_key: str,
    resumable_source_manager: ResumableSourceManager[SmartRecruitersResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Read an endpoint once for each job application, walking the candidate listing page by page.

    SmartRecruiters has no account-wide listing for status history, reviews or interviews. Each one
    takes a candidate and a job, so the job applications come from the candidate assignments.
    """
    client = RESTClient(
        base_url=BASE_URL,
        headers={"Accept": "application/json"},
        auth=APIKeyAuth(api_key=api_key, name="X-SmartToken", location="header"),
        # The key rides in a custom header, which `requests` does not strip on a redirect.
        allow_redirects=False,
    )
    # A candidate or application deleted between the listing and its child request has nothing to read.
    skip_deleted = create_response_hooks([{"status_code": 404, "action": "ignore"}])

    page_id: Optional[str] = None
    last_pair: Optional[ApplicationPair] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and (resume.candidate_page_id is not None or resume.last_candidate_id is not None):
            page_id = resume.candidate_page_id
            if resume.last_candidate_id is not None and resume.last_job_id is not None:
                last_pair = ApplicationPair(candidate_id=resume.last_candidate_id, job_id=resume.last_job_id)

    next_page: dict[str, Optional[str]] = {"cursor": None}

    def capture_next_page(state: Optional[dict[str, Any]], has_next_page: bool) -> None:
        next_page["cursor"] = state.get("cursor") if state and has_next_page else None

    for candidates in client.paginate(
        path="/candidates",
        params={"limit": PAGE_SIZE},
        paginator=JSONResponseCursorPaginator(cursor_path="nextPageId", cursor_param="pageId"),
        data_selector="content",
        initial_paginator_state={"cursor": page_id} if page_id else None,
        page_state_hook=capture_next_page,
    ):
        pairs = _application_pairs(candidates)
        next_page_id = next_page["cursor"]
        # The page can change between attempts, so a resume finds the last read pair by identity. When
        # that pair is gone, the page is read again from its start rather than risk skipping a pair.
        start = pairs.index(last_pair) + 1 if last_pair is not None and last_pair in pairs else 0
        if start >= len(pairs) and next_page_id is not None:
            resumable_source_manager.save_state(SmartRecruitersResumeConfig(candidate_page_id=next_page_id))
            resumable_source_manager.safe_point()

        for index in range(start, len(pairs)):
            rows = _application_rows(client, config, pairs[index], skip_deleted)
            if index == len(pairs) - 1 and next_page_id is not None:
                state = SmartRecruitersResumeConfig(candidate_page_id=next_page_id)
            else:
                state = SmartRecruitersResumeConfig(
                    candidate_page_id=page_id,
                    last_candidate_id=pairs[index].candidate_id,
                    last_job_id=pairs[index].job_id,
                )
            resumable_source_manager.save_state(state)
            if rows:
                yield rows
            else:
                resumable_source_manager.safe_point()

        page_id, last_pair = next_page_id, None


def smartrecruiters_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SmartRecruitersResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SMARTRECRUITERS_ENDPOINTS[endpoint]

    if config.fanout is not None:
        return _fanout_source(config, api_key, team_id, job_id, resumable_source_manager)

    if config.per_application:
        return _make_source_response(config, lambda: _per_application_source(config, api_key, resumable_source_manager))

    return _top_level_source(
        config,
        api_key,
        team_id,
        job_id,
        resumable_source_manager,
        should_use_incremental_field,
        db_incremental_field_last_value,
    )


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Probe a one-row job search. Returns `(ok, status_code)`, with `None` on a transport error."""
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        PROBE_URL,
        headers={"X-SmartToken": api_key, "Accept": "application/json"},
        # The key rides in a custom header, which `requests` does not strip on a redirect.
        allow_redirects=False,
    )
