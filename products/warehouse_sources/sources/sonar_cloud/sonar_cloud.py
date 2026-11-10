import dataclasses
from collections.abc import Callable
from typing import Any, Optional, cast
from urllib.parse import urlencode

import structlog
from requests import Response

from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    ClientConfig,
    DependentEndpointConfig,
    PageNumberPaginator,
    Resource,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    build_dependent_resource,
    frozen,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)
from products.warehouse_sources.sources.sonar_cloud.settings import (
    MAX_PAGE_SIZE,
    REGION_HOSTS,
    RESULT_CAP,
    SONAR_CLOUD_ENDPOINTS,
    SonarCloudEndpointConfig,
)

logger = structlog.get_logger(__name__)


@frozen
class SonarCloudResumeConfig:
    # 1-based index of the next page to fetch. Paginated endpoints resume from here after a crash;
    # non-paginated endpoints ignore it.
    page: int = 1
    # Fan-out tables save the state `build_dependent_resource` checkpoints instead: the parents that
    # finished and the page where the current parent stopped.
    fanout_state: Optional[dict[str, Any]] = None


def _base_url(region: str) -> str:
    return REGION_HOSTS.get((region or "eu").lower(), REGION_HOSTS["eu"])


def _build_url(base_url: str, path: str, params: dict[str, Any]) -> str:
    query = urlencode({k: v for k, v in params.items() if v is not None})
    return f"{base_url}/{path}?{query}" if query else f"{base_url}/{path}"


def _total(data: dict[str, Any]) -> int | None:
    """Total row count, from either the nested `paging` object or the flat top-level fields."""
    paging = data.get("paging")
    if isinstance(paging, dict) and paging.get("total") is not None:
        return int(paging["total"])
    if data.get("total") is not None:
        return int(data["total"])
    return None


class SonarCloudPaginator(PageNumberPaginator):
    """v1 search pagination (`p`/`ps`) with SonarQube Cloud's 10000-row hard cap.

    Terminates on a short/empty page, once the reported total is reached, or at the cap — matching the
    hand-rolled loop's behavior exactly (never requesting a page the v1 API would reject). Resume state
    is the next page number; ``fetched`` is reconstructed from it so the cap check survives a restart.
    """

    def __init__(self, endpoint: str, page: int = 1) -> None:
        super().__init__(base_page=1, page=page, page_param="p", stop_after_empty_page=True)
        self.endpoint = endpoint
        self.fetched = (self.page - 1) * MAX_PAGE_SIZE

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if data is None or len(data) == 0:
            self._has_next_page = False
            return

        self.fetched += len(data)

        try:
            total = _total(response.json())
        except Exception:
            total = None

        # v1 hard-caps results at 10000 regardless of the reported total; stop there to avoid
        # requesting pages the API will reject.
        if self.fetched >= RESULT_CAP:
            if total is None or total > RESULT_CAP:
                logger.warning(
                    f"SonarQube Cloud endpoint {self.endpoint} hit the 10000-result cap; rows beyond the cap were not synced"
                )
            self._has_next_page = False
            return

        if len(data) < MAX_PAGE_SIZE or (total is not None and self.fetched >= total):
            self._has_next_page = False
            return

        self.page += 1
        self._has_next_page = True

    def set_resume_state(self, state: dict[str, Any]) -> None:
        super().set_resume_state(state)
        self.fetched = (self.page - 1) * MAX_PAGE_SIZE


class SonarCloudEnvelopePaginator(PageNumberPaginator):
    """v1 pagination driven by the response's `paging` object instead of the row count.

    The measures endpoints need it: component_tree returns the project next to each page of its
    components, and search_history pages the history points of each metric, so the number of selected
    rows says nothing about whether a page follows.
    """

    def __init__(self, page: int = 1) -> None:
        super().__init__(base_page=1, page=page, page_param="p")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            paging = response.json().get("paging") or {}
        except Exception:
            paging = {}

        index, size, total = paging.get("pageIndex"), paging.get("pageSize"), paging.get("total")
        if not (isinstance(index, int) and isinstance(size, int) and isinstance(total, int)) or index * size >= total:
            self._has_next_page = False
            return

        self.page = index + 1
        self._has_next_page = True


def _measure_rows() -> Callable[[dict[str, Any]], list[dict[str, Any]]]:
    """One row per component and metric, from the items the measures selector matches."""
    # The selector yields each page's `paging` object before its `baseComponent`.
    page_index: Any = None

    def _rows(item: dict[str, Any]) -> list[dict[str, Any]]:
        nonlocal page_index
        if "measures" not in item:
            # The `paging` object, selected only to keep the match a list.
            page_index = item.get("pageIndex")
            return []
        key = item.get("key")
        if key is not None and key == item.get("project_key") and page_index not in (None, 1):
            # component_tree repeats the project on every page of its components. Keep only the copy
            # on page 1, so a sync that resumes on a later page does not add the project again.
            return []
        component = {name: value for name, value in item.items() if name != "measures"}
        return [{**component, **measure} for measure in item.get("measures") or [] if isinstance(measure, dict)]

    return _rows


def _history_rows(item: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "project_key": item.get("project_key"),
            "metric": item.get("metric"),
            "date": point.get("date"),
            "value": point.get("value"),
        }
        for point in item.get("history") or []
        if isinstance(point, dict)
    ]


ROW_MAPS: dict[str, Callable[[], Callable[[dict[str, Any]], list[dict[str, Any]]]]] = {
    "measures": _measure_rows,
    "measures_history": lambda: _history_rows,
}


def _client_config(token: str, region: str, paginator: BasePaginator) -> ClientConfig:
    return {
        "base_url": _base_url(region),
        # Auth (Bearer) is supplied via the framework auth config so the token is redacted from
        # logs and error messages; only the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": token},
        "paginator": paginator,
    }


def _source_response(endpoint: str, config: SonarCloudEndpointConfig, resource: Any) -> SourceResponse:
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def _fanout_source(
    token: str,
    organization: str,
    region: str,
    endpoint: str,
    config: SonarCloudEndpointConfig,
    fanout_config: DependentEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SonarCloudResumeConfig],
) -> SourceResponse:
    fanout = dataclasses.replace(fanout_config, parent_params={"organization": organization, "ps": MAX_PAGE_SIZE})
    parent = SONAR_CLOUD_ENDPOINTS[fanout.parent_name]

    initial_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            resumable_source_manager.save_state(SonarCloudResumeConfig(fanout_state=state))

    child_paginator: BasePaginator = SonarCloudEnvelopePaginator() if config.paginated else SinglePagePaginator()
    resource = build_dependent_resource(
        endpoint_configs=SONAR_CLOUD_ENDPOINTS,
        child_endpoint=endpoint,
        fanout=fanout,
        client_config=_client_config(token, region, SonarCloudPaginator(fanout.parent_name)),
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        # Page sizes go in the params: the changelog child takes none.
        page_size_param=None,
        parent_endpoint_extra={"data_selector": parent.data_key},
        child_endpoint_extra={"data_selector": config.data_key, "paginator": child_paginator},
        child_params_extra={"organization": organization} if config.requires_organization else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
        resume_parent_pagination=True,
    )
    row_map = ROW_MAPS.get(endpoint)
    if row_map is not None:
        resource = cast(Resource, resource).add_map(row_map())
    return _source_response(endpoint, config, resource)


def sonar_cloud_source(
    token: str,
    organization: str,
    region: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SonarCloudResumeConfig],
) -> SourceResponse:
    config = SONAR_CLOUD_ENDPOINTS[endpoint]
    if config.fanout is not None:
        return _fanout_source(
            token, organization, region, endpoint, config, config.fanout, team_id, job_id, resumable_source_manager
        )

    params: dict[str, Any] = {}
    if config.requires_organization:
        params["organization"] = organization

    initial_paginator_state: Optional[dict[str, Any]] = None
    paginator: BasePaginator
    if config.paginated:
        params["ps"] = MAX_PAGE_SIZE
        paginator = SonarCloudPaginator(endpoint)
        if resumable_source_manager.can_resume():
            resume = resumable_source_manager.load_state()
            if resume is not None:
                initial_paginator_state = {"page": resume.page}
    else:
        paginator = SinglePagePaginator()

    rest_config: RESTAPIConfig = {
        "client": _client_config(token, region, paginator),
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # The hand-rolled source read `data.get(data_key, [])` — a missing key yields no
                    # rows rather than raising, so data_selector_required is intentionally left unset.
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(SonarCloudResumeConfig(page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # every SonarQube Cloud endpoint is full refresh
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _source_response(endpoint, config, resource)


def validate_credentials(token: str, organization: str, region: str, timeout: int = 10) -> int:
    """Probe the projects endpoint and return the HTTP status code (or 0 on transport failure).

    A single cheap request confirms the token is genuine. The caller decides how to treat 403
    (valid token, missing scope) depending on whether it's validating a specific schema.
    """
    url = _build_url(_base_url(region), "components/search_projects", {"organization": organization, "ps": 1})
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(token,)),
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=timeout,
    )
    return status if status is not None else 0
