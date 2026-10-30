import gzip
import json
import time
import sqlite3
import tempfile
from collections.abc import Callable, Iterable, Iterator
from dataclasses import field
from datetime import UTC, datetime, timedelta
from itertools import batched
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qsl, urlsplit

import requests
import structlog
from requests import PreparedRequest
from urllib3.util.retry import Retry

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_selling_partner.settings import (
    DEFERRED_RELEASE_SWEEP_DAYS,
    EARLIEST_START,
    INVENTORY_SUMMARIES,
    INVENTORY_SUMMARIES_PATH,
    LWA_TOKEN_URL,
    MARKETPLACE_CURRENCIES,
    MARKETPLACE_PARTICIPATIONS_PATH,
    ORDER_ITEMS,
    ORDERS,
    ORDERS_INCLUDED_DATA,
    ORDERS_PAGE_SIZE,
    ORDERS_PATH,
    PARTITION_KEYS,
    PRIMARY_KEYS,
    REPORT_DOCUMENTS_PATH,
    REPORTS_PATH,
    REQUEST_TIME_MARGIN_SECONDS,
    SP_API_HOSTS,
    SP_API_MAX_RETRY_ATTEMPTS,
    SP_API_RETRY_BACKOFF_MAX_SECONDS,
    TRANSACTIONS,
    TRANSACTIONS_PATH,
    TRANSACTIONS_WINDOW_DAYS,
    VENDOR_REPORTS,
    VENDOR_SALES,
    VendorReport,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.interruptible_wait import (
    interruptible_wait,
)
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
    "Amazon accepted the login but refused the Selling Partner API calls. "
    "Check that the region matches the account, that the account authorized the app, "
    "and that the app has the roles the tables need."
)
UNAVAILABLE_MESSAGE = "Couldn't reach Amazon to check the credentials. Try again in a few minutes."
MISSING_MARKETPLACES_MESSAGE = "Vendor reports need marketplace IDs. Add them in the source settings."
SELLER_ONLY_MESSAGE = "This table needs a seller account with the role listed in the source description."
VENDOR_ONLY_MESSAGE = "This table needs a vendor account with the Brand Analytics role."

REQUEST_TIMEOUT = (10.0, 30.0)
# The table picker waits on the probes inside one setup request, so they share a short budget.
PROBE_TIMEOUT = (5.0, 10.0)
PROBE_BUDGET_SECONDS = 30.0
INVENTORY_ROWS_PER_BATCH = 2000
REPORT_POLL_INTERVAL_SECONDS = 30
# A report still pending after this long fails the attempt; the next attempt polls the same report.
REPORT_POLL_BUDGET_SECONDS = 60 * 60
# createReport allows one call a minute after a burst of 15, and Amazon sends no Retry-After.
REPORT_CREATE_ATTEMPTS = 5
REPORT_CREATE_BACKOFF_SECONDS = 60
REPORT_DOWNLOAD_TIMEOUT = (10.0, 300.0)
# A FATAL report for a window that ended this recently may only mean Amazon has not published it yet.
REPORT_PUBLISH_GRACE = timedelta(days=7)
REPORT_FATAL_ATTEMPTS = 3
REPORT_DOWNLOAD_CHUNK_BYTES = 1024 * 1024
REPORT_ROWS_PER_BATCH = 2000
# The document sits on presigned Amazon storage. Pinning the host keeps a tampered `url` from
# sending the download anywhere else.
REPORT_URL_HOST_SUFFIXES = (".amazonaws.com", ".amazon.com")
ResumeHook = Callable[[Optional[dict[str, Any]]], None]


@frozen
class AmazonSellingPartnerResumeConfig:
    # The page token of the endpoint being walked, when the vendor's token outlives a hand-off.
    next_token: str | None = None
    # The transactions window being walked. Amazon accepts a page token only with the arguments that produced it.
    window_start: str | None = None
    window_end: str | None = None
    transaction_status: str | None = None
    # Marketplaces whose walk finished.
    completed_marketplaces: list[str] = field(default_factory=list)
    marketplace_id: str | None = None
    last_seller_sku: str | None = None
    # A vendor report being handed on, so a resume polls it and skips its rows already handed on.
    report_id: str | None = None
    rows_done: int = 0


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
            # Without this a stalled SP-API host holds the whole retry budget in one try, and the
            # waits above never run. The seller's other calls use the same bound.
            "request_timeout": REQUEST_TIMEOUT,
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


def list_marketplace_ids(
    region: str,
    auth: LwaAuth,
    session: requests.Session | None = None,
    timeout: tuple[float, float] = REQUEST_TIMEOUT,
) -> list[str]:
    session = session or make_tracked_session(redact_values=auth.secret_values())
    response = session.get(f"{_base_url(region)}{MARKETPLACE_PARTICIPATIONS_PATH}", auth=auth, timeout=timeout)
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


class VendorReportError(Exception):
    """Amazon finished a report with FATAL status. The retry requests a new report for the same window."""


class VendorReportPendingError(Exception):
    """A report is still processing after the polling budget. The next attempt polls it again."""


@frozen
class ReportWindow:
    data_start_time: str
    data_end_time: str


def presigned_secret_values(url: str) -> tuple[str, ...]:
    """The signing material in a presigned document URL, which the shared scrubber does not mask by name."""
    return tuple(
        value for name, value in parse_qsl(urlsplit(url).query) if name.lower().startswith("x-amz-") and len(value) >= 8
    )


def report_windows(
    report: VendorReport, start: datetime | None, now: datetime, *, resumed: bool = False
) -> list[ReportWindow]:
    """The date ranges to request, oldest first, from `start` (or the oldest Amazon keeps) to the newest it publishes.

    A resumed `start` belongs to a report that already exists, so it is kept even when the lookback
    floor moved past it since the report was created.
    """
    if report.window is None or report.lookback is None:
        return []
    if report.hourly:
        newest = (now - report.availability_delay).replace(minute=0, second=0, microsecond=0)
        oldest = now.replace(minute=0, second=0, microsecond=0) - report.lookback
        if start is not None:
            start = start.replace(minute=0, second=0, microsecond=0)
        cursor = (start if resumed else max(start, oldest)) if start else oldest
        windows = []
        while cursor < newest:
            end = min(cursor + report.window, newest)
            windows.append(ReportWindow(data_start_time=to_iso8601(cursor), data_end_time=to_iso8601(end)))
            cursor = end
        return windows

    last_day = (now - report.availability_delay).date()
    oldest_day = now.date() - report.lookback
    day = (start.date() if resumed else max(start.date(), oldest_day)) if start else oldest_day
    windows = []
    while day <= last_day:
        end_day = min(day + report.window - timedelta(days=1), last_day)
        windows.append(
            ReportWindow(
                data_start_time=f"{day.isoformat()}T00:00:00Z", data_end_time=f"{end_day.isoformat()}T23:59:59Z"
            )
        )
        day = end_day + timedelta(days=1)
    return windows


class ReportsClient:
    def __init__(self, region: str, auth: LwaAuth) -> None:
        self._base_url = _base_url(region)
        self._auth = auth
        # Report and document bodies carry presigned download URLs, so they stay out of sample capture.
        self._session = make_tracked_session(redact_values=auth.secret_values(), capture=False)

    def create_report(self, body: dict[str, Any], safe_point: Callable[[], None]) -> str:
        for attempt in range(REPORT_CREATE_ATTEMPTS):
            response = self._session.post(
                f"{self._base_url}{REPORTS_PATH}", json=body, auth=self._auth, timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 429 and attempt + 1 < REPORT_CREATE_ATTEMPTS:
                interruptible_wait(REPORT_CREATE_BACKOFF_SECONDS, safe_point=safe_point)
                continue
            response.raise_for_status()
            return str(response.json()["reportId"])
        raise AssertionError("unreachable")

    def get_report(self, report_id: str) -> dict[str, Any]:
        response = self._session.get(
            f"{self._base_url}{REPORTS_PATH}/{report_id}", auth=self._auth, timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        return response.json()

    def get_document(self, document_id: str) -> dict[str, Any]:
        """Read a report document. Rows come back as JSON, unzipped when Amazon compressed them."""
        response = self._session.get(
            f"{self._base_url}{REPORT_DOCUMENTS_PATH}/{document_id}", auth=self._auth, timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        document = response.json()
        url = str(document["url"])
        host = (urlsplit(url).hostname or "").lower()
        if not host.endswith(REPORT_URL_HOST_SUFFIXES):
            raise ValueError(f"Amazon report document URL points outside Amazon: host={host}")
        # The presigned URL carries its own signature, so the download sends no LWA token.
        download = make_tracked_session(redact_values=presigned_secret_values(url), capture=False)
        # The stock error messages quote the whole URL, signature included, into the job's error and logs.
        # The download goes to a temporary file in chunks, so the compressed copy never sits in memory.
        with tempfile.TemporaryFile() as spool:
            try:
                with download.get(url, timeout=REPORT_DOWNLOAD_TIMEOUT, stream=True) as content_response:
                    if not content_response.ok:
                        raise requests.HTTPError(
                            f"Amazon report document download returned status={content_response.status_code}",
                            response=content_response,
                        )
                    for chunk in content_response.iter_content(chunk_size=REPORT_DOWNLOAD_CHUNK_BYTES):
                        spool.write(chunk)
            except requests.HTTPError:
                raise
            except requests.RequestException as e:
                raise requests.ConnectionError(f"Amazon report document download failed: {type(e).__name__}") from None
            spool.seek(0)
            if document.get("compressionAlgorithm") == "GZIP":
                with gzip.GzipFile(fileobj=spool) as unzipped:
                    return json.load(unzipped)
            return json.load(spool)


def await_report_document(
    client: ReportsClient, report: VendorReport, report_id: str, safe_point: Callable[[], None]
) -> dict[str, Any] | None:
    """Poll until the report is done. None means Amazon cancelled it because there was no data."""
    waited = 0
    while True:
        status = client.get_report(report_id)
        safe_point()
        processing_status = status.get("processingStatus")
        if processing_status == "DONE":
            return client.get_document(str(status["reportDocumentId"]))
        if processing_status == "CANCELLED":
            return None
        if processing_status == "FATAL":
            detail = ""
            if status.get("reportDocumentId"):
                detail = str(client.get_document(str(status["reportDocumentId"])).get("errorDetails") or "")
            raise VendorReportError(f"Amazon could not generate the {report.report_type} report: {detail}".strip())
        if waited >= REPORT_POLL_BUDGET_SECONDS:
            raise VendorReportPendingError(
                f"Amazon {report.report_type} report {report_id} is still {processing_status} after {waited} seconds"
            )
        interruptible_wait(REPORT_POLL_INTERVAL_SECONDS, safe_point=safe_point)
        waited += REPORT_POLL_INTERVAL_SECONDS


def _may_be_unpublished(report: VendorReport, data_end_time: str, now: datetime) -> bool:
    """Whether a FATAL report for this window can mean Amazon has not published the data yet."""
    end = parse_datetime_value(data_end_time)
    return end is None or end >= now - report.availability_delay - REPORT_PUBLISH_GRACE


def _after(report: VendorReport, data_end_time: str) -> datetime | None:
    """Where the window after one ending at `data_end_time` starts."""
    end = parse_datetime_value(data_end_time)
    if end is None or report.hourly:
        return end
    return datetime.combine(end.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC)


def _report_options(report: VendorReport, marketplace_id: str) -> dict[str, str]:
    if not report.needs_currency:
        return dict(report.options)
    currency = MARKETPLACE_CURRENCIES.get(marketplace_id)
    if currency is None:
        raise ValueError(f"Unknown Amazon marketplace ID for real-time sales: {marketplace_id}")
    return {**report.options, "currencyCode": currency}


def _vendor_report_rows(
    *,
    region: str,
    auth: LwaAuth,
    marketplace_ids: list[str],
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[AmazonSellingPartnerResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    if not marketplace_ids:
        raise ValueError(MISSING_MARKETPLACES_MESSAGE)
    report = VENDOR_REPORTS[endpoint]
    client = ReportsClient(region, auth)
    manager = resumable_source_manager
    resume = manager.load_state() if manager.can_resume() else None
    completed = list(resume.completed_marketplaces) if resume is not None else []
    watermark = parse_datetime_value(db_incremental_field_last_value) if should_use_incremental_field else None
    now = datetime.now(UTC)

    for marketplace_id in marketplace_ids:
        if marketplace_id in completed:
            continue
        pending = resume if resume is not None and resume.marketplace_id == marketplace_id else None
        windows: list[ReportWindow | None]
        if not report.window:
            windows = [None]
        elif pending is not None and pending.report_id and pending.window_start and pending.window_end:
            # The saved report covers the range it was created with. The next window starts right
            # after it, even when a partial window would come out longer today.
            saved = ReportWindow(data_start_time=pending.window_start, data_end_time=pending.window_end)
            windows = [saved, *report_windows(report, _after(report, pending.window_end), now, resumed=True)]
        else:
            resumed = pending is not None and pending.window_start is not None
            start = (
                parse_datetime_value(pending.window_start)
                if pending is not None and pending.window_start
                else watermark
            )
            windows = list(report_windows(report, start, now, resumed=resumed))

        for index, window in enumerate(windows):
            window_start = window.data_start_time if window is not None else None
            window_end = window.data_end_time if window is not None else None
            resuming = pending is not None and pending.window_start == window_start
            report_id = pending.report_id if pending is not None and resuming else None
            rows_done = pending.rows_done if pending is not None and resuming and report_id else 0
            pending = None
            following = windows[index + 1] if index + 1 < len(windows) else None
            next_state = (
                AmazonSellingPartnerResumeConfig(
                    completed_marketplaces=completed,
                    marketplace_id=marketplace_id,
                    window_start=following.data_start_time,
                )
                if following is not None
                else AmazonSellingPartnerResumeConfig(completed_marketplaces=[*completed, marketplace_id])
            )
            recent = window_end is None or _may_be_unpublished(report, window_end, now)
            document: dict[str, Any] | None = None
            for attempt in range(1, REPORT_FATAL_ATTEMPTS + 1):
                if report_id is None:
                    body: dict[str, Any] = {"reportType": report.report_type, "marketplaceIds": [marketplace_id]}
                    options = _report_options(report, marketplace_id)
                    if options:
                        body["reportOptions"] = options
                    if window is not None:
                        body["dataStartTime"] = window.data_start_time
                        body["dataEndTime"] = window.data_end_time
                    report_id = client.create_report(body, manager.safe_point)
                    rows_done = 0
                    # Staged, not committed: the pipeline commits it at a safe point once earlier rows are
                    # written, so an attempt that resumes polls this report instead of creating another.
                    manager.save_state(
                        AmazonSellingPartnerResumeConfig(
                            completed_marketplaces=completed,
                            marketplace_id=marketplace_id,
                            window_start=window_start,
                            window_end=window_end,
                            report_id=report_id,
                        )
                    )
                try:
                    document = await_report_document(client, report, report_id, manager.safe_point)
                    break
                except VendorReportError:
                    # A failed report stays failed, so a retry asks for a new one for the same window.
                    report_id = None
                    # FATAL can be a passing processing error, so an old window gets more reports in
                    # this run. A recent one may only be unpublished, so it waits for the next sync.
                    if not recent and attempt < REPORT_FATAL_ATTEMPTS:
                        continue
                    # The resume point stays on this window, so no later window moves the watermark past it.
                    manager.save_state(
                        AmazonSellingPartnerResumeConfig(
                            completed_marketplaces=completed,
                            marketplace_id=marketplace_id,
                            window_start=window_start,
                        )
                    )
                    manager.safe_point()
                    raise
            all_rows = (document or {}).get(report.rows_key) or []
            if rows_done >= len(all_rows):
                manager.save_state(next_state)
                manager.safe_point()
                continue
            for batch in batched(all_rows[rows_done:], REPORT_ROWS_PER_BATCH, strict=False):
                rows_done += len(batch)
                # A resumed full refresh would append handed-on rows again, so the offset moves with each batch.
                manager.save_state(
                    next_state
                    if rows_done >= len(all_rows)
                    else AmazonSellingPartnerResumeConfig(
                        completed_marketplaces=completed,
                        marketplace_id=marketplace_id,
                        window_start=window_start,
                        window_end=window_end,
                        report_id=report_id,
                        rows_done=rows_done,
                    )
                )
                yield [{"marketplaceId": marketplace_id, **row} for row in batch]
        completed = [*completed, marketplace_id]


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
    elif endpoint in VENDOR_REPORTS:
        items = lambda: _vendor_report_rows(
            region=region,
            auth=auth,
            marketplace_ids=marketplace_ids,
            endpoint=endpoint,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
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
    region: str, client_id: str, client_secret: str, refresh_token: str, marketplace_ids: list[str]
) -> tuple[bool, str | None]:
    auth = LwaAuth(client_id, client_secret, refresh_token)
    session = make_tracked_session(redact_values=auth.secret_values(), capture=False)
    base_url = _base_url(region)
    try:
        response = session.get(f"{base_url}{MARKETPLACE_PARTICIPATIONS_PATH}", auth=auth, timeout=REQUEST_TIMEOUT)
        if response.status_code == 403:
            # Vendor accounts always get 403 from the Sellers API, so ask the Reports API instead.
            response = session.get(
                f"{base_url}{REPORTS_PATH}",
                params={"reportTypes": VENDOR_REPORTS[VENDOR_SALES].report_type, "pageSize": "1"},
                auth=auth,
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code == 200 and not marketplace_ids:
                return False, MISSING_MARKETPLACES_MESSAGE
    except OAuth2AuthRequestError as e:
        return False, LWA_REJECTED_MESSAGE if e.is_permanent else UNAVAILABLE_MESSAGE
    except requests.RequestException:
        return False, UNAVAILABLE_MESSAGE
    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, ACCESS_DENIED_MESSAGE
    return False, UNAVAILABLE_MESSAGE


def _probe(session: requests.Session, auth: LwaAuth, url: str, params: dict[str, Any]) -> bool | None:
    """Whether Amazon allows the call. None when the answer says nothing about access."""
    try:
        response = session.get(url, params=params, auth=auth, timeout=PROBE_TIMEOUT)
    except (OAuth2AuthRequestError, requests.RequestException):
        return None
    if response.status_code in (401, 403):
        return False
    return True if response.ok else None


def probe_endpoint_permissions(
    region: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    marketplace_ids: list[str],
    endpoints: list[str],
) -> dict[str, str | None]:
    auth = LwaAuth(client_id, client_secret, refresh_token)
    session = make_tracked_session(redact_values=auth.secret_values(), capture=False, retry=Retry(total=0))
    base_url = _base_url(region)
    recent = to_iso8601(datetime.now(UTC) - timedelta(days=1))
    deadline = time.monotonic() + PROBE_BUDGET_SECONDS

    def probe_inventory() -> bool | None:
        marketplace_id = marketplace_ids[0] if marketplace_ids else None
        if marketplace_id is None:
            try:
                discovered = list_marketplace_ids(region, auth, session=session, timeout=PROBE_TIMEOUT)
            except requests.HTTPError as e:
                # Only an explicit rejection means the account is not a seller. Other failures stay unknown.
                status = e.response.status_code if e.response is not None else None
                return False if status in (401, 403) else None
            except (OAuth2AuthRequestError, requests.RequestException):
                return None
            if not discovered:
                return None
            marketplace_id = discovered[0]
        return _probe(
            session,
            auth,
            f"{base_url}{INVENTORY_SUMMARIES_PATH}",
            {"granularityType": "Marketplace", "granularityId": marketplace_id, "marketplaceIds": marketplace_id},
        )

    def probe(path: str, params: dict[str, Any]) -> Callable[[], bool | None]:
        return lambda: _probe(session, auth, f"{base_url}{path}", params)

    probes: dict[str, tuple[Callable[[], bool | None], str]] = {
        ORDERS: (
            probe(
                ORDERS_PATH,
                {
                    "maxResultsPerPage": 1,
                    "lastUpdatedAfter": recent,
                    "marketplaceIds": ",".join(marketplace_ids) or None,
                },
            ),
            SELLER_ONLY_MESSAGE,
        ),
        TRANSACTIONS: (probe(TRANSACTIONS_PATH, {"postedAfter": recent}), SELLER_ONLY_MESSAGE),
        INVENTORY_SUMMARIES: (probe_inventory, SELLER_ONLY_MESSAGE),
        VENDOR_SALES: (
            probe(REPORTS_PATH, {"reportTypes": VENDOR_REPORTS[VENDOR_SALES].report_type, "pageSize": 1}),
            VENDOR_ONLY_MESSAGE,
        ),
    }
    # One call answers for every table that needs the same role.
    probe_for = {ORDER_ITEMS: ORDERS, **dict.fromkeys(VENDOR_REPORTS, VENDOR_SALES)}
    answers: dict[str, bool | None] = {}
    permissions: dict[str, str | None] = {}
    for endpoint in endpoints:
        probe_name = probe_for.get(endpoint, endpoint)
        if probe_name not in probes:
            permissions[endpoint] = None
            continue
        run_probe, message = probes[probe_name]
        if probe_name not in answers:
            answers[probe_name] = run_probe() if time.monotonic() < deadline else None
        if answers[probe_name] is False:
            permissions[endpoint] = message
        elif endpoint in VENDOR_REPORTS and not marketplace_ids:
            permissions[endpoint] = MISSING_MARKETPLACES_MESSAGE
        else:
            permissions[endpoint] = None
    return permissions
