import dataclasses
from typing import Any, Optional
from urllib.parse import urlencode

import structlog
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.sonar_cloud.settings import (
    MAX_PAGE_SIZE,
    REGION_HOSTS,
    RESULT_CAP,
    SONAR_CLOUD_ENDPOINTS,
)

logger = structlog.get_logger(__name__)


@dataclasses.dataclass
class SonarCloudResumeConfig:
    # 1-based index of the next page to fetch. Paginated endpoints resume from here after a crash;
    # non-paginated endpoints ignore it.
    page: int = 1


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
        "client": {
            "base_url": _base_url(region),
            # Auth (Bearer) is supplied via the framework auth config so the token is redacted from
            # logs and error messages; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": token},
            "paginator": paginator,
        },
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
