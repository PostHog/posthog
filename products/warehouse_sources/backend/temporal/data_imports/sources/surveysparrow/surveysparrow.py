import dataclasses
from datetime import date, datetime
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.surveysparrow.settings import (
    SURVEYSPARROW_ENDPOINTS,
    SurveySparrowEndpointConfig,
)

# Page size used when enumerating survey ids for fan-out endpoints (/v3/surveys caps at 100).
SURVEY_LIST_PAGE_SIZE = 100


@dataclasses.dataclass
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


def _incremental_config(
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> IncrementalConfig | None:
    """Server-side date filter (e.g. ``date.gte``), only when we hold a cursor value.

    Mirrors the old behaviour: no filter on a first (full) sync, and the persisted watermark floored
    to a day the way SurveySparrow's date filters expect.
    """
    config = SURVEYSPARROW_ENDPOINTS[endpoint]
    if not should_use_incremental_field or db_incremental_field_last_value is None or not config.cutoff_param:
        return None
    return {
        "start_param": config.cutoff_param,
        "cursor_path": config.default_incremental_field or "completed_time",
        "convert": _format_cutoff,
    }


def _stamp_survey_id(row: dict[str, Any]) -> dict[str, Any]:
    # ``include_from_parent`` injects the parent survey's id as ``_surveys_id``; expose it under the
    # ``survey_id`` column the child rows carry. Rows already carry survey_id per the docs, but the
    # composite primary key must never be null, so stamp it from the parent regardless.
    if "_surveys_id" in row:
        row["survey_id"] = row.pop("_surveys_id")
    return row


def _client_config(access_token: str, base_url: str) -> ClientConfig:
    return {
        "base_url": base_url,
        # Auth (the Bearer token) is supplied via the framework auth config so its value is redacted
        # from every raised error and log sample; only the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": access_token},
        "paginator": HasNextPagePaginator(),
    }


def _simple_resource(config: SurveySparrowEndpointConfig) -> EndpointResource:
    return {
        "name": config.name,
        "endpoint": {
            "path": config.path,
            "params": {"limit": config.page_size, **config.extra_params},
            "data_selector": "data",
            # The old code raised a retryable error when a 200 body wasn't ``{"data": [...]}``;
            # keep that defensive treatment of an unexpected shape as transient.
            "data_selector_malformed_retryable": True,
        },
    }


def _parent_surveys_resource() -> EndpointResource:
    # Fan-out enumerates every survey id via a bare ``/v3/surveys`` listing (no cutoff): the child
    # endpoints must fan out over ALL surveys, never only the recently-modified slice.
    return {
        "name": "surveys",
        "endpoint": {
            "path": SURVEYSPARROW_ENDPOINTS["surveys"].path,
            "params": {"limit": SURVEY_LIST_PAGE_SIZE},
            "data_selector": "data",
        },
    }


def _fanout_child_resource(
    config: SurveySparrowEndpointConfig, incremental: IncrementalConfig | None
) -> EndpointResource:
    # SurveySparrow scopes /v3/responses and /v3/questions by a ``survey_id`` QUERY param. The
    # resolve mechanism only substitutes into the path, so embed the query param in the path with
    # the placeholder; the paginator appends its own page/limit params with ``&``.
    child_endpoint: Endpoint = {
        "path": f"{config.path}?survey_id={{survey_id}}",
        "params": {
            "survey_id": {"type": "resolve", "resource": "surveys", "field": "id"},
            "limit": config.page_size,
            **config.extra_params,
        },
        "data_selector": "data",
        # The path ends in a {survey_id} placeholder, which the engine would otherwise read as a
        # single-entity endpoint and force onto SinglePagePaginator; pin the page-number paginator.
        "paginator": HasNextPagePaginator(),
    }
    if incremental is not None:
        child_endpoint["incremental"] = incremental
    return {
        "name": config.name,
        "include_from_parent": ["id"],
        "endpoint": child_endpoint,
        "data_map": _stamp_survey_id,
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

    resource: Resource
    if not config.is_fanout:
        rest_config: RESTAPIConfig = {
            "client": client_config,
            "resource_defaults": {},
            "resources": [_simple_resource(config)],
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
        incremental = _incremental_config(endpoint, should_use_incremental_field, db_incremental_field_last_value)
        fanout_config: RESTAPIConfig = {
            "client": client_config,
            "resource_defaults": {},
            "resources": [_parent_surveys_resource(), _fanout_child_resource(config, incremental)],
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
        sort_mode="asc",
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
