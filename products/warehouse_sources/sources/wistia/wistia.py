import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.sources.sdk import (
    BearerTokenAuth,
    ClientConfig,
    Endpoint,
    EndpointResource,
    PageNumberPaginator,
    Resource,
    RESTAPIConfig,
    RESTClient,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    make_tracked_session,
    rest_api_resource,
    rest_api_resources,
    validate_via_probe,
)
from products.warehouse_sources.sources.wistia.settings import (
    ACCOUNT_STATS_HISTORY_START,
    ACCOUNT_STATS_WINDOW_DAYS,
    PAGE_SIZE,
    WISTIA_API_VERSION_HEADER,
    WISTIA_BASE_URL,
    WISTIA_ENDPOINTS,
    WistiaEndpointConfig,
)

FIRST_PAGE = 1


@dataclasses.dataclass(frozen=False)
class WistiaResumeConfig:
    # Next page of a top-level list endpoint.
    page: Optional[int] = None
    # Framework fan-out checkpoint: {"completed": [...], "current": ..., "child_state": ...}.
    fanout_state: Optional[dict[str, Any]] = None
    # First day of the next account stats window, as YYYY-MM-DD.
    window_start: Optional[str] = None


class WistiaPageNumberPaginator(PageNumberPaginator):
    """Page-number paginator that also stops on a short page.

    Wistia list endpoints return a bare JSON array with no total count, so a page with fewer
    than `per_page` rows is the last one. Stopping there saves one empty-page request.
    """

    def __init__(self, page_size: int = PAGE_SIZE) -> None:
        super().__init__(base_page=FIRST_PAGE)
        self.page_size = page_size

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and data is not None and len(data) < self.page_size:
            self._has_next_page = False


def _client_config(api_token: str, api_version: str) -> ClientConfig:
    return {
        "base_url": WISTIA_BASE_URL,
        "headers": {WISTIA_API_VERSION_HEADER: api_version, "Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_token},
    }


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


# `cursor` is only valid for the sort order of one request, so it has no meaning in the warehouse.
# Webinar host and panelist links give access to the webinar without a login, so they must not
# reach every reader of the warehouse table.
_DROPPED_FIELDS = ("cursor", "host_link", "panelist_link")


def _drop_fields(row: dict[str, Any]) -> dict[str, Any]:
    for field_name in _DROPPED_FIELDS:
        row.pop(field_name, None)
    return row


def validate_credentials(api_token: str, api_version: str) -> tuple[bool, str | None]:
    # GET /account accepts a token with any permission, so a 401 here means the token itself is
    # wrong. Wistia also returns 401 for a missing permission on other endpoints.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{WISTIA_BASE_URL}/account",
        headers={
            "Authorization": f"Bearer {api_token}",
            WISTIA_API_VERSION_HEADER: api_version,
            "Accept": "application/json",
        },
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Wistia rejected the API token. Check the token in your Wistia account settings and try again."
    if status is None:
        return False, "Couldn't reach Wistia to check the API token. Try again in a few minutes."
    return False, f"Wistia couldn't check the API token right now (status {status}). Try again in a few minutes."


def _top_level_resource(
    config: WistiaEndpointConfig,
    api_token: str,
    api_version: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[WistiaResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> Resource:
    params: dict[str, Any] = {**config.params, "per_page": PAGE_SIZE}
    if config.incremental_fields and db_incremental_field_last_value is not None:
        # The Stats API filters by day only, so the watermark day is read again and merge
        # removes the duplicates.
        params["start_date"] = _as_date(db_incremental_field_last_value).isoformat()

    rest_config: RESTAPIConfig = {
        "client": {**_client_config(api_token, api_version), "paginator": WistiaPageNumberPaginator()},
        "resources": [
            {
                "name": config.name,
                "data_map": _drop_fields,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # A 200 with a body that is not a list means the response shape changed.
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if manager.can_resume():
        resume = manager.load_state()
        if resume is not None and resume.page is not None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("page") is not None:
            manager.save_state(WistiaResumeConfig(page=int(state["page"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _fan_out_resource(
    config: WistiaEndpointConfig,
    parent_config: WistiaEndpointConfig,
    api_token: str,
    api_version: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[WistiaResumeConfig],
) -> Resource:
    assert config.parent_key is not None
    parent_key = config.parent_key
    prefixed_parent_id = f"_{parent_config.name}_hashed_id"

    def _inject_parent_id(row: dict[str, Any]) -> dict[str, Any]:
        row[parent_key] = row.pop(prefixed_parent_id)
        return _drop_fields(row)

    parent_resource: EndpointResource = {
        "name": parent_config.name,
        "endpoint": {
            "path": parent_config.path,
            "params": {**parent_config.params, "per_page": PAGE_SIZE},
            "paginator": WistiaPageNumberPaginator(),
            "data_selector_required": True,
        },
    }

    child_params: dict[str, Any] = {
        "parent_id": {"type": "resolve", "resource": parent_config.name, "field": "hashed_id"},
    }
    child_endpoint: Endpoint = {
        "path": config.path,
        "params": child_params,
        # A parent deleted between the parent list and the child request returns 404.
        "response_actions": [{"status_code": 404, "action": "ignore"}],
    }
    if config.child_is_single_object:
        # One stats object per media: no pagination, and the body is a dict, not a list.
        child_endpoint["paginator"] = SinglePagePaginator()
    else:
        child_params.update({**config.params, "per_page": PAGE_SIZE})
        child_endpoint["paginator"] = WistiaPageNumberPaginator()
        child_endpoint["data_selector_required"] = True

    child_resource: EndpointResource = {
        "name": config.name,
        "include_from_parent": ["hashed_id"],
        "data_map": _inject_parent_id,
        "endpoint": child_endpoint,
        # The checkpoint keeps the parent page position, so it does not list every completed parent.
        "resume_parent_pagination": True,
    }

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token, api_version),
        "resources": [parent_resource, child_resource],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if manager.can_resume():
        resume = manager.load_state()
        if resume is not None and resume.fanout_state is not None:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            manager.save_state(WistiaResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return next(resource for resource in resources if resource.name == config.name)


def _account_stats_start(db_incremental_field_last_value: Optional[Any]) -> date:
    if db_incremental_field_last_value is not None:
        # The last synced day can still change, so read it again.
        return _as_date(db_incremental_field_last_value)
    return ACCOUNT_STATS_HISTORY_START


def _account_stats_rows(
    config: WistiaEndpointConfig,
    api_token: str,
    api_version: str,
    manager: ResumableSourceManager[WistiaResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> Iterator[list[dict[str, Any]]]:
    client = RESTClient(
        base_url=WISTIA_BASE_URL,
        headers={WISTIA_API_VERSION_HEADER: api_version, "Accept": "application/json"},
        auth=BearerTokenAuth(token=api_token),
    )
    today = datetime.now(UTC).date()
    start = _account_stats_start(db_incremental_field_last_value)
    if manager.can_resume():
        resume = manager.load_state()
        if resume is not None and resume.window_start is not None:
            start = date.fromisoformat(resume.window_start)

    # The endpoint has no pagination, so each request covers one window of days.
    while start <= today:
        end = min(start + timedelta(days=ACCOUNT_STATS_WINDOW_DAYS - 1), today)
        rows: list[dict[str, Any]] = []
        for page in client.paginate(
            path=config.path,
            params={"start_date": start.isoformat(), "end_date": end.isoformat()},
            paginator=SinglePagePaginator(),
            data_selector_required=True,
        ):
            rows.extend(page)
        start = end + timedelta(days=1)
        manager.save_state(WistiaResumeConfig(window_start=start.isoformat()))
        if rows:
            yield rows
        else:
            manager.safe_point()


def wistia_source(
    api_token: str,
    api_version: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WistiaResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = WISTIA_ENDPOINTS[endpoint]

    items: Any
    if config.name == "account_stats_by_date":
        items = lambda: _account_stats_rows(
            config, api_token, api_version, resumable_source_manager, db_incremental_field_last_value
        )
    elif config.parent is not None:
        resource = _fan_out_resource(
            config,
            WISTIA_ENDPOINTS[config.parent],
            api_token,
            api_version,
            team_id,
            job_id,
            resumable_source_manager,
        )
        items = lambda: resource
    else:
        resource = _top_level_resource(
            config,
            api_token,
            api_version,
            team_id,
            job_id,
            resumable_source_manager,
            db_incremental_field_last_value,
        )
        items = lambda: resource

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format=config.partition_format if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
