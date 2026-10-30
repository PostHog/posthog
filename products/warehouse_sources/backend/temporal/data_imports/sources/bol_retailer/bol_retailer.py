from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from requests.auth import HTTPBasicAuth
from urllib3.util.retry import Retry

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.bol_retailer.settings import (
    BOL_BASE_URL,
    BOL_ENDPOINTS,
    BOL_TOKEN_URL,
    INVOICE_HISTORY_DAYS,
    INVOICE_WINDOW_DAYS,
    OFFERS_PAGE_SIZE,
    ORDER_HISTORY_DAYS,
    BolEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import OAuth2Auth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

REQUEST_TIMEOUT = (10, 120)
TOKEN_TIMEOUT = 30


@frozen
class BolRetailerResumeConfig:
    pass_index: int = 0
    page: int = 1
    # The first day of the run's order or invoice windows, so a resumed attempt rebuilds the same passes.
    window_start: str | None = None
    cursor: str | None = None
    # The `last-modified-date-time` the interrupted attempt sent, so resumed pages come from the same result set.
    modified_since: str | None = None


def _auth(client_id: str, client_secret: str) -> OAuth2Auth:
    return OAuth2Auth(
        token_url=BOL_TOKEN_URL,
        client_id=client_id,
        client_secret=client_secret,
        grant_type="client_credentials",
        client_auth_method="basic",
        # bol's token service only answers JSON when the request asks for it.
        token_request_headers={"Accept": "application/json"},
    )


def format_modified_since(value: Any) -> str:
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return f"{value.isoformat()}T00:00:00Z"
    return str(value)


def flatten_order_items(order: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per order item, carrying the order's id and placement time."""
    return [
        {"orderId": order.get("orderId"), "orderPlacedDateTime": order.get("orderPlacedDateTime"), **item}
        for item in order.get("orderItems") or []
        if isinstance(item, dict)
    ]


def _paged_passes(
    client: RESTClient,
    path: str,
    data_selector: str,
    passes: list[dict[str, Any]],
    manager: ResumableSourceManager[BolRetailerResumeConfig],
    resume: BolRetailerResumeConfig | None,
    window_start: str | None = None,
    row_map: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None,
    stop_before: tuple[str, datetime] | None = None,
) -> Iterator[list[Any]]:
    start_pass = resume.pass_index if resume is not None else 0
    for pass_index in range(start_pass, len(passes)):
        first_page = resume.page if resume is not None and pass_index == start_pass else 1

        def stage(state: Optional[dict[str, Any]], has_next_page: bool, pass_index: int = pass_index) -> None:
            if has_next_page and state:
                manager.save_state(
                    BolRetailerResumeConfig(pass_index=pass_index, page=int(state["page"]), window_start=window_start)
                )
            elif pass_index + 1 < len(passes):
                manager.save_state(BolRetailerResumeConfig(pass_index=pass_index + 1, window_start=window_start))

        # bol ends a list with an empty page and reports no total, so each pass costs one empty request.
        for rows in client.paginate(
            path,
            params=passes[pass_index],
            paginator=PageNumberPaginator(base_page=1, page=first_page, page_param="page"),
            data_selector=data_selector,
            page_state_hook=stage,
        ):
            mapped = [mapped_row for row in rows for mapped_row in row_map(row)] if row_map else rows
            reached_watermark = (
                stop_before is not None and bool(mapped) and all(_is_before(row, *stop_before) for row in mapped)
            )
            if reached_watermark and pass_index + 1 < len(passes):
                manager.save_state(BolRetailerResumeConfig(pass_index=pass_index + 1, window_start=window_start))
            if mapped:
                yield mapped
            else:
                manager.safe_point()
            if reached_watermark:
                break


def _as_utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _is_before(row: dict[str, Any], field: str, watermark: datetime) -> bool:
    value = row.get(field)
    return value is not None and _as_utc(value) < watermark


def _to_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _invoice_windows(
    client: RESTClient,
    config: BolEndpointConfig,
    manager: ResumableSourceManager[BolRetailerResumeConfig],
    start: date,
    today: date,
) -> Iterator[list[Any]]:
    window = start
    while window <= today:
        end = min(window + timedelta(days=INVOICE_WINDOW_DAYS - 1), today)
        rows: list[Any] = []
        for page in client.paginate(
            config.path,
            params={"period-start-date": window.isoformat(), "period-end-date": end.isoformat()},
            paginator=SinglePagePaginator(),
            data_selector=config.data_selector,
        ):
            rows.extend(page)
        next_window = end + timedelta(days=1)
        if next_window <= today:
            manager.save_state(BolRetailerResumeConfig(window_start=next_window.isoformat()))
        if rows:
            yield rows
        else:
            manager.safe_point()
        window = next_window


def bol_retailer_source(
    client_id: str,
    client_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BolRetailerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = BOL_ENDPOINTS[endpoint]
    auth = _auth(client_id, client_secret)
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

    if config.pagination == "cursor":
        is_incremental = should_use_incremental_field and bool(config.incremental_fields)
        modified_since: str | None
        if resume is not None:
            modified_since = resume.modified_since
        elif is_incremental and db_incremental_field_last_value is not None:
            modified_since = format_modified_since(db_incremental_field_last_value)
        else:
            modified_since = None
        params: dict[str, Any] = {"page-size": OFFERS_PAGE_SIZE}
        if modified_since:
            params["last-modified-date-time"] = modified_since

        rest_config: RESTAPIConfig = {
            "client": {
                "base_url": BOL_BASE_URL,
                "headers": {"Accept": config.accept},
                "auth": auth,
                "paginator": JSONResponseCursorPaginator(cursor_path="page.nextCursor", cursor_param="cursor"),
                "request_timeout": REQUEST_TIMEOUT,
            },
            "resource_defaults": {},
            "resources": [
                {
                    "name": endpoint,
                    "table_name": endpoint,
                    "primary_key": list(config.primary_keys),
                    "write_disposition": {"disposition": "merge", "strategy": "upsert"}
                    if is_incremental
                    else "replace",
                    "endpoint": {"path": config.path, "params": params, "data_selector": config.data_selector},
                    "table_format": "delta",
                }
            ],
        }

        def save_cursor(state: Optional[dict[str, Any]]) -> None:
            if state and state.get("cursor"):
                resumable_source_manager.save_state(
                    BolRetailerResumeConfig(cursor=str(state["cursor"]), modified_since=modified_since)
                )

        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_cursor,
            initial_paginator_state={"cursor": resume.cursor} if resume is not None and resume.cursor else None,
        )
        # bol documents no order for offers, so the watermark is taken once the run ends.
        return SourceResponse(items=lambda: resource, sort_mode="desc", **response_kwargs)

    client = RESTClient(
        base_url=BOL_BASE_URL, headers={"Accept": config.accept}, auth=auth, request_timeout=REQUEST_TIMEOUT
    )
    if config.pagination == "invoice_windows":
        today = datetime.now(UTC).date()
        start = (
            date.fromisoformat(resume.window_start)
            if resume is not None and resume.window_start
            else today - timedelta(days=INVOICE_HISTORY_DAYS)
        )
        return SourceResponse(
            items=lambda: _invoice_windows(client, config, resumable_source_manager, start, today),
            **response_kwargs,
        )

    if config.per_change_day:
        today = datetime.now(UTC).date()
        floor = today - timedelta(days=ORDER_HISTORY_DAYS)
        if resume is not None and resume.window_start:
            first_day = date.fromisoformat(resume.window_start)
        elif should_use_incremental_field and db_incremental_field_last_value is not None:
            first_day = max(_to_date(db_incremental_field_last_value), floor)
        else:
            first_day = floor
        days = [first_day + timedelta(days=offset) for offset in range((today - first_day).days + 1)]
        passes = [{**dict(base), "latest-change-date": day.isoformat()} for day in days for base in config.passes]
        return SourceResponse(
            items=lambda: _paged_passes(
                client,
                config.path,
                config.data_selector,
                passes,
                resumable_source_manager,
                resume,
                window_start=first_day.isoformat(),
                row_map=flatten_order_items,
            ),
            # No sort_mode: the days come in order, but the rows inside a day have no documented order.
            **response_kwargs,
        )

    stop_before: tuple[str, datetime] | None = None
    if config.newest_first and should_use_incremental_field and db_incremental_field_last_value is not None:
        stop_before = (config.incremental_fields[0]["field"], _as_utc(db_incremental_field_last_value))
    return SourceResponse(
        items=lambda: _paged_passes(
            client,
            config.path,
            config.data_selector,
            [dict(params) for params in config.passes],
            resumable_source_manager,
            resume,
            stop_before=stop_before,
        ),
        # Newest-first lists take the watermark once the run ends.
        sort_mode="desc" if config.newest_first else "asc",
        **response_kwargs,
    )


def validate_credentials(client_id: str, client_secret: str) -> tuple[bool, str | None]:
    """Mint one access token. bol grants every Retailer API resource to the same client credentials."""
    try:
        # Setup waits on the probe, so it gets one attempt.
        response = make_tracked_session(
            redact_values=(client_secret,), capture=False, allow_redirects=False, retry=Retry(total=0)
        ).post(
            BOL_TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=HTTPBasicAuth(client_id, client_secret),
            headers={"Accept": "application/json"},
            timeout=TOKEN_TIMEOUT,
        )
    except Exception:  # noqa: BLE001 — a credential probe must never raise; any failure means "not validated"
        return False, "Could not connect to bol. Try again in a minute."
    if response.status_code == 200:
        return True, None
    if response.status_code in (400, 401):
        return (
            False,
            "bol rejected the client ID or secret. Copy both again from API settings in your seller dashboard.",
        )
    return False, "Could not connect to bol. Try again in a minute."
