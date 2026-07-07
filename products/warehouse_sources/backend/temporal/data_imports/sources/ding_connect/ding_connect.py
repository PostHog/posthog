import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.ding_connect.settings import (
    DING_CONNECT_ENDPOINTS,
    DingConnectEndpointConfig,
)

DING_CONNECT_BASE_URL = "https://api.dingconnect.com"

# ListTransferRecords requires a Take (page size) and bypasses already-returned rows with Skip.
TRANSFER_RECORDS_PAGE_SIZE = 100

# Envelope keys returned alongside the data on every DingConnect response. Stripped from the
# single-object GetBalance response so only the balance fields land in the row.
_ENVELOPE_KEYS = ("ResultCode", "ErrorCodes", "ThereAreMoreItems")


class DingConnectRetryableError(Exception):
    pass


@dataclasses.dataclass
class DingConnectResumeConfig:
    # Number of TransferRecords rows already returned; the Skip value the next page resumes from.
    # Only the paginated TransferRecords endpoint persists this; reference endpoints complete in a
    # single request and never save state.
    skip: int = 0


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "api_key": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


@retry(
    retry=retry_if_exception_type((DingConnectRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _request(
    session: requests.Session,
    method: str,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    json_body: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    response = session.request(method, url, headers=headers, json=json_body, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise DingConnectRetryableError(f"DingConnect API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Truncate the body: DingConnect error responses can echo row data (e.g. AccountNumber from
        # TransferRecords), so we log only a short preview to avoid persisting PII in logs.
        logger.error(f"DingConnect API error: status={response.status_code}, body={response.text[:500]}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> bool:
    # GetBalance is the cheapest call that proves both the key is valid and an account is attached.
    url = f"{DING_CONNECT_BASE_URL}/api/V1/GetBalance"
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(url, headers=_get_headers(api_key), timeout=30)
        return response.status_code == 200
    except Exception:
        return False


def _flatten_transfer_record(record: dict[str, Any]) -> dict[str, Any]:
    """Lift the nested TransferId identifiers to the top level so TransferRef is a usable primary key."""
    transfer_id = record.get("TransferId")
    if isinstance(transfer_id, dict):
        record = {**record}
        record["TransferRef"] = transfer_id["TransferRef"]
        record["DistributorRef"] = transfer_id.get("DistributorRef")
    return record


def _row_from_single_object(body: dict[str, Any]) -> dict[str, Any]:
    """Build a single row from an envelope that carries the payload at the top level (GetBalance)."""
    return {key: value for key, value in body.items() if key not in _ENVELOPE_KEYS}


def _get_reference_rows(
    session: requests.Session,
    config: DingConnectEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    url = f"{DING_CONNECT_BASE_URL}{config.path}"
    body = _request(session, config.method, url, headers, logger)

    if config.data_selector == "":
        yield [_row_from_single_object(body)]
        return

    items = body.get(config.data_selector, []) or []
    if items:
        yield items


def _get_transfer_record_rows(
    session: requests.Session,
    config: DingConnectEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DingConnectResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    url = f"{DING_CONNECT_BASE_URL}{config.path}"

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    skip = resume.skip if resume is not None else 0
    if skip:
        logger.debug(f"DingConnect: resuming TransferRecords from skip={skip}")

    while True:
        body = _request(
            session,
            config.method,
            url,
            headers,
            logger,
            json_body={"Skip": skip, "Take": TRANSFER_RECORDS_PAGE_SIZE},
        )

        items = body.get(config.data_selector, []) or []
        if items:
            yield [_flatten_transfer_record(item) for item in items]

        # `ThereAreMoreItems` is the documented continuation flag; fall back to a short final page.
        there_are_more = body.get("ThereAreMoreItems")
        has_next = there_are_more if there_are_more is not None else len(items) == TRANSFER_RECORDS_PAGE_SIZE
        if not items or not has_next:
            break

        skip += TRANSFER_RECORDS_PAGE_SIZE
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it; the
        # full-refresh replace plus the TransferRef primary key dedupe any re-pulled rows.
        resumable_source_manager.save_state(DingConnectResumeConfig(skip=skip))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DingConnectResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = DING_CONNECT_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    session = make_tracked_session(redact_values=(api_key,))

    if config.paginated:
        yield from _get_transfer_record_rows(session, config, headers, logger, resumable_source_manager)
    else:
        yield from _get_reference_rows(session, config, headers, logger)


def ding_connect_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DingConnectResumeConfig],
) -> SourceResponse:
    config = DING_CONNECT_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
