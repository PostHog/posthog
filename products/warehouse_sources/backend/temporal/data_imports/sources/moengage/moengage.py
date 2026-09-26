import uuid
import hashlib
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any, Optional

from requests import Request, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.moengage.settings import (
    ATTRIBUTION_TYPE,
    DEFAULT_BACKFILL_DAYS,
    METRIC_TYPE,
    MOENGAGE_DATA_CENTERS,
    MOENGAGE_ENDPOINTS,
    REPORT_WINDOW_DAYS,
    SEARCH_PAGE_SIZE,
    STATS_PAGE_SIZE,
)


@frozen
class MoEngageResumeConfig:
    # Campaign search checkpoint: {"page": <next 1-indexed page>}.
    search_state: dict | None = None
    # Daily report checkpoint: {"start": "YYYY-MM-DD"}, the first day not yet fully yielded. The
    # within-day stats offset is deliberately not saved: replaying a whole day costs at most a few
    # request sets and merge dedupes the overlap on the synthesized `id`.
    report_day_state: dict | None = None


def moengage_base_url(data_center: str) -> str:
    # The value is interpolated into the hostname, so anything outside the fixed data-center set is
    # refused rather than sent: "01.evil.com" would otherwise retarget the credential.
    if data_center not in MOENGAGE_DATA_CENTERS:
        raise ValueError(f"Unknown MoEngage data center: {data_center!r}")
    return f"https://api-{data_center}.moengage.com"


class MoEngageSearchPaginator(BasePaginator):
    """Page-number pagination inside the V5 search POST body.

    The response carries no total count, so the terminal page is the one that returns fewer
    campaigns than the requested limit. Every POST also needs a fresh Idempotency-Key header:
    reusing one would make MoEngage replay the first page's response for every page.
    """

    def __init__(self, limit: int = SEARCH_PAGE_SIZE) -> None:
        super().__init__()
        self._limit = limit
        self._page = 1

    def _apply(self, request: Request) -> None:
        if request.json is None:
            request.json = {}
        request.json["page"] = self._page
        request.json["limit"] = self._limit
        request.headers["Idempotency-Key"] = str(uuid.uuid4())

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if data is not None and len(data) >= self._limit:
            self._page += 1
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"page": self._page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self._page = int(page)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"MoEngageSearchPaginator(page={self._page}, limit={self._limit})"


class MoEngageStatsPaginator(BasePaginator):
    """Offset pagination inside the campaign-stats POST body.

    The response reports current_page/total_pages; an empty `data` object or the last page stops
    the walk. When the page counters are missing from a response, a page holding fewer campaigns
    than the limit is treated as terminal so the walk can never loop on one offset.
    """

    def __init__(self, limit: int = STATS_PAGE_SIZE) -> None:
        super().__init__()
        self._limit = limit
        self._offset = 0

    def _apply(self, request: Request) -> None:
        if request.json is None:
            request.json = {}
        request.json["offset"] = self._offset
        request.json["limit"] = self._limit

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            self._has_next_page = False
            return
        stats = body.get("data") or {}
        current_page = body.get("current_page")
        total_pages = body.get("total_pages")
        if not stats:
            self._has_next_page = False
        elif isinstance(current_page, int) and isinstance(total_pages, int):
            self._has_next_page = current_page < total_pages
        else:
            self._has_next_page = len(stats) >= self._limit
        if self._has_next_page:
            self._offset += self._limit

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def __str__(self) -> str:
        return f"MoEngageStatsPaginator(offset={self._offset}, limit={self._limit})"


def _row_id(*parts: Any) -> str:
    """Deterministic surrogate id for a report row.

    Hashes only the identity dimensions (never the metric values), so a row whose metrics get
    restated between runs keeps the same id and merge updates it in place.
    """
    joined = "|".join("\x00" if p is None else str(p) for p in parts)
    return hashlib.sha256(joined.encode()).hexdigest()


def _explode_stats(window_columns: dict[str, Any], data_item: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten one campaign-stats response into rows.

    The response's `data` is an object keyed by campaign id, each holding a list of entries whose
    platforms/locales/variations nest the metrics. One row per (campaign, platform, locale,
    variation) with the flat performance metrics spread as columns; the goal, funnel and failure
    groups keep dynamic keys (goal names, failure reasons) so they stay nested.
    """
    rows: list[dict[str, Any]] = []
    for campaign_id, entries in data_item.items():
        if not isinstance(entries, list):
            continue
        # The entry list is undocumented and observed with a single element; the index joins the id
        # so a second element can never silently collide with the first.
        for index, entry in enumerate(entries):
            platforms = (entry or {}).get("platforms") or {}
            for platform, platform_data in platforms.items():
                locales = (platform_data or {}).get("locales") or {}
                for locale, locale_data in locales.items():
                    variations = (locale_data or {}).get("variations") or {}
                    for variation, stats in variations.items():
                        stats = stats or {}
                        row: dict[str, Any] = dict(stats.get("performance_stats") or {})
                        row.update(
                            {
                                "id": _row_id(
                                    campaign_id,
                                    *window_columns.values(),
                                    index,
                                    platform,
                                    locale,
                                    variation,
                                ),
                                "campaign_id": campaign_id,
                                **window_columns,
                                "platform": platform,
                                "locale": locale,
                                "variation": variation,
                                "conversion_goal_stats": stats.get("conversion_goal_stats"),
                                "delivery_funnel": stats.get("delivery_funnel"),
                                "failure_breakdown": stats.get("failure_breakdown"),
                            }
                        )
                        rows.append(row)
    return rows


def _stats_body(start_date: date, end_date: date) -> dict[str, Any]:
    return {
        "request_id": str(uuid.uuid4()),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "attribution_type": ATTRIBUTION_TYPE,
        "metric_type": METRIC_TYPE,
    }


def parse_iso_date(value: str) -> date:
    # Accept a bare date or a full timestamp; only the calendar day matters for the fan-out.
    return date.fromisoformat(value.strip()[:10])


def _as_date(value: Any) -> date:
    # datetime subclasses date, so it has to be tested first.
    if isinstance(value, datetime):
        return (value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)).date()
    if isinstance(value, date):
        return value
    return parse_iso_date(str(value))


def _report_days(
    db_incremental_field_last_value: Optional[Any],
    today: date,
    configured_start: Optional[date],
    resume_from: Optional[date],
) -> list[date]:
    """Resolve the days the daily report requests, oldest first.

    An incremental run continues from the watermark (already shifted back by the pipeline's
    lookback); a full refresh starts at the configured start date, else the default backfill
    window. A start past today is clamped onto today so a run always re-pulls the current day.
    """
    if db_incremental_field_last_value is not None:
        start = _as_date(db_incremental_field_last_value)
    else:
        start = configured_start or (today - timedelta(days=DEFAULT_BACKFILL_DAYS - 1))
    if resume_from is not None:
        start = max(start, resume_from)
    day = min(start, today)
    days: list[date] = []
    while day <= today:
        days.append(day)
        day = day + timedelta(days=1)
    return days


def _resume_day(resume: Optional[MoEngageResumeConfig]) -> Optional[date]:
    saved = resume.report_day_state if resume is not None else None
    start = saved.get("start") if isinstance(saved, dict) else None
    return parse_iso_date(str(start)) if start else None


def _iter_report_days(
    build_resource: Callable[[date], Any],
    days: list[date],
    save_checkpoint: Callable[[date], None],
) -> Iterator[list[dict[str, Any]]]:
    """Yield every day's pages in ascending day order, checkpointing once a day is fully yielded.

    The checkpoint names the first day not yet yielded, so a restart replays at most the day that
    was in progress and merge dedupes it on the synthesized `id`.
    """
    for index, day in enumerate(days):
        yield from build_resource(day)
        if index + 1 < len(days):
            save_checkpoint(days[index + 1])


def _client_config(data_center: str, workspace_id: str, api_key: str) -> ClientConfig:
    return {
        "base_url": moengage_base_url(data_center),
        "auth": {
            "type": "http_basic",
            "username": workspace_id,
            "password": api_key,
        },
        # MOE-APPKEY is required by the core-services endpoints and harmless on V5, which reads the
        # workspace id from the Basic Auth username.
        "headers": {
            "MOE-APPKEY": workspace_id,
            "Accept": "application/json",
        },
    }


def moengage_source(
    data_center: str,
    workspace_id: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MoEngageResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
    should_use_incremental_field: bool = False,
    configured_start_date: Optional[str] = None,
) -> SourceResponse:
    endpoint_config = MOENGAGE_ENDPOINTS.get(endpoint)
    if endpoint_config is None:
        raise ValueError(f"Unknown MoEngage endpoint: {endpoint}")

    client_config = _client_config(data_center, workspace_id, api_key)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    today = datetime.now(UTC).date()
    # Set only where the rows come from something other than iterating `resource` once.
    items: Optional[Callable[[], Iterator[list[dict[str, Any]]]]] = None
    resource: Any = None

    if endpoint == "campaigns":
        campaigns_resource: EndpointResource = {
            "name": endpoint,
            "write_disposition": "replace",
            "table_format": "delta",
            "endpoint": {
                "path": endpoint_config.path,
                "method": "POST",
                # Child campaigns (periodic and flow-node executions) and archived campaigns are the
                # rows the stats tables key to, so the list includes both.
                "json": {"include_child_campaigns": True, "include_archive_campaigns": True},
                "data_selector": "data.campaigns",
                "paginator": MoEngageSearchPaginator(),
            },
        }
        campaigns_config: RESTAPIConfig = {
            "client": client_config,
            "resource_defaults": None,
            "resources": [campaigns_resource],
        }

        def save_search_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state and state.get("page"):
                resumable_source_manager.save_state(MoEngageResumeConfig(search_state=state))

        resource = rest_api_resource(
            campaigns_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_search_checkpoint,
            initial_paginator_state=resume.search_state if resume is not None else None,
        )
    elif endpoint == "campaign_report":
        # A per-campaign snapshot of the trailing window the stats API allows in one call. The
        # whole table restates each sync, so it is full-refresh only and not resumed: the window is
        # anchored to today, and a checkpointed offset from a previous day would point into a
        # different result set.
        window_start = today - timedelta(days=REPORT_WINDOW_DAYS - 1)
        report_resource: EndpointResource = {
            "name": endpoint,
            "write_disposition": "replace",
            "table_format": "delta",
            "endpoint": {
                "path": endpoint_config.path,
                "method": "POST",
                "json": _stats_body(window_start, today),
                "data_selector": "data",
                "paginator": MoEngageStatsPaginator(),
            },
            "data_map": partial(
                _explode_stats, {"start_date": window_start.isoformat(), "end_date": today.isoformat()}
            ),
        }
        report_config: RESTAPIConfig = {
            "client": client_config,
            "resource_defaults": None,
            "resources": [report_resource],
        }
        resource = rest_api_resource(report_config, team_id, job_id, db_incremental_field_last_value)
    else:
        # Daily report: the stats API answers one date window per call, so the source fans out one
        # request set per calendar day, oldest first, which keeps rows ascending for the watermark.
        configured_start = parse_iso_date(configured_start_date) if configured_start_date else None
        days = _report_days(
            db_incremental_field_last_value if should_use_incremental_field else None,
            today,
            configured_start,
            _resume_day(resume),
        )
        # One tracked session shared by every day's client, so a backfill reuses a single
        # connection pool instead of opening one per day.
        client_config["session"] = make_tracked_session(redact_values=(api_key,))

        def build_day_resource(day: date) -> Any:
            day_resource: EndpointResource = {
                "name": endpoint,
                "write_disposition": {"disposition": "merge", "strategy": "upsert"}
                if should_use_incremental_field
                else "replace",
                "table_format": "delta",
                "endpoint": {
                    "path": endpoint_config.path,
                    "method": "POST",
                    "json": _stats_body(day, day),
                    "data_selector": "data",
                    "paginator": MoEngageStatsPaginator(),
                },
                "data_map": partial(_explode_stats, {"date": day.isoformat()}),
            }
            day_config: RESTAPIConfig = {
                "client": client_config,
                "resource_defaults": None,
                "resources": [day_resource],
            }
            return rest_api_resource(day_config, team_id, job_id, db_incremental_field_last_value)

        def save_day_checkpoint(next_day: date) -> None:
            resumable_source_manager.save_state(MoEngageResumeConfig(report_day_state={"start": next_day.isoformat()}))

        items = partial(_iter_report_days, build_day_resource, days, save_day_checkpoint)

    return SourceResponse(
        name=endpoint,
        items=items if items is not None else (lambda: resource),
        primary_keys=endpoint_config.primary_keys,
        sort_mode="asc",
        partition_count=1 if endpoint_config.partition_key else None,
        partition_size=1 if endpoint_config.partition_key else None,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def validate_credentials(data_center: str, workspace_id: str, api_key: str) -> tuple[bool, str | None]:
    """One cheap probe against the campaign search endpoint to confirm the credentials.

    MoEngage issues separate API keys per feature; the campaigns and stats endpoints both take the
    Campaign report key, so a 403 here means the wrong key kind rather than a partial scope, and it
    is rejected at create time.
    """
    try:
        session = make_tracked_session(redact_values=(api_key,))
        response = session.post(
            f"{moengage_base_url(data_center)}/v5/campaigns/search",
            json={"limit": 1, "page": 1},
            headers={
                "MOE-APPKEY": workspace_id,
                "Accept": "application/json",
                "Idempotency-Key": str(uuid.uuid4()),
            },
            auth=(workspace_id, api_key),
            timeout=10,
        )
    except Exception:
        return False, "Couldn't reach MoEngage. Check the selected data center and try again."
    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return (
            False,
            "MoEngage authentication failed. Check that the Workspace ID and the Campaign report API key "
            "(Settings > Account > APIs in your MoEngage dashboard) are correct and match your data center.",
        )
    return False, f"MoEngage returned an unexpected response (HTTP {response.status_code}). Try again later."
