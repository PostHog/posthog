import json
import sqlite3
import tempfile
from collections.abc import Callable, Iterable, Iterator
from dataclasses import field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import requests
import structlog
from requests import PreparedRequest

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_selling_partner.settings import (
    DEFERRED_RELEASE_SWEEP_DAYS,
    EARLIEST_START,
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
    SP_API_MAX_RETRY_ATTEMPTS,
    SP_API_RETRY_BACKOFF_MAX_SECONDS,
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

logger = structlog.get_logger(__name__)

LWA_REJECTED_MESSAGE = (
    "Amazon rejected the Login with Amazon credentials. "
    "Check the client ID, client secret and refresh token, then try again."
)
ACCESS_DENIED_MESSAGE = (
    "Amazon accepted the login but refused the Selling Partner API call. "
    "Check that the app is authorized for this seller and has the roles the tables need."
)
UNAVAILABLE_MESSAGE = "Couldn't reach Amazon to check the credentials. Try again in a few minutes."

REQUEST_TIMEOUT = (10.0, 30.0)
INVENTORY_ROWS_PER_BATCH = 2000
ResumeHook = Callable[[Optional[dict[str, Any]]], None]


@frozen
class AmazonSellingPartnerResumeConfig:
    # The page token of the endpoint being walked, when the vendor's token outlives a hand-off.
    next_token: str | None = None
    # The transactions window being walked. Amazon accepts a page token only with the arguments that produced it.
    window_start: str | None = None
    window_end: str | None = None
    transaction_status: str | None = None
    # Marketplaces whose inventory walk finished. Inventory page tokens expire in 30 seconds, so a
    # marketplace restarts from its first page.
    completed_marketplaces: list[str] = field(default_factory=list)
    marketplace_id: str | None = None
    last_seller_sku: str | None = None


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
    transaction_status: str | None = None


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
        "client": {
            "base_url": _base_url(region),
            "auth": auth,
            "max_retries": SP_API_MAX_RETRY_ATTEMPTS,
            "retry_backoff_max_seconds": SP_API_RETRY_BACKOFF_MAX_SECONDS,
            # Order bodies carry buyer data that only the row maps remove, after any sample is taken.
            "capture": False,
        },
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


def drop_buyer_personal_data(order: dict[str, Any]) -> dict[str, Any]:
    """Remove the buyer's personal data that rides inside the TAX and FULFILLMENT datasets."""
    tax = order.get("tax")
    if isinstance(tax, dict):
        tax.pop("taxRegistrations", None)
    for item in order.get("orderItems") or []:
        product = item.get("product")
        if isinstance(product, dict):
            product.pop("customization", None)
        gift_option = ((item.get("fulfillment") or {}).get("packing") or {}).get("giftOption")
        if isinstance(gift_option, dict):
            gift_option.pop("giftMessage", None)
    return order


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
    resource.add_map(drop_buyer_personal_data)
    if endpoint == ORDER_ITEMS:
        resource.add_map(explode_order_items)
    return resource


def deferred_release_sweep(now: datetime) -> TransactionWindow:
    cutoff = now - timedelta(seconds=REQUEST_TIME_MARGIN_SECONDS)
    return TransactionWindow(
        posted_after=cutoff - timedelta(days=DEFERRED_RELEASE_SWEEP_DAYS),
        posted_before=cutoff,
        transaction_status="DEFERRED_RELEASED",
    )


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
    now = datetime.now(UTC)
    start = parse_datetime_value(EARLIEST_START)
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        start = parse_datetime_value(db_incremental_field_last_value) or start
    assert start is not None
    windows = transaction_windows(start, now)
    initial_paginator_state: dict[str, Any] | None = None
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.window_start and resume.window_end:
        after, before = parse_datetime_value(resume.window_start), parse_datetime_value(resume.window_end)
        if after is not None and before is not None:
            current = TransactionWindow(
                posted_after=after, posted_before=before, transaction_status=resume.transaction_status
            )
            windows = [current]
            if current.transaction_status is None:
                windows += transaction_windows(before, now)
            if resume.next_token:
                initial_paginator_state = {"cursor": resume.next_token}
    # A first sync reads the whole history already, so the sweep would only repeat rows.
    has_watermark = should_use_incremental_field and db_incremental_field_last_value is not None
    if has_watermark and (not windows or windows[-1].transaction_status is None):
        windows.append(deferred_release_sweep(now))

    def state_for(window: TransactionWindow, next_token: str | None = None) -> AmazonSellingPartnerResumeConfig:
        return AmazonSellingPartnerResumeConfig(
            window_start=to_iso8601(window.posted_after),
            window_end=to_iso8601(window.posted_before),
            transaction_status=window.transaction_status,
            next_token=next_token,
        )

    def pages() -> Iterator[Any]:
        for index, window in enumerate(windows):
            following = windows[index + 1] if index + 1 < len(windows) else None

            def save_checkpoint(
                state: dict[str, Any] | None,
                window: TransactionWindow = window,
                following: TransactionWindow | None = following,
            ) -> None:
                if state and state.get("cursor"):
                    resumable_source_manager.save_state(state_for(window, str(state["cursor"])))
                elif following is not None:
                    # Staged before the window's last page is handed on, so a resume skips the window.
                    resumable_source_manager.save_state(state_for(following))

            params: dict[str, Any] = {
                "postedAfter": to_iso8601(window.posted_after),
                "postedBefore": to_iso8601(window.posted_before),
            }
            if window.transaction_status is not None:
                params["transactionStatus"] = window.transaction_status
            yield from _build_resource(
                region=region,
                auth=auth,
                name=TRANSACTIONS,
                path=TRANSACTIONS_PATH,
                data_selector="payload.transactions",
                cursor_path="payload.nextToken",
                cursor_param="nextToken",
                params=params,
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
    response = session.get(f"{_base_url(region)}{MARKETPLACE_PARTICIPATIONS_PATH}", auth=auth, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return [
        entry["marketplace"]["id"]
        for entry in response.json().get("payload") or []
        if (entry.get("participation") or {}).get("isParticipating", True)
    ]


def _spool_inventory_pages(
    session: requests.Session,
    auth: LwaAuth,
    url: str,
    marketplace_id: str,
    spool: sqlite3.Connection,
    manager: ResumableSourceManager[AmazonSellingPartnerResumeConfig],
    skip_if_not_covered: bool,
) -> bool:
    """Spool every page of one marketplace. False when Amazon rejects the marketplace on its first page."""
    next_token: str | None = None
    while True:
        params: dict[str, Any] = {
            "granularityType": "Marketplace",
            "granularityId": marketplace_id,
            "marketplaceIds": marketplace_id,
            "details": "true",
        }
        if next_token:
            params["nextToken"] = next_token
        response = session.get(url, params=params, auth=auth, timeout=REQUEST_TIMEOUT)
        # A discovered marketplace can be a channel FBA inventory does not cover. A later page's 400
        # is a real failure, such as an expired page token.
        if skip_if_not_covered and next_token is None and response.status_code == 400:
            return False
        response.raise_for_status()
        body = response.json()
        spool.executemany(
            "INSERT OR REPLACE INTO inventory VALUES (?, ?)",
            [
                (str(summary.get("sellerSku") or ""), json.dumps({"marketplaceId": marketplace_id, **summary}))
                for summary in (body.get("payload") or {}).get("inventorySummaries") or []
            ],
        )
        next_token = (body.get("pagination") or {}).get("nextToken")
        # The staged cursor does not cover this marketplace, so a hand-off here reads it again.
        manager.safe_point()
        if not next_token:
            return True


def _inventory_rows(
    *,
    region: str,
    auth: LwaAuth,
    marketplace_ids: list[str],
    resumable_source_manager: ResumableSourceManager[AmazonSellingPartnerResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    manager = resumable_source_manager
    resume = manager.load_state() if manager.can_resume() else None
    completed = list(resume.completed_marketplaces) if resume is not None else []
    session = make_tracked_session(redact_values=auth.secret_values())
    url = f"{_base_url(region)}{INVENTORY_SUMMARIES_PATH}"
    discovered = not marketplace_ids

    for marketplace_id in marketplace_ids or list_marketplace_ids(region, auth):
        if marketplace_id in completed:
            continue
        after_sku = resume.last_seller_sku if resume is not None and resume.marketplace_id == marketplace_id else None
        done_state = AmazonSellingPartnerResumeConfig(completed_marketplaces=[*completed, marketplace_id])
        # Page tokens expire in 30 seconds and Amazon documents no SKU order, so rows wait on disk
        # sorted by SKU and a resume continues after the last SKU handed on.
        with tempfile.TemporaryDirectory() as spool_dir:
            # The pipeline may resume this generator on another thread.
            spool = sqlite3.connect(Path(spool_dir) / "inventory.sqlite", check_same_thread=False)
            try:
                spool.execute("CREATE TABLE inventory (seller_sku TEXT PRIMARY KEY, row TEXT NOT NULL)")
                if not _spool_inventory_pages(
                    session, auth, url, marketplace_id, spool, manager, skip_if_not_covered=discovered
                ):
                    logger.warning(
                        "amazon_selling_partner_inventory_marketplace_skipped", marketplace_id=marketplace_id
                    )
                    manager.save_state(done_state)
                    manager.safe_point()
                    completed = done_state.completed_marketplaces
                    continue
                cursor = spool.execute(
                    "SELECT seller_sku, row FROM inventory WHERE seller_sku > ? ORDER BY seller_sku", (after_sku or "",)
                )
                batch = cursor.fetchmany(INVENTORY_ROWS_PER_BATCH)
                if not batch:
                    manager.save_state(done_state)
                    manager.safe_point()
                while batch:
                    following = cursor.fetchmany(INVENTORY_ROWS_PER_BATCH)
                    manager.save_state(
                        done_state
                        if not following
                        else AmazonSellingPartnerResumeConfig(
                            completed_marketplaces=completed,
                            marketplace_id=marketplace_id,
                            last_seller_sku=batch[-1][0],
                        )
                    )
                    yield [json.loads(row) for _, row in batch]
                    batch = following
            finally:
                spool.close()
        completed = done_state.completed_marketplaces


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
    items: Callable[[], Iterable[Any]]
    column_hints: dict[str, Any] | None = None
    if endpoint == INVENTORY_SUMMARIES:
        items = lambda: _inventory_rows(
            region=region, auth=auth, marketplace_ids=marketplace_ids, resumable_source_manager=resumable_source_manager
        )
    else:
        resource: Resource
        if endpoint in (ORDERS, ORDER_ITEMS):
            resource = _orders_resource(marketplace_ids=marketplace_ids, endpoint=endpoint, **common)
        elif endpoint == TRANSACTIONS:
            resource = _transactions_resource(**common)
        else:
            raise ValueError(f"Unknown Amazon Selling Partner endpoint: {endpoint}")
        items = lambda: resource
        column_hints = resource.column_hints

    partition_key = PARTITION_KEYS.get(endpoint)
    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=PRIMARY_KEYS[endpoint],
        # Amazon documents no order for any of these listings. Desc stores the watermark when the
        # run completes, which is correct whichever order the rows arrive in.
        sort_mode="desc",
        partition_count=1 if partition_key else None,
        partition_size=1 if partition_key else None,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
        column_hints=column_hints,
    )


def validate_credentials(
    region: str, client_id: str, client_secret: str, refresh_token: str
) -> tuple[bool, str | None]:
    auth = LwaAuth(client_id, client_secret, refresh_token)
    session = make_tracked_session(redact_values=auth.secret_values(), capture=False)
    try:
        response = session.get(
            f"{_base_url(region)}{MARKETPLACE_PARTICIPATIONS_PATH}", auth=auth, timeout=REQUEST_TIMEOUT
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
