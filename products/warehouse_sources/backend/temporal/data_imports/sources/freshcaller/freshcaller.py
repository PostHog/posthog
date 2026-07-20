import dataclasses
from datetime import UTC, date, datetime, time
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.freshcaller.settings import (
    DEFAULT_START_DATETIME,
    FRESHCALLER_ENDPOINTS,
    PER_PAGE,
)

VALIDATE_TIMEOUT = 10


@dataclasses.dataclass
class FreshcallerResumeConfig:
    # The next page number to fetch. Freshcaller uses page/per_page pagination, so a single
    # integer is enough to pick back up. The time window (by_time[from]/by_time[to]) is rebuilt
    # from the incremental watermark on resume — `from` is the stable DB watermark and `to` is
    # "now", so re-entering the same window and deduping on `id` is safe.
    page: int


def normalize_subdomain(domain: str) -> str:
    """Accept either a bare account name ("acme") or a full host ("acme.freshcaller.com")."""
    domain = domain.strip().removeprefix("https://").removeprefix("http://")
    domain = domain.split("/")[0]
    return domain.removesuffix(".freshcaller.com")


def _base_url(subdomain: str) -> str:
    return f"https://{normalize_subdomain(subdomain)}.freshcaller.com"


def _get_headers(api_key: str) -> dict[str, str]:
    # Freshcaller authenticates with a single API key in the X-Api-Auth header. The Accept header
    # is required — the API 404s the route when it's `*/*`.
    return {"X-Api-Auth": api_key, "Accept": "application/json"}


def _format_datetime(value: Any) -> str:
    """Format an incremental cursor value as the ISO 8601 UTC (Z-suffixed) string Freshcaller expects."""
    if isinstance(value, datetime):
        utc = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


class FreshcallerPagePaginator(BasePaginator):
    """page/per_page paginator matching Freshcaller's `meta` wrapper.

    Freshcaller wraps each list under its plural resource key alongside a `meta` object carrying
    `current`/`total_pages`. Termination mirrors the hand-rolled source exactly: stop on an empty
    page; when `total_pages` is present, continue while the current page is below it; when `meta` is
    unusable, treat a full page as "maybe more" and a short page as the end.
    """

    def __init__(self, per_page: int, page: int = 1, page_param: str = "page") -> None:
        super().__init__()
        self.per_page = per_page
        self.page = page
        self.page_param = page_param

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.page_param] = self.page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        items = data or []
        if not items:
            self._has_next_page = False
            return

        try:
            meta = response.json().get("meta") or {}
        except Exception:
            meta = {}

        total_pages = meta.get("total_pages")
        if isinstance(total_pages, int):
            current = meta.get("current")
            current_page = current if isinstance(current, int) else self.page
            if current_page < total_pages:
                self.page += 1
                self._has_next_page = True
            else:
                self._has_next_page = False
            return

        # No usable meta -> a full page implies there may be more.
        if len(items) >= self.per_page:
            self.page += 1
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.page_param] = self.page

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.page already points at the next page to fetch (update_state advanced it).
        return {"page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self.page = int(page)
            self._has_next_page = True


def freshcaller_source(
    api_key: str,
    subdomain: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FreshcallerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = FRESHCALLER_ENDPOINTS[endpoint]

    # Query params shared across every page (everything except `page`, which the paginator injects).
    params: dict[str, Any] = {"per_page": PER_PAGE}
    params.update(config.extra_params)

    endpoint_config: dict[str, Any] = {
        "path": config.path,
        "params": params,
        # Freshcaller wraps each list under its plural resource key (e.g. {"users": [...]}). A body
        # without that key degrades to a 0-row page (as the hand-rolled source did), not a hard error.
        "data_selector": config.data_key,
        "paginator": FreshcallerPagePaginator(per_page=PER_PAGE),
    }

    if should_use_incremental_field and config.supports_incremental:
        # `by_time` requires both bounds together; window is [watermark, now]. Without a watermark
        # (first sync) the framework falls back to `initial_value` (the configured backfill floor)
        # instead of scanning all history.
        endpoint_config["incremental"] = {
            "start_param": "by_time[from]",
            "end_param": "by_time[to]",
            "initial_value": DEFAULT_START_DATETIME,
            "end_value": _format_datetime(datetime.now(UTC)),
            "convert": _format_datetime,
        }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": _base_url(subdomain),
            # Only the non-secret Accept header here; the API key rides in framework auth so its
            # value is registered for log redaction.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-Api-Auth", "location": "header"},
        },
        "resources": [{"name": endpoint, "endpoint": endpoint_config}],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # from `page` and merge dedupes on the primary key rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(FreshcallerResumeConfig(page=int(state["page"])))

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
        primary_keys=["id"],
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Freshcaller list endpoints expose no sort param and don't document their default order.
        # For incremental endpoints we page the full [watermark, now] window each sync and dedupe
        # on `id`, so declaring "desc" defers the watermark commit to end-of-sync — keeping the
        # cursor correct regardless of the API's actual intra-window ordering. Full-refresh
        # endpoints carry no watermark, so the mode is irrelevant there.
        sort_mode="desc" if config.supports_incremental else "asc",
    )


def validate_credentials(subdomain: str, api_key: str) -> Optional[int]:
    """Probe the Freshcaller API. Returns the HTTP status code, or ``None`` on a connection error."""
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{_base_url(subdomain)}/api/v1/users?per_page=1",
        headers=_get_headers(api_key),
        timeout=VALIDATE_TIMEOUT,
    )
    return status
