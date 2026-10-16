from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import structlog
from requests import Response
from urllib3.util.retry import Retry

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.everflow.settings import (
    BASE_URLS,
    EVERFLOW_ENDPOINTS,
    HISTORY_DAYS,
    REREAD_DAYS,
    UTC_TIMEZONE_ID,
)

logger = structlog.get_logger(__name__)

REQUEST_TIMEOUT = (10, 120)
# Setup waits on the probe, so it gets one short attempt.
PROBE_TIMEOUT = (10, 30)
API_KEY_HEADER = "X-Eflow-API-Key"


@frozen
class EverflowResumeConfig:
    next_page: int | None = None
    # The `from` date the interrupted attempt sent, so resumed pages come from the same result set.
    window_start: str | None = None
    # The `to` date of the interrupted attempt, so a resume after midnight does not widen the window.
    window_end: str | None = None
    # The next day of the daily performance report to request.
    next_day: str | None = None


class EverflowReportTruncatedError(Exception):
    pass


class EverflowPaginator(PageNumberPaginator):
    """Page-number pagination that stops once `paging.total_count` rows have been read.

    Everflow reports the total row count but no page count, so without this check the walk pays for
    one more empty page on every table.
    """

    def __init__(self, page_size: int) -> None:
        super().__init__(base_page=1, page_param="page")
        self.page_size = page_size

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not self._has_next_page:
            return
        try:
            paging = response.json().get("paging") or {}
        except (ValueError, AttributeError):
            return
        total = paging.get("total_count")
        # `page` already points at the next page, so the pages read so far are `page - 1`.
        if isinstance(total, int) and (self.page - 1) * self.page_size >= total:
            self._has_next_page = False


def to_date(value: Any) -> date:
    if isinstance(value, bool):
        raise ValueError(f"Unexpected watermark: {value!r}")
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=UTC).date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def window_start(should_use_incremental_field: bool, last_value: Any, today: date, reread_days: int = 0) -> date:
    # The window runs to tomorrow's midnight, so this floor keeps it at the report's one-year maximum.
    floor = today - timedelta(days=HISTORY_DAYS - 1)
    if should_use_incremental_field and last_value is not None:
        return max(to_date(last_value) - timedelta(days=reread_days), floor)
    return floor


def _as_int(value: Any) -> Any:
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return value


def flatten_entity_row(row: dict[str, Any], day: str, currency_code: str) -> dict[str, Any]:
    """Turn one entity report row into a flat row keyed by day, offer and affiliate."""
    flat: dict[str, Any] = {
        "date": day,
        "network_offer_id": None,
        "network_affiliate_id": None,
        # The currency the amounts are in, which a later change of the setting does not rewrite.
        "currency_id": currency_code,
    }
    for column in row.get("columns") or []:
        column_type = column.get("column_type")
        if column_type in ("offer", "affiliate"):
            flat[f"network_{column_type}_id"] = _as_int(column.get("id"))
            flat[f"{column_type}_name"] = column.get("label")
    flat.update(row.get("reporting") or {})
    return flat


def _without(columns: tuple[str, ...]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def drop(row: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in row.items() if key not in columns}

    return drop


def _api_key_auth(api_key: str) -> APIKeyAuth:
    return APIKeyAuth(api_key=api_key, name=API_KEY_HEADER, location="header")


def _daily_performance(
    api_key: str,
    base_url: str,
    path: str,
    currency_code: str,
    start: date,
    end: date,
    manager: ResumableSourceManager[EverflowResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    client = RESTClient(base_url=base_url, auth=_api_key_auth(api_key), request_timeout=REQUEST_TIMEOUT)
    day = start
    while day <= end:
        next_day = day + timedelta(days=1)
        # Everflow reads both bounds as midnight, so one day runs up to the next day's midnight.
        body = {
            "from": day.isoformat(),
            "to": next_day.isoformat(),
            "timezone_id": UTC_TIMEZONE_ID,
            "currency_id": currency_code,
            "columns": [{"column": "offer"}, {"column": "affiliate"}],
            "query": {"filters": []},
        }
        rows: list[dict[str, Any]] = []
        # Without a selector each page is the whole body, which carries the truncation flag next to the rows.
        for page in client.paginate(path, method="post", json=body, paginator=SinglePagePaginator()):
            for response_body in page:
                if response_body.get("incomplete_results"):
                    raise EverflowReportTruncatedError(
                        f"Everflow's daily report for {day.isoformat()} hit its 10,000-row limit"
                    )
                rows.extend(
                    flatten_entity_row(row, day.isoformat(), currency_code) for row in response_body.get("table") or []
                )

        if next_day <= end:
            manager.save_state(EverflowResumeConfig(next_day=next_day.isoformat()))
        if rows:
            yield rows
        else:
            manager.safe_point()
        day = next_day


def everflow_source(
    api_key: str,
    region: str,
    endpoint: str,
    currency_code: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[EverflowResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = EVERFLOW_ENDPOINTS[endpoint]
    base_url = BASE_URLS[region]
    is_incremental = should_use_incremental_field and bool(config.incremental_fields)
    today = datetime.now(UTC).date()
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    response_kwargs: dict[str, Any] = {
        "name": endpoint,
        "primary_keys": list(config.primary_keys),
        "partition_count": 1 if config.partition_key else None,
        "partition_size": 1 if config.partition_key else None,
        "partition_mode": "datetime" if config.partition_key else None,
        "partition_format": "month" if config.partition_key else None,
        "partition_keys": [config.partition_key] if config.partition_key else None,
    }

    if endpoint == "daily_performance":
        start = (
            date.fromisoformat(resume.next_day)
            if resume is not None and resume.next_day
            else window_start(is_incremental, db_incremental_field_last_value, today)
        )
        return SourceResponse(
            items=lambda: _daily_performance(
                api_key, base_url, config.path, currency_code, start, today, resumable_source_manager
            ),
            # Days are requested in order, so rows arrive in date order.
            sort_mode="asc",
            **response_kwargs,
        )

    body: dict[str, Any] = {}
    start_value: str | None = None
    end_value: str | None = None
    if endpoint == "conversions":
        if resume is not None and resume.window_start:
            start_value = resume.window_start
            end_value = resume.window_end
        else:
            start_value = window_start(is_incremental, db_incremental_field_last_value, today, REREAD_DAYS).isoformat()
        # Everflow reads `to` as midnight, so tomorrow's date includes today's conversions.
        end_value = end_value or (today + timedelta(days=1)).isoformat()
        body = {
            "from": start_value,
            "to": end_value,
            "timezone_id": UTC_TIMEZONE_ID,
            "show_conversions": True,
            "show_events": True,
        }

    assert config.page_size is not None
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url,
            "auth": _api_key_auth(api_key),
            "paginator": EverflowPaginator(config.page_size),
            "request_timeout": REQUEST_TIMEOUT,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "table_name": endpoint,
                "primary_key": list(config.primary_keys),
                "write_disposition": {"disposition": "merge", "strategy": "upsert"} if is_incremental else "replace",
                "endpoint": {
                    "path": config.path,
                    "method": "POST",
                    "params": {"page_size": config.page_size},
                    "json": body,
                    "data_selector": config.data_selector,
                },
                "table_format": "delta",
                **({"data_map": _without(config.drop_columns)} if config.drop_columns else {}),
            }
        ],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("page"):
            resumable_source_manager.save_state(
                EverflowResumeConfig(next_page=int(state["page"]), window_start=start_value, window_end=end_value)
            )

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state={"page": resume.next_page} if resume is not None and resume.next_page else None,
    )
    return SourceResponse(
        items=lambda: resource,
        # The report has no sort parameter, so the watermark is taken once the run ends.
        sort_mode="desc" if config.incremental_fields else "asc",
        **response_kwargs,
    )


def validate_credentials(api_key: str, region: str) -> tuple[bool, str | None]:
    try:
        response = make_tracked_session(redact_values=(api_key,), allow_redirects=False, retry=Retry(total=0)).post(
            f"{BASE_URLS[region]}/networks/offerstable",
            params={"page": 1, "page_size": 1},
            json={},
            headers={API_KEY_HEADER: api_key},
            timeout=PROBE_TIMEOUT,
        )
    except Exception:  # noqa: BLE001 — a credential probe must never raise; any failure means "not validated"
        return False, "Could not connect to Everflow. Check the region and try again."
    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Everflow rejected the API key. Check the key and the region, then try again."
    if response.status_code == 403:
        return False, "This key belongs to an affiliate or advertiser portal. Create a network API key instead."
    return False, "Could not connect to Everflow. Check the region and try again."
