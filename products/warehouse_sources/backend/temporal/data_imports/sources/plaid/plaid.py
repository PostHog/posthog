import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    make_tracked_session,
    retry_with_deadline,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
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


# Every country Plaid supports; /institutions/get_by_id requires the list and the Item's country is not known.
INSTITUTION_COUNTRY_CODES = [
    "US", "GB", "ES", "NL", "FR", "IE", "CA", "DE", "IT", "PL",
    "DK", "NO", "SE", "EE", "LT", "LV", "PT", "BE", "AT", "FI",
]  # fmt: skip
# Item errors that mean the Item has no data for the product, so the table is empty, not failed.
NO_PRODUCT_DATA_ERROR_CODES = frozenset(
    {"NO_ACCOUNTS", "NO_INVESTMENT_ACCOUNTS", "NO_LIABILITY_ACCOUNTS", "PRODUCTS_NOT_SUPPORTED"}
)
# endpoint -> (path, rows key, total count key) for endpoints paginated with options.offset.
OFFSET_PAGINATED_ENDPOINTS = {
    "transactions": ("/transactions/get", "transactions", "total_transactions"),
    "investment_transactions": (
        "/investments/transactions/get",
        "investment_transactions",
        "total_investment_transactions",
    ),
}
# endpoint -> the Plaid product the Item must already have before we call the endpoint.
PRODUCT_GATED_ENDPOINTS = {
    "investment_holdings": "investments",
    "investment_transactions": "investments",
    "liabilities": "liabilities",
}


class PlaidRetryableError(Exception):
    pass


class PlaidNoProductDataError(Exception):
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


def _error_code(response: requests.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    return body.get("error_code") if isinstance(body, dict) else None


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

    @retry_with_deadline(
        retry=retry_if_exception_type((PlaidRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=5, max=120),
        reraise=True,
    )
    def post(path: str, body: dict[str, Any], with_access_token: bool = True) -> dict[str, Any]:
        # Stay under the 30 req/min per-Item budget.
        time.sleep(REQUEST_INTERVAL_SECONDS)
        url = f"{base_url}{path}"
        auth = credentials if with_access_token else {"client_id": client_id, "secret": secret}
        response = session.post(url, json={**auth, **body}, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise PlaidRetryableError(f"Plaid API error (retryable): status={response.status_code}, url={url}")

        if response.status_code == 400 and endpoint in PRODUCT_GATED_ENDPOINTS:
            error_code = _error_code(response)
            if error_code in NO_PRODUCT_DATA_ERROR_CODES:
                raise PlaidNoProductDataError(error_code)
            # Returned while Plaid still extracts the Item's investment history.
            if error_code == "PRODUCT_NOT_READY":
                raise PlaidRetryableError(f"Plaid product not ready yet: url={url}")

        if not response.ok:
            logger.error(f"Plaid API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    def get_item() -> dict[str, Any]:
        return post("/item/get", {}).get("item") or {}

    if endpoint == "accounts":
        data = post("/accounts/get", {})
        items = data.get("accounts", []) or []
        if items:
            yield items
        return

    if endpoint == "institutions":
        institution_id = get_item().get("institution_id")
        if not institution_id:
            return
        data = post(
            "/institutions/get_by_id",
            {"institution_id": institution_id, "country_codes": INSTITUTION_COUNTRY_CODES},
            with_access_token=False,
        )
        if institution := data.get("institution"):
            yield [institution]
        return

    try:
        if product := PRODUCT_GATED_ENDPOINTS.get(endpoint):
            # Calling a product endpoint on an Item without that product adds the product to the Item,
            # and Plaid bills for it, so skip the table instead.
            item = get_item()
            if product not in {*(item.get("billed_products") or []), *(item.get("products") or [])}:
                logger.info(f"Plaid: Item does not have the {product} product, skipping {endpoint}")
                return

        if endpoint == "investment_holdings":
            data = post("/investments/holdings/get", {})
            items = data.get("holdings", []) or []
            if items:
                yield items
            return

        if endpoint == "liabilities":
            data = post("/liabilities/get", {})
            rows = [
                {**liability, "liability_type": liability_type}
                for liability_type, liabilities in (data.get("liabilities") or {}).items()
                for liability in liabilities or []
            ]
            if rows:
                yield rows
            return

        path, rows_key, total_key = OFFSET_PAGINATED_ENDPOINTS[endpoint]
        start_date = (
            _format_date(db_incremental_field_last_value)
            if should_use_incremental_field and db_incremental_field_last_value is not None
            else DEFAULT_START_DATE
        )
        end_date = _today()

        resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
        offset = resume_config.offset if resume_config is not None else 0
        if resume_config is not None:
            logger.debug(f"Plaid: resuming {endpoint} from offset {offset}")

        while True:
            data = post(
                path,
                {
                    "start_date": start_date,
                    "end_date": end_date,
                    "options": {"count": PAGE_SIZE, "offset": offset},
                },
            )
            items = data.get(rows_key, []) or []

            total = data.get(total_key)
            offset += len(items)
            has_more = bool(items) and not (isinstance(total, int) and offset >= total)

            if has_more:
                resumable_source_manager.save_state(PlaidResumeConfig(offset=offset))

            if items:
                yield items

            if not has_more:
                break
    except PlaidNoProductDataError as error:
        logger.info(f"Plaid: Item has no data for {endpoint} ({error}), skipping")


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
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # /transactions/get and /investments/transactions/get return newest-first;
        # the pipeline commits desc watermarks only when a run completes.
        sort_mode="desc" if endpoint in OFFSET_PAGINATED_ENDPOINTS else "asc",
    )
