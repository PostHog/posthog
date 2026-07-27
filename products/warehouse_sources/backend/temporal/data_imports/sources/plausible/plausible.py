import dataclasses
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.plausible.settings import (
    DEFAULT_BACKFILL_DAYS,
    PLAUSIBLE_ENDPOINTS,
    REPORT_LOOKBACK_DAYS,
    PlausibleEndpointConfig,
)

# Plausible Cloud; self-hosted instances override this via the source's host field.
PLAUSIBLE_DEFAULT_HOST = "https://plausible.io"
QUERY_PATH = "/api/v2/query"

# Stats API v2 caps pagination.limit at 10000 rows per page.
DEFAULT_PAGE_LIMIT = 10000


@dataclasses.dataclass
class PlausibleResumeConfig:
    # Offset of the next page to fetch within the current query.
    offset: int = 0
    # The date window the in-flight query was issued for, pinned so resuming mid-pagination keeps a
    # consistent total_rows/ordering instead of shifting when "today" moves.
    date_range_start: Optional[str] = None
    date_range_end: Optional[str] = None


def normalize_host(host: str) -> str:
    """Normalize the instance URL and reject anything that isn't plain http(s)."""
    host = host.strip()
    if not host:
        raise ValueError("Plausible host is required")
    if "://" not in host:
        host = f"https://{host}"
    host = host.rstrip("/")
    parsed = urlparse(host)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"Invalid Plausible host: {host}")
    return host


def resolve_host(host: Optional[str]) -> str:
    """Default an empty host to Plausible Cloud, then normalize it."""
    return normalize_host(host or PLAUSIBLE_DEFAULT_HOST)


def hostname_of(host: Optional[str]) -> str:
    return urlparse(resolve_host(host)).hostname or ""


def _to_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def _normalize_row(config: PlausibleEndpointConfig, result: dict[str, Any]) -> dict[str, Any]:
    """Flatten a Stats API result ({dimensions: [...], metrics: [...]}) into a named-column dict."""
    row: dict[str, Any] = {}
    # Direct access (not .get) so a malformed response missing dimensions — and therefore the `date`
    # primary key — fails fast instead of ingesting unkeyed rows.
    for name, value in zip(config.column_names, result["dimensions"]):
        row[name] = value
    for name, value in zip(config.metrics, result["metrics"]):
        row[name] = value
    return row


class PlausiblePaginator(BasePaginator):
    """Offset pagination for the Stats API v2 query endpoint.

    The offset/limit live nested under ``pagination`` in the POST body (not a flat top-level key),
    and the grand total is at ``meta.total_rows``, so the built-in OffsetPaginator (flat JSON keys)
    can't express it. Termination mirrors the hand-rolled loop: stop on a short page OR once the next
    offset reaches ``total_rows``.
    """

    def __init__(self, limit: int, offset: int = 0) -> None:
        super().__init__()
        self.limit = limit
        self.offset = offset

    def _set_pagination(self, request: Request) -> None:
        if request.json is None:
            request.json = {}
        request.json["pagination"] = {"limit": self.limit, "offset": self.offset}

    def init_request(self, request: Request) -> None:
        self._set_pagination(request)

    def update_request(self, request: Request) -> None:
        self._set_pagination(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        results = data or []
        try:
            total_rows = response.json().get("meta", {}).get("total_rows")
        except Exception:
            total_rows = None

        next_offset = self.offset + self.limit
        reached_end = len(results) < self.limit or (total_rows is not None and next_offset >= total_rows)
        self.offset = next_offset
        self._has_next_page = not reached_end

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.offset already points at the next page to fetch (update_state advanced it).
        return {"offset": self.offset} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        offset = state.get("offset")
        if offset is not None:
            self.offset = int(offset)
            self._has_next_page = True


def validate_credentials(host: Optional[str], site_id: str, api_key: str) -> tuple[bool, str | None]:
    """Confirm the instance is reachable and the key can read the site's stats."""
    try:
        # `host` is user-supplied, so pin redirects off: validation and the outbound request must
        # stay on the same target (SSRF defense-in-depth). The key is redacted from logged samples.
        session = make_tracked_session(
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            redact_values=(api_key,),
            allow_redirects=False,
        )
        response = session.post(
            f"{resolve_host(host)}{QUERY_PATH}",
            # Cheapest possible probe: one metric over a short relative range, no dimensions.
            json={"site_id": site_id, "metrics": ["visitors"], "date_range": "7d"},
            timeout=15,
        )
    except Exception:
        return False, "Could not reach Plausible. Check the host URL."

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Plausible rejected the API key. Check the key and that it has the stats read scope."
    if response.status_code == 404:
        return False, "Plausible could not find that site. Check the site domain (site ID)."

    try:
        message = response.json().get("error")
    except Exception:
        message = None
    return False, message or f"Plausible returned status {response.status_code}."


def _resolve_window(
    resume_config: Optional[PlausibleResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> tuple[date, date]:
    today = datetime.now(tz=UTC).date()
    start = today - timedelta(days=DEFAULT_BACKFILL_DAYS)
    if should_use_incremental_field:
        watermark = _to_date(db_incremental_field_last_value)
        if watermark is not None:
            # Recent days re-aggregate as visits arrive, so re-pull a trailing window and let merge
            # on the (date, ...) primary key overwrite the changed rows.
            start = watermark - timedelta(days=REPORT_LOOKBACK_DAYS)
    end = today

    if resume_config is not None:
        resumed_start = _to_date(resume_config.date_range_start)
        resumed_end = _to_date(resume_config.date_range_end)
        if resumed_start is not None:
            start = resumed_start
        if resumed_end is not None:
            end = resumed_end

    if start > end:
        start = end
    return start, end


def plausible_source(
    host: Optional[str],
    site_id: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PlausibleResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = PLAUSIBLE_ENDPOINTS[endpoint]

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start, end = _resolve_window(resume_config, should_use_incremental_field, db_incremental_field_last_value)
    start_iso, end_iso = start.isoformat(), end.isoformat()

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume_config is not None:
        initial_paginator_state = {"offset": resume_config.offset or 0}

    body: dict[str, Any] = {
        "site_id": site_id,
        "metrics": config.metrics,
        "date_range": [start_iso, end_iso],
        "dimensions": config.dimensions,
        # Ascending by day so the pipeline's incremental watermark only ever advances forward.
        "order_by": [["time:day", "asc"]],
        "include": {"total_rows": True},
    }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": resolve_host(host),
            "headers": {"Content-Type": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            # `host` is user-supplied: reject redirects so a request (and the Authorization header)
            # can't be bounced off the validated target.
            "allow_redirects": False,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": QUERY_PATH,
                    "method": "POST",
                    "json": body,
                    "data_selector": "results",
                    "paginator": PlausiblePaginator(limit=DEFAULT_PAGE_LIMIT),
                },
                "data_map": lambda result, config=config: _normalize_row(config, result),
            }
        ],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # the last page (merge dedupes on the primary key) rather than skipping it. The window is
        # pinned so the resumed query keeps a consistent total_rows/ordering.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(
                PlausibleResumeConfig(offset=int(state["offset"]), date_range_start=start_iso, date_range_end=end_iso)
            )

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
        primary_keys=list(config.primary_keys),
        # Reports are pulled oldest-day-first (order_by time:day asc), so the cursor only moves forward.
        sort_mode="asc",
        partition_mode="datetime",
        partition_format="month",
        partition_keys=["date"],
    )
