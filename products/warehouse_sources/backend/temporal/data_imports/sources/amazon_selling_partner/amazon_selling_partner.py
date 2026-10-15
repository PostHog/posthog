from collections.abc import Callable, Iterator
from dataclasses import field
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

import requests
from requests import PreparedRequest

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_selling_partner.settings import (
    EARLIEST_START,
    INVENTORY_MAX_LOOKBACK_DAYS,
    INVENTORY_SUMMARIES,
    INVENTORY_SUMMARIES_PATH,
    LWA_TOKEN_URL,
    MARKETPLACE_PARTICIPATIONS_PATH,
    ORDER_ITEMS,
    ORDERS,
    ORDERS_INCLUDED_DATA,
    ORDERS_PAGE_SIZE,
    ORDERS_PATH,
    PARTITION_KEYS,
    PRIMARY_KEYS,
    REQUEST_TIME_MARGIN_SECONDS,
    SP_API_HOSTS,
    TRANSACTIONS,
    TRANSACTIONS_PATH,
    TRANSACTIONS_WINDOW_DAYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAuth2Auth,
    OAuth2AuthRequestError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

LWA_REJECTED_MESSAGE = (
    "Amazon rejected the Login with Amazon credentials. "
    "Check the client ID, client secret and refresh token, then try again."
)
ACCESS_DENIED_MESSAGE = (
    "Amazon accepted the login but refused the Selling Partner API call. "
    "Check that the app is authorized for this seller and has the roles the tables need."
)
UNAVAILABLE_MESSAGE = "Couldn't reach Amazon to check the credentials. Try again in a few minutes."

PROBE_TIMEOUT = (10.0, 30.0)
ResumeHook = Callable[[Optional[dict[str, Any]]], None]


@frozen
class AmazonSellingPartnerResumeConfig:
    # The page token of the endpoint being walked, when the vendor's token outlives a hand-off.
    next_token: str | None = None
    # The start of the transactions window being walked.
    window_start: str | None = None
    # Marketplaces whose inventory walk finished; their page tokens expire in 30 seconds, so a
    # marketplace restarts from its first page.
    completed_marketplaces: list[str] = field(default_factory=list)


class LwaAuth(OAuth2Auth):
    """Login with Amazon refresh-token grant. SP-API reads the token from `x-amz-access-token`."""

    def __init__(self, client_id: str, client_secret: str, refresh_token: str) -> None:
        super().__init__(
            token_url=LWA_TOKEN_URL,
            client_id=client_id,
            client_secret=client_secret,
            grant_type="refresh_token",
            refresh_token=refresh_token,
        )

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        if self.token is None or self._is_token_expired():
            self._obtain_token()
        assert self.token is not None
        request.headers["x-amz-access-token"] = self.token
        return request


def to_iso8601(value: Any) -> str:
    parsed = parse_datetime_value(value)
    if parsed is None:
        return str(value)
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_marketplace_ids(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


@frozen
class TransactionWindow:
    posted_after: datetime
    posted_before: datetime


def transaction_windows(start: datetime, now: datetime) -> list[TransactionWindow]:
    """Contiguous [postedAfter, postedBefore) windows from `start` up to the latest time Amazon accepts."""
    cutoff = now - timedelta(seconds=REQUEST_TIME_MARGIN_SECONDS)
    windows: list[TransactionWindow] = []
    while start < cutoff:
        end = min(start + timedelta(days=TRANSACTIONS_WINDOW_DAYS), cutoff)
        windows.append(TransactionWindow(posted_after=start, posted_before=end))
        start = end
    return windows


def _base_url(region: str) -> str:
    host = SP_API_HOSTS.get(region)
    if host is None:
        raise ValueError(f"Invalid Amazon Selling Partner region: {region}")
    return host


def _write_disposition(merge: bool) -> Any:
    return {"disposition": "merge", "strategy": "upsert"} if merge else "replace"


def _build_resource(
    *,
    region: str,
    auth: LwaAuth,
    name: str,
    path: str,
    data_selector: str,
    cursor_path: str,
    cursor_param: str,
    params: dict[str, Any],
    merge: bool,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Any,
    resume_hook: ResumeHook | None = None,
    initial_paginator_state: dict[str, Any] | None = None,
) -> Resource:
    config: RESTAPIConfig = {
        "client": {"base_url": _base_url(region), "auth": auth},
        "resource_defaults": {},
        "resources": [
            {
                "name": name,
                "table_name": name,
                "write_disposition": _write_disposition(merge),
                "endpoint": {
                    "path": path,
                    "data_selector": data_selector,
                    "data_selector_empty_ok": True,
                    "paginator": {"type": "cursor", "cursor_path": cursor_path, "cursor_param": cursor_param},
                    "params": params,
                },
                "table_format": "delta",
            }
        ],
    }
    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=resume_hook,
        initial_paginator_state=initial_paginator_state,
    )


def _wrapper_hints(name: str, merge: bool) -> dict[str, Any]:
    return {"table_name": name, "write_disposition": _write_disposition(merge), "table_format": "delta"}


def explode_order_items(order: dict[str, Any]) -> list[dict[str, Any]]:
    parent = {key: order.get(key) for key in ("orderId", "createdTime", "lastUpdatedTime")}
    parent["marketplaceId"] = (order.get("salesChannel") or {}).get("marketplaceId")
    return [{**parent, **item} for item in order.get("orderItems") or []]


def _orders_resource(
    *,
    region: str,
    auth: LwaAuth,
    marketplace_ids: list[str],
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AmazonSellingPartnerResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Resource:
    initial_paginator_state: dict[str, Any] | None = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_token:
            initial_paginator_state = {"cursor": resume.next_token}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state and state.get("cursor"):
            resumable_source_manager.save_state(AmazonSellingPartnerResumeConfig(next_token=str(state["cursor"])))

    resource = _build_resource(
        region=region,
        auth=auth,
        name=endpoint,
        path=ORDERS_PATH,
        data_selector="orders",
        cursor_path="pagination.nextToken",
        cursor_param="paginationToken",
        params={
            "maxResultsPerPage": ORDERS_PAGE_SIZE,
            "includedData": ORDERS_INCLUDED_DATA,
            "marketplaceIds": ",".join(marketplace_ids) or None,
            # Exactly one of createdAfter and lastUpdatedAfter is required; the latter also
            # covers a full refresh, because an order's last update is never before its creation.
            "lastUpdatedAfter": {
                "type": "incremental",
                "cursor_path": "lastUpdatedTime",
                "initial_value": EARLIEST_START,
                "convert": to_iso8601,
            },
        },
        merge=should_use_incremental_field,
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    if endpoint == ORDER_ITEMS:
        resource.add_map(explode_order_items)
    return resource


def _transactions_resource(
    *,
    region: str,
    auth: LwaAuth,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AmazonSellingPartnerResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Resource:
    start = parse_datetime_value(EARLIEST_START)
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        start = parse_datetime_value(db_incremental_field_last_value) or start
    initial_paginator_state: dict[str, Any] | None = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.window_start:
            start = parse_datetime_value(resume.window_start) or start
            if resume.next_token:
                initial_paginator_state = {"cursor": resume.next_token}
    assert start is not None
    windows = transaction_windows(start, datetime.now(UTC))

    def pages() -> Iterator[Any]:
        for index, window in enumerate(windows):
            window_start, window_end = window.posted_after, window.posted_before
            next_start = windows[index + 1].posted_after if index + 1 < len(windows) else None

            def save_checkpoint(
                state: dict[str, Any] | None,
                window_start: datetime = window_start,
                next_start: datetime | None = next_start,
            ) -> None:
                if state and state.get("cursor"):
                    resumable_source_manager.save_state(
                        AmazonSellingPartnerResumeConfig(
                            window_start=to_iso8601(window_start), next_token=str(state["cursor"])
                        )
                    )
                elif next_start is not None:
                    # Staged before the window's last page is handed on, so a resume skips the window.
                    resumable_source_manager.save_state(
                        AmazonSellingPartnerResumeConfig(window_start=to_iso8601(next_start))
                    )

            yield from _build_resource(
                region=region,
                auth=auth,
                name=TRANSACTIONS,
                path=TRANSACTIONS_PATH,
                data_selector="payload.transactions",
                cursor_path="payload.nextToken",
                cursor_param="nextToken",
                params={"postedAfter": to_iso8601(window_start), "postedBefore": to_iso8601(window_end)},
                merge=should_use_incremental_field,
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=None,
                resume_hook=save_checkpoint,
                initial_paginator_state=initial_paginator_state if index == 0 else None,
            )

    return Resource(pages, name=TRANSACTIONS, hints=_wrapper_hints(TRANSACTIONS, should_use_incremental_field))


def list_marketplace_ids(region: str, auth: LwaAuth) -> list[str]:
    session = make_tracked_session(redact_values=auth.secret_values())
    response = session.get(f"{_base_url(region)}{MARKETPLACE_PARTICIPATIONS_PATH}", auth=auth, timeout=PROBE_TIMEOUT)
    response.raise_for_status()
    return [
        entry["marketplace"]["id"]
        for entry in response.json().get("payload") or []
        if (entry.get("participation") or {}).get("isParticipating", True)
    ]


def _inventory_resource(
    *,
    region: str,
    auth: LwaAuth,
    marketplace_ids: list[str],
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AmazonSellingPartnerResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Resource:
    completed: list[str] = []
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            completed = list(resume.completed_marketplaces)
    start_date_time: str | None = None
    watermark = parse_datetime_value(db_incremental_field_last_value) if should_use_incremental_field else None
    if watermark is not None:
        start_date_time = to_iso8601(max(watermark, datetime.now(UTC) - timedelta(days=INVENTORY_MAX_LOOKBACK_DAYS)))

    def pages() -> Iterator[Any]:
        marketplaces = marketplace_ids or list_marketplace_ids(region, auth)
        for marketplace_id in marketplaces:
            if marketplace_id in completed:
                continue

            def save_checkpoint(state: dict[str, Any] | None, marketplace_id: str = marketplace_id) -> None:
                if not state or not state.get("cursor"):
                    resumable_source_manager.save_state(
                        AmazonSellingPartnerResumeConfig(completed_marketplaces=[*completed, marketplace_id])
                    )

            def tag_marketplace(row: dict[str, Any], marketplace_id: str = marketplace_id) -> dict[str, Any]:
                return {"marketplaceId": marketplace_id, **row}

            resource = _build_resource(
                region=region,
                auth=auth,
                name=INVENTORY_SUMMARIES,
                path=INVENTORY_SUMMARIES_PATH,
                data_selector="payload.inventorySummaries",
                cursor_path="pagination.nextToken",
                cursor_param="nextToken",
                params={
                    "granularityType": "Marketplace",
                    "granularityId": marketplace_id,
                    "marketplaceIds": marketplace_id,
                    "details": "true",
                    "startDateTime": start_date_time,
                },
                merge=should_use_incremental_field,
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=None,
                resume_hook=save_checkpoint,
            )
            yield from resource.add_map(tag_marketplace)
            completed.append(marketplace_id)

    return Resource(
        pages, name=INVENTORY_SUMMARIES, hints=_wrapper_hints(INVENTORY_SUMMARIES, should_use_incremental_field)
    )


def amazon_selling_partner_source(
    *,
    region: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    marketplace_ids: list[str],
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AmazonSellingPartnerResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> SourceResponse:
    auth = LwaAuth(client_id, client_secret, refresh_token)
    common = {
        "region": region,
        "auth": auth,
        "team_id": team_id,
        "job_id": job_id,
        "resumable_source_manager": resumable_source_manager,
        "should_use_incremental_field": should_use_incremental_field,
        "db_incremental_field_last_value": db_incremental_field_last_value,
    }
    resource: Resource
    if endpoint in (ORDERS, ORDER_ITEMS):
        resource = _orders_resource(marketplace_ids=marketplace_ids, endpoint=endpoint, **common)
    elif endpoint == TRANSACTIONS:
        resource = _transactions_resource(**common)
    elif endpoint == INVENTORY_SUMMARIES:
        resource = _inventory_resource(marketplace_ids=marketplace_ids, **common)
    else:
        raise ValueError(f"Unknown Amazon Selling Partner endpoint: {endpoint}")

    partition_key = PARTITION_KEYS.get(endpoint)
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS[endpoint],
        # Amazon documents no order for any of these listings.
        sort_mode=None,
        partition_count=1 if partition_key else None,
        partition_size=1 if partition_key else None,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(
    region: str, client_id: str, client_secret: str, refresh_token: str
) -> tuple[bool, str | None]:
    auth = LwaAuth(client_id, client_secret, refresh_token)
    session = make_tracked_session(redact_values=auth.secret_values(), capture=False)
    try:
        response = session.get(
            f"{_base_url(region)}{MARKETPLACE_PARTICIPATIONS_PATH}", auth=auth, timeout=PROBE_TIMEOUT
        )
    except OAuth2AuthRequestError as e:
        return False, LWA_REJECTED_MESSAGE if e.is_permanent else UNAVAILABLE_MESSAGE
    except requests.RequestException:
        return False, UNAVAILABLE_MESSAGE
    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, ACCESS_DENIED_MESSAGE
    return False, UNAVAILABLE_MESSAGE
