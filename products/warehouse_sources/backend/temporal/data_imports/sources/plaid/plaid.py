import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.plaid.settings import PLAID_ENDPOINTS

PLAID_HOSTS = {
    "production": "https://production.plaid.com",
    "sandbox": "https://sandbox.plaid.com",
}
# /transactions/get pages cap at 500.
PAGE_SIZE = 500
# Plaid has no data before this; full transaction pulls start here.
DEFAULT_START_DATE = "2000-01-01"
# /transactions/get is limited to 30 req/min per Item — space requests out.
REQUEST_INTERVAL_SECONDS = 2.1
REQUEST_TIMEOUT_SECONDS = 120
MAX_RETRY_ATTEMPTS = 5


class PlaidRetryableError(Exception):
    pass


@dataclasses.dataclass
class PlaidResumeConfig:
    # /transactions/get paginates with options.offset; static body parts are
    # rebuilt deterministically from job inputs on resume.
    offset: int


def _get_session(secret: str, access_token: str) -> requests.Session:
    return make_tracked_session(redact_values=(secret, access_token))


def _base_url(environment: str) -> str:
    host = PLAID_HOSTS.get(environment)
    if host is None:
        raise ValueError(f"Invalid Plaid environment: {environment}")
    return host


def _format_date(value: Any) -> str:
    """Format an incremental cursor for Plaid's start_date filter (YYYY-MM-DD)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def validate_credentials(environment: str, client_id: str, secret: str, access_token: str) -> bool:
    """Confirm the credential triple is valid with a cheap /item/get probe."""
    try:
        response = _get_session(secret, access_token).post(
            f"{_base_url(environment)}/item/get",
            json={"client_id": client_id, "secret": secret, "access_token": access_token},
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    environment: str,
    client_id: str,
    secret: str,
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PlaidResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    session = _get_session(secret, access_token)
    base_url = _base_url(environment)
    credentials = {"client_id": client_id, "secret": secret, "access_token": access_token}

    @retry(
        retry=retry_if_exception_type((PlaidRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=5, max=120),
        reraise=True,
    )
    def post(path: str, body: dict[str, Any]) -> dict[str, Any]:
        # Stay under the 30 req/min per-Item budget.
        time.sleep(REQUEST_INTERVAL_SECONDS)
        url = f"{base_url}{path}"
        response = session.post(url, json={**credentials, **body}, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise PlaidRetryableError(f"Plaid API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Plaid API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    if endpoint == "accounts":
        data = post("/accounts/get", {})
        items = data.get("accounts", []) or []
        if items:
            yield items
        return

    # transactions
    start_date = (
        _format_date(db_incremental_field_last_value)
        if should_use_incremental_field and db_incremental_field_last_value is not None
        else DEFAULT_START_DATE
    )
    end_date = _today()

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume_config.offset if resume_config is not None else 0
    if resume_config is not None:
        logger.debug(f"Plaid: resuming transactions from offset {offset}")

    while True:
        data = post(
            "/transactions/get",
            {
                "start_date": start_date,
                "end_date": end_date,
                "options": {"count": PAGE_SIZE, "offset": offset},
            },
        )
        items = data.get("transactions", []) or []

        if items:
            yield items

        total = data.get("total_transactions")
        offset += len(items)
        if not items or (isinstance(total, int) and offset >= total):
            break

        # Save state AFTER yielding the page so a crash re-yields the last page
        # (merge dedupes on primary key) rather than skipping it.
        resumable_source_manager.save_state(PlaidResumeConfig(offset=offset))


def plaid_source(
    environment: str,
    client_id: str,
    secret: str,
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PlaidResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = PLAID_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            environment=environment,
            client_id=client_id,
            secret=secret,
            access_token=access_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint == "transactions" else None,
        partition_format="month" if endpoint == "transactions" else None,
        partition_keys=["date"] if endpoint == "transactions" else None,
        # /transactions/get returns newest-first; the pipeline commits desc
        # watermarks only when a run completes.
        sort_mode="desc" if endpoint == "transactions" else "asc",
    )
