import time
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.airtable.settings import AIRTABLE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

AIRTABLE_BASE_URL = "https://api.airtable.com/v0"
# Record list pages cap at 100.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Airtable allows 5 req/s per base and imposes a 30s cooldown after a 429, so
# requests are proactively spaced and backoff starts above the cooldown.
REQUEST_INTERVAL_SECONDS = 0.21
MAX_RETRY_ATTEMPTS = 5


class AirtableRetryableError(Exception):
    pass


def _get_session(personal_access_token: str) -> requests.Session:
    return make_tracked_session(
        headers={"Authorization": f"Bearer {personal_access_token}"}, redact_values=(personal_access_token,)
    )


def _format_created_time(value: Any) -> str:
    """Format an incremental cursor for an IS_AFTER(CREATED_TIME(), ...) formula (ISO 8601 UTC)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00.000Z")
    return str(value)


def validate_credentials(personal_access_token: str) -> bool:
    """Confirm the PAT is valid with a cheap one-base meta probe."""
    try:
        response = _get_session(personal_access_token).get(
            f"{AIRTABLE_BASE_URL}/meta/bases",
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    personal_access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    session = _get_session(personal_access_token)

    @retry(
        retry=retry_if_exception_type((AirtableRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        # First retry waits out Airtable's 30s post-429 cooldown.
        wait=wait_exponential_jitter(initial=31, max=120),
        reraise=True,
    )
    def fetch(path: str, params: dict[str, Any]) -> dict[str, Any]:
        # Stay under the 5 req/s per-base budget.
        time.sleep(REQUEST_INTERVAL_SECONDS)
        url = f"{AIRTABLE_BASE_URL}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise AirtableRetryableError(f"Airtable API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Airtable API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    def iterate_bases() -> Iterator[list[dict[str, Any]]]:
        # List-page offsets expire after a few minutes of inactivity, so page
        # chains are never persisted — a retried sync restarts the chain.
        offset: Optional[str] = None
        while True:
            params: dict[str, Any] = {"offset": offset} if offset else {}
            data = fetch("/meta/bases", params)
            items = data.get("bases", []) or []
            if items:
                yield items
            offset = data.get("offset")
            if not offset or not items:
                return

    def tables_for_base(base_id: str) -> list[dict[str, Any]]:
        data = fetch(f"/meta/bases/{quote(base_id)}/tables", {})
        return data.get("tables", []) or []

    if endpoint == "bases":
        yield from iterate_bases()
        return

    base_ids = [base["id"] for page in iterate_bases() for base in page]

    if endpoint == "tables":
        for base_id in base_ids:
            tables = [{**table, "_base_id": base_id} for table in tables_for_base(base_id)]
            if tables:
                yield tables
        return

    # records: fan out over every table of every base.
    created_after = (
        _format_created_time(db_incremental_field_last_value)
        if should_use_incremental_field and db_incremental_field_last_value is not None
        else None
    )

    for base_id in base_ids:
        for table in tables_for_base(base_id):
            table_id = table["id"]
            offset = None
            while True:
                params: dict[str, Any] = {"pageSize": PAGE_SIZE}
                if created_after is not None:
                    params["filterByFormula"] = f'IS_AFTER(CREATED_TIME(), "{created_after}")'
                if offset:
                    params["offset"] = offset
                data = fetch(f"/{quote(base_id)}/{quote(table_id)}", params)
                items = [
                    {**record, "_base_id": base_id, "_table_id": table_id} for record in (data.get("records", []) or [])
                ]
                if items:
                    yield items
                offset = data.get("offset")
                if not offset or not items:
                    break


def airtable_source(
    personal_access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = AIRTABLE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            personal_access_token=personal_access_token,
            endpoint=endpoint,
            logger=logger,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )
