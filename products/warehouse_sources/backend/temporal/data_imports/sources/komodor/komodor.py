from collections.abc import Iterator
from datetime import UTC, datetime
from functools import partial
from typing import Any

from requests import Request, Response
from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    RESTClient,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.komodor import (
    KomodorSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.komodor.settings import (
    AUTH_ERRORS,
    ENDPOINTS,
    PAGE_SIZE,
    PRIMARY_KEYS,
    REGION_URLS,
    SEARCH_INCREMENTAL_OVERLAP_SECONDS,
    SEARCH_RETENTION_MARGIN_SECONDS,
    SEARCH_RETENTION_SECONDS,
    SEARCH_WINDOW_SECONDS,
    WINDOWED_SEARCHES,
)

REQUEST_TIMEOUT = (10, 60)


@frozen
class KomodorResumeConfig:
    cursor: str | int | None = None
    cluster: str | None = None
    search_type: str | None = None
    window_start: int | None = None
    start: int | None = None
    until: int | None = None


@frozen
class SearchUnit:
    cluster: str
    search_type: str
    window_start: int
    window_end: int


class KomodorPaginator(JSONResponseCursorPaginator):
    def __init__(self, *, cursor_path: str, pagination_field: str) -> None:
        super().__init__(cursor_path=cursor_path, raise_on_repeated_cursor=True)
        self.pagination_field = pagination_field

    def update_request(self, request: Request) -> None:
        state = self.get_resume_state()
        if state is not None:
            if request.json is None:
                request.json = {}
            request.json.setdefault("pagination", {})[self.pagination_field] = state["cursor"]

    def init_request(self, request: Request) -> None:
        self.update_request(request)


class CostAllocationPaginator(JSONResponseCursorPaginator):
    def __init__(self) -> None:
        super().__init__(cursor_path="paginationToken", cursor_param="paginationToken", raise_on_repeated_cursor=True)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        if not response.json().get("hasMorePages"):
            self._has_next_page = False
            return
        super().update_state(response, data)


def get_base_url(region: str, api_version: str) -> str:
    if region not in REGION_URLS:
        raise ValueError("Select a valid Komodor region: US or EU.")
    return f"{REGION_URLS[region]}/api/{api_version}/"


def _client(api_key: str, base_url: str) -> RESTClient:
    return RESTClient(
        base_url=base_url,
        auth=APIKeyAuth(api_key=api_key, name="X-API-KEY"),
        allow_redirects=False,
        request_timeout=REQUEST_TIMEOUT,
    )


def validate_credentials(config: KomodorSourceConfig, api_version: str) -> tuple[bool, str | None]:
    try:
        base_url = get_base_url(config.region, api_version)
    except ValueError as error:
        return False, str(error)

    client = _client(config.api_key, base_url)
    try:
        next(
            client.paginate(
                "services/search",
                method="POST",
                json={"pagination": {"pageSize": 1}},
                data_selector="data.services",
                data_selector_required=True,
                paginator=SinglePagePaginator(),
            ),
            None,
        )
    except HTTPError as error:
        if error.response is not None and error.response.status_code in (401, 403):
            return False, AUTH_ERRORS[f"{error.response.status_code} Client Error"]
        raise
    return True, None


def _search_units(clusters: list[str], types: tuple[str, ...], start: int, until: int) -> list[SearchUnit]:
    windows: list[tuple[int, int]] = []
    window_start = start
    while window_start < until:
        window_end = min(window_start + SEARCH_WINDOW_SECONDS, until)
        windows.append((window_start, window_end))
        window_start = window_end
    return [
        SearchUnit(cluster=cluster, search_type=search_type, window_start=window_start, window_end=window_end)
        for cluster in clusters
        for search_type in types
        for window_start, window_end in windows
    ]


def _retention_floor(now: int) -> int:
    return now - SEARCH_RETENTION_SECONDS + SEARCH_RETENTION_MARGIN_SECONDS


def _search_start(until: int, db_incremental_field_last_value: Any) -> int:
    start = _retention_floor(until)
    try:
        last_value = int(db_incremental_field_last_value)
    except (TypeError, ValueError):
        return start
    # A watermark ahead of our clock still reads the latest window.
    return min(max(start, last_value - SEARCH_INCREMENTAL_OVERLAP_SECONDS), until - SEARCH_WINDOW_SECONDS)


def _owns(unit: SearchUnit, start: int, until: int, row: dict[str, Any]) -> bool:
    start_time = row.get("startTime")
    if not isinstance(start_time, int | float):
        return True
    after_start = unit.window_start == start or start_time >= unit.window_start
    before_end = unit.window_end == until or start_time < unit.window_end
    return after_start and before_end


def iter_windowed_search(
    endpoint: str,
    api_key: str,
    base_url: str,
    manager: ResumableSourceManager[KomodorResumeConfig],
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    search = WINDOWED_SEARCHES[endpoint]
    resume = manager.load_state() if manager.can_resume() else None
    if resume is not None and resume.start is not None and resume.until is not None:
        start, until = resume.start, resume.until
    else:
        until = int(datetime.now(UTC).timestamp())
        start = _search_start(until, db_incremental_field_last_value)

    client = _client(api_key, base_url)
    try:
        clusters = sorted(
            {
                row["name"]
                for page in client.paginate(
                    "clusters",
                    data_selector="data.clusters",
                    data_selector_required=True,
                    paginator=SinglePagePaginator(),
                )
                for row in page
            }
        )
        units = _search_units(clusters, search.types, start, until)

        first, cursor = 0, None
        if resume is not None:
            for index, unit in enumerate(units):
                if (unit.cluster, unit.search_type, unit.window_start) == (
                    resume.cluster,
                    resume.search_type,
                    resume.window_start,
                ):
                    first, cursor = index, resume.cursor
                    break

        def stage(index: int, state: dict[str, Any] | None, has_next_page: bool) -> None:
            if has_next_page and state is not None:
                unit, next_cursor = units[index], state["cursor"]
            elif index + 1 < len(units):
                unit, next_cursor = units[index + 1], None
            else:
                return
            manager.save_state(
                KomodorResumeConfig(
                    cursor=next_cursor,
                    cluster=unit.cluster,
                    search_type=unit.search_type,
                    window_start=unit.window_start,
                    start=start,
                    until=until,
                )
            )

        for index in range(first, len(units)):
            unit = units[index]
            # A long or resumed run can age its oldest windows past the 7-day limit, which Komodor rejects.
            floor = _retention_floor(int(datetime.now(UTC).timestamp()))
            if unit.window_end <= floor:
                continue
            manager.safe_point()
            props: dict[str, Any] = {
                "type": unit.search_type,
                "fromEpoch": max(unit.window_start, floor),
                # Both bounds are inclusive, so the next window starts one second later.
                "toEpoch": unit.window_end - 1,
            }
            if search.statuses is not None:
                props["statuses"] = list(search.statuses)
            for page in client.paginate(
                search.path,
                method="POST",
                json={"scope": {"cluster": unit.cluster}, "props": props, "pagination": {"pageSize": PAGE_SIZE}},
                paginator=KomodorPaginator(cursor_path=search.cursor_path, pagination_field=search.pagination_field),
                data_selector=search.data_selector,
                data_selector_required=True,
                initial_paginator_state={"cursor": cursor} if cursor is not None else None,
                page_state_hook=partial(stage, index),
            ):
                # A search can return an issue or event in two windows, so only the window that holds its start keeps it.
                rows = [{**row, "cluster": unit.cluster} for row in page if _owns(unit, start, until, row)]
                if rows:
                    yield rows
                else:
                    manager.safe_point()
            cursor = None
    finally:
        client.session.close()


def komodor_source(
    config: KomodorSourceConfig,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[KomodorResumeConfig],
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    if endpoint not in ENDPOINTS:
        raise ValueError(f"Unknown Komodor table: {endpoint}")

    base_url = get_base_url(config.region, api_version)

    if endpoint in WINDOWED_SEARCHES:
        return SourceResponse(
            name=endpoint,
            items=lambda: iter_windowed_search(
                endpoint, config.api_key, base_url, resumable_source_manager, db_incremental_field_last_value
            ),
            primary_keys=PRIMARY_KEYS[endpoint],
            sort_mode=None,
            supports_resume=True,
        )

    endpoint_config = ENDPOINTS[endpoint].copy()
    paginated = endpoint in ("services", "jobs", "cost_allocation")
    if endpoint == "cost_allocation":
        endpoint_config["paginator"] = CostAllocationPaginator()
    elif paginated:
        endpoint_config["json"] = {"pagination": {"pageSize": PAGE_SIZE}}
        endpoint_config["paginator"] = KomodorPaginator(
            cursor_path="meta.token" if endpoint == "services" else "meta.nextPage",
            pagination_field="token" if endpoint == "services" else "page",
        )
    else:
        endpoint_config["paginator"] = "single_page"
    endpoint_config["data_selector_required"] = True

    initial_state: dict[str, Any] | None = None
    if paginated and resumable_source_manager.can_resume():
        saved = resumable_source_manager.load_state()
        if saved is not None and saved.cursor is not None:
            initial_state = {"cursor": saved.cursor}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(KomodorResumeConfig(cursor=state["cursor"]))

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url,
            "auth": {"type": "api_key", "api_key": config.api_key, "name": "X-API-KEY", "location": "header"},
            "allow_redirects": False,
            "request_timeout": REQUEST_TIMEOUT,
        },
        "resources": [{"name": endpoint, "endpoint": endpoint_config, "write_disposition": "replace"}],
    }
    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint if paginated else None,
        initial_paginator_state=initial_state,
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS[endpoint],
        sort_mode=None,
        supports_resume=paginated,
    )
