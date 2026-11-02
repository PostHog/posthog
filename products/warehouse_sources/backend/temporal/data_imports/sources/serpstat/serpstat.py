import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from requests import Request, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.serpstat import (
    SerpstatSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.serpstat.settings import (
    DEFAULT_SEARCH_ENGINE,
    DOMAIN_ERROR,
    DOMAIN_HISTORY_PAGE_SIZE,
    DOMAIN_RESPONSE_ACTIONS,
    ENDPOINTS,
    MAX_PAGES,
    PAGE_SIZE,
    POSITION_HISTORY_DAYS,
    REQUEST_INTERVAL_SECONDS,
    RESPONSE_ACTIONS,
)

logger = structlog.get_logger(__name__)


@frozen
class SerpstatResumeConfig:
    page: int
    date_to: str


class SerpstatPaginator(PageNumberPaginator):
    def __init__(self, *, page_size: int | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.page_size = page_size

    def init_request(self, request: Request) -> None:
        # JSON-RPC puts pagination inside params, rather than at the body root.
        request.json["params"]["page"] = self.page

    def update_request(self, request: Request) -> None:
        time.sleep(REQUEST_INTERVAL_SECONDS)
        self.init_request(request)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        super().update_state(response, data)
        if self.page_size is not None and data is not None and len(data) < self.page_size:
            self._has_next_page = False
        if self.maximum_page == MAX_PAGES and self.page > MAX_PAGES and data:
            logger.info("serpstat_page_cap_reached", maximum_page=self.maximum_page)


def normalize_domain(value: str | None) -> str:
    domain = (value or "").strip().lower().removeprefix("https://").removeprefix("http://")
    return domain.split("/", 1)[0]


def serpstat_resource(
    config: SerpstatSourceConfig,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    manager: ResumableSourceManager[SerpstatResumeConfig] | None = None,
    credential_check: bool = False,
    date_from: str | None = None,
) -> Resource:
    settings = ENDPOINTS[endpoint]
    resume = manager.load_state() if manager is not None and manager.can_resume() else None
    date_to = resume.date_to if resume else datetime.now(UTC).date().isoformat()
    params: dict[str, Any] = {}
    if settings.project_param:
        params[settings.project_param] = int(config.project_id)
    if settings.domain_param:
        domain = normalize_domain(config.domain)
        if not domain:
            raise ValueError(DOMAIN_ERROR)
        params[settings.domain_param] = [domain] if settings.domain_param == "domains" else domain
    if settings.search_engine:
        params["se"] = (config.search_engine or "").strip() or DEFAULT_SEARCH_ENGINE
    if settings.paginated:
        params[settings.size_param] = 20 if credential_check else PAGE_SIZE
    if endpoint in ("project_keywords", "project_positions"):
        params.update(sort="added", order="asc")
    if endpoint == "project_positions":
        params.update(
            project_region_ids=[int(config.project_region_id)],
            date_from=(date.fromisoformat(date_to) - timedelta(days=POSITION_HISTORY_DAYS - 1)).isoformat(),
            date_to=date_to,
        )
    if endpoint == "domain_history":
        params.update(during_all_time=True, sort={"date": "asc"}, size=DOMAIN_HISTORY_PAGE_SIZE)
        if date_from:
            params["filters"] = {"date_from": date_from}
    if endpoint == "backlinks":
        params.update(searchType="domain_with_subdomains", sort="add", order="desc")

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": f"https://api.serpstat.com/{api_version}/",
            "auth": {"type": "api_key", "name": "token", "api_key": config.api_key, "location": "query"},
            "allow_redirects": False,
            "allowed_hosts": [],
            "request_timeout": (10.0, 60.0),
        },
        "resources": [
            {
                "name": endpoint,
                "table_format": "delta",
                "write_disposition": "replace",
                "primary_key": list(settings.primary_keys),
                "endpoint": {
                    "path": "",
                    "method": "POST",
                    "json": {"id": "posthog", "method": settings.method, "params": params},
                    "data_selector": settings.selector,
                    "data_selector_required": True,
                    "paginator": SerpstatPaginator(
                        base_page=1,
                        total_path=settings.total_pages_path,
                        maximum_page=1 if credential_check else MAX_PAGES,
                        page_size=PAGE_SIZE if settings.stop_on_short_page else None,
                    )
                    if settings.paginated
                    else "single_page",
                    "response_actions": DOMAIN_RESPONSE_ACTIONS if settings.domain_param else RESPONSE_ACTIONS,
                },
            }
        ],
    }

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if manager is not None and state is not None:
            manager.save_state(SerpstatResumeConfig(page=int(state["page"]), date_to=date_to))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"page": resume.page} if resume else None,
    )
    if settings.project_param:
        resource.add_map(lambda row: {**row, "project_id": int(config.project_id)})
    return resource
