import dataclasses
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
    PageNumberPaginator,
    Resource,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    make_tracked_session,
    rest_api_resource,
    rest_api_resources,
    validate_via_probe,
)
from products.warehouse_sources.sources.surveysparrow.settings import (
    SURVEYSPARROW_ENDPOINTS,
    FanoutParent,
    SurveySparrowEndpointConfig,
)


@dataclasses.dataclass(frozen=False)
class SurveySparrowResumeConfig:
    # Legacy fields from the pre-framework implementation, kept (with defaults) so a checkpoint
    # written by the old code still parses via ``dataclass(**saved)``. They are no longer written; a
    # loaded state carrying only these starts fresh (a full re-read, deduped on the primary key).
    page: int = 1
    remaining_survey_ids: Optional[list[int]] = None
    # Simple-resource (surveys/contacts/contact_lists) paginator snapshot: ``{"page": <next page>}``.
    paginator_state: Optional[dict[str, Any]] = None
    # Single-hop fan-out snapshot for a survey-scoped endpoint:
    # ``{"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}``.
    fanout_state: Optional[dict[str, Any]] = None


class HasNextPagePaginator(PageNumberPaginator):
    """Page-number pagination keyed off SurveySparrow's body ``has_next_page`` flag.

    Each list response carries ``has_next_page: bool``; a false/missing flag — or an empty page —
    is the last one (the empty-page guard stops a stale flag looping forever, and matches endpoints
    like ``/v3/contact_lists`` that omit the flag entirely). Page/limit params and resume snapshots
    reuse ``PageNumberPaginator`` with 1-based pages.
    """

    def __init__(self) -> None:
        super().__init__(base_page=1, page=1, page_param="page")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return
        try:
            body = response.json()
        except Exception:
            body = None
        if not (isinstance(body, dict) and body.get("has_next_page")):
            self._has_next_page = False
            return
        self.page += 1
        self._has_next_page = True


def _get_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _format_cutoff(value: Any) -> str:
    """Format the incremental watermark for SurveySparrow's date filters.

    The docs only specify ``YYYY-MM-DD`` dates for these filters, so the watermark is floored to
    its day: each incremental sync re-fetches up to one day of overlap, which merge dedupes.
    """
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _format_datetime_cutoff(value: Any) -> str:
    """Format the incremental watermark for filters that take ``YYYY-MM-DDTHH:MM:SS``.

    The docs don't say which timezone the filter is read in, so the cutoff starts one day before
    the watermark. That covers any UTC offset, and merge dedupes the overlap.
    """
    if isinstance(value, datetime):
        moment = value.astimezone(UTC) if value.tzinfo else value
    elif isinstance(value, date):
        moment = datetime.combine(value, time.min)
    else:
        return str(value)
    return (moment - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")


def _incremental_config(
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> IncrementalConfig | None:
    """Server-side date filter (e.g. ``date.gte``), only when we hold a cursor value.

    No filter on a first (full) sync. The persisted watermark is formatted the way the endpoint's
    filter expects: floored to a day, or a full timestamp.
    """
    config = SURVEYSPARROW_ENDPOINTS[endpoint]
    if not should_use_incremental_field or db_incremental_field_last_value is None or not config.cutoff_param:
        return None
    return {
        "start_param": config.cutoff_param,
        "cursor_path": config.default_incremental_field or "completed_time",
        "convert": _format_datetime_cutoff if config.cutoff_includes_time else _format_cutoff,
    }


def _parent_id_stamper(parent: FanoutParent) -> Callable[[dict[str, Any]], dict[str, Any]]:
    # ``include_from_parent`` injects the parent's id as ``_<parent>_id``; expose it under the column
    # the child rows carry. Rows already carry it per the docs, but the composite primary key must
    # never be null, so stamp it from the parent regardless.
    injected_key = f"_{parent.name}_id"

    def stamp(row: dict[str, Any]) -> dict[str, Any]:
        if injected_key in row:
            row[parent.child_column] = row.pop(injected_key)
        return row

    return stamp


def _client_config(access_token: str, base_url: str) -> ClientConfig:
    return {
        "base_url": base_url,
        # Auth (the Bearer token) is supplied via the framework auth config so its value is redacted
        # from every raised error and log sample; only the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": access_token},
        "paginator": HasNextPagePaginator(),
    }


def _simple_resource(config: SurveySparrowEndpointConfig, incremental: IncrementalConfig | None) -> EndpointResource:
    endpoint: Endpoint = {
        "path": config.path,
        "params": {"limit": config.page_size, **config.extra_params} if config.paginated else {**config.extra_params},
        "data_selector": "data",
        # The old code raised a retryable error when a 200 body wasn't ``{"data": [...]}``;
        # keep that defensive treatment of an unexpected shape as transient.
        "data_selector_malformed_retryable": True,
    }
    if not config.paginated:
        endpoint["paginator"] = "single_page"
    if incremental is not None:
        endpoint["incremental"] = incremental
    return {"name": config.name, "endpoint": endpoint}


def _parent_resource(parent: FanoutParent) -> EndpointResource:
    # The parent listing has no cutoff: children must fan out over ALL parents, never only the
    # recently-modified slice.
    return {
        "name": parent.name,
        "endpoint": {
            "path": parent.path,
            "params": {"limit": parent.page_size},
            "data_selector": "data",
        },
    }


def _fanout_child_resource(
    config: SurveySparrowEndpointConfig, parent: FanoutParent, incremental: IncrementalConfig | None
) -> EndpointResource:
    # The resolve mechanism only substitutes into the path, so a parent id that SurveySparrow takes
    # as a QUERY param (``survey_id``, ``app_platform_id``) sits in the path with its placeholder;
    # the paginator appends its own page/limit params with ``&``.
    child_endpoint: Endpoint = {
        "path": config.path,
        "params": {
            parent.child_column: {"type": "resolve", "resource": parent.name, "field": "id"},
            "limit": config.page_size,
            **config.extra_params,
        },
        "data_selector": "data",
        # A path ending in a placeholder would otherwise be read as a single-entity endpoint and
        # forced onto SinglePagePaginator; pin the page-number paginator.
        "paginator": HasNextPagePaginator(),
    }
    if incremental is not None:
        child_endpoint["incremental"] = incremental
    return {
        "name": config.name,
        "include_from_parent": ["id"],
        "endpoint": child_endpoint,
        "data_map": _parent_id_stamper(parent),
    }


def surveysparrow_source(
    access_token: str,
    base_url: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SurveySparrowResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SURVEYSPARROW_ENDPOINTS[endpoint]
    client_config = _client_config(access_token, base_url)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    incremental = _incremental_config(endpoint, should_use_incremental_field, db_incremental_field_last_value)

    resource: Resource
    if config.parent is None:
        rest_config: RESTAPIConfig = {
            "client": client_config,
            "resource_defaults": {},
            "resources": [_simple_resource(config, incremental)],
        }

        def save_simple(state: Optional[dict[str, Any]]) -> None:
            # Persist only when a next page remains; save AFTER a page is yielded so a crash resumes
            # at the next page rather than re-reading from the top.
            if state is not None:
                resumable_source_manager.save_state(SurveySparrowResumeConfig(paginator_state=state))

        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_simple,
            initial_paginator_state=(resume.paginator_state if resume is not None else None),
        )
    else:
        fanout_config: RESTAPIConfig = {
            "client": client_config,
            "resource_defaults": {},
            "resources": [
                _parent_resource(config.parent),
                _fanout_child_resource(config, config.parent, incremental),
            ],
        }

        def save_fanout(state: Optional[dict[str, Any]]) -> None:
            if state is not None:
                resumable_source_manager.save_state(SurveySparrowResumeConfig(fanout_state=state))

        resources = rest_api_resources(
            fanout_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_fanout,
            initial_paginator_state=(resume.fanout_state if resume is not None else None),
        )
        resource = next(r for r in resources if r.name == endpoint)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(access_token: str, base_url: str) -> tuple[bool, str | None]:
    """Cheap probe against ``/v3/surveys`` to confirm the token is genuine for this data center."""
    ok, status = validate_via_probe(
        lambda: make_tracked_session(headers=_get_headers(access_token), redact_values=(access_token,)),
        f"{base_url}/v3/surveys",
        timeout=15,
    )
    if ok:
        return True, None
    if status == 401:
        return (
            False,
            "Invalid SurveySparrow access token. Check the token and that the data center matches your account.",
        )
    if status == 403:
        return False, "Your SurveySparrow access token is missing the required scopes."
    if status is None:
        return False, "Could not connect to SurveySparrow"
    return False, f"SurveySparrow API returned status {status}"
