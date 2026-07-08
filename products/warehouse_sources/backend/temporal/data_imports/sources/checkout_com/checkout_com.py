import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CHECKOUT_HOSTS = {
    "production": {"api": "https://api.checkout.com", "auth": "https://access.checkout.com/connect/token"},
    "sandbox": {
        "api": "https://api.sandbox.checkout.com",
        "auth": "https://access.sandbox.checkout.com/connect/token",
    },
}
# Disputes list pages cap at 250.
PAGE_SIZE = 250
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5

# Checkout.com has no list-all-payments endpoint — bulk payment data only
# exists via report files. Disputes are the one honest list surface.
ENDPOINTS = ("disputes",)


class CheckoutComRetryableError(Exception):
    pass


@dataclasses.dataclass
class CheckoutComResumeConfig:
    # Disputes paginate with limit/skip; static params are rebuilt from job
    # inputs on resume.
    skip: int


def _get_session(client_secret: str) -> requests.Session:
    return make_tracked_session(redact_values=(client_secret,))


def _hosts(environment: str) -> dict[str, str]:
    hosts = CHECKOUT_HOSTS.get(environment)
    if hosts is None:
        raise ValueError(f"Invalid Checkout.com environment: {environment}")
    return hosts


@retry(
    retry=retry_if_exception_type((CheckoutComRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _mint_token(session: requests.Session, environment: str, client_id: str, client_secret: str) -> str:
    """Exchange client credentials for a bearer token (~1h lifetime)."""
    response = session.post(
        _hosts(environment)["auth"],
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    # A transient auth-host blip (429/5xx) during an in-flight re-mint must not
    # kill the whole sync — retry it like any other retryable API error.
    if response.status_code == 429 or response.status_code >= 500:
        raise CheckoutComRetryableError(f"Checkout.com auth error (retryable): status={response.status_code}")
    response.raise_for_status()
    return response.json()["access_token"]


def _format_timestamp(value: Any) -> str:
    """Format an incremental cursor for the disputes `from` filter (ISO 8601 UTC)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


def validate_credentials(environment: str, client_id: str, client_secret: str) -> bool:
    """Confirm the API credentials are valid by minting a token."""
    try:
        _mint_token(_get_session(client_secret), environment, client_id, client_secret)
        return True
    except Exception:
        return False


def get_rows(
    environment: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CheckoutComResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    session = _get_session(client_secret)
    api_base = _hosts(environment)["api"]
    token = _mint_token(session, environment, client_id, client_secret)

    @retry(
        retry=retry_if_exception_type((CheckoutComRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch(params: dict[str, Any]) -> dict[str, Any]:
        nonlocal token
        url = f"{api_base}/{endpoint}?{urlencode(params)}"
        response = session.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=REQUEST_TIMEOUT_SECONDS)

        # Tokens last ~1h; re-mint once if the sync outlives one.
        if response.status_code == 401:
            token = _mint_token(session, environment, client_id, client_secret)
            response = session.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise CheckoutComRetryableError(
                f"Checkout.com API error (retryable): status={response.status_code}, url={url}"
            )

        if not response.ok:
            logger.error(f"Checkout.com API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    skip = resume_config.skip if resume_config is not None else 0
    if resume_config is not None:
        logger.debug(f"Checkout.com: resuming {endpoint} from skip {skip}")

    base_params: dict[str, Any] = {"limit": PAGE_SIZE}
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        # `from` filters on a dispute's last_update timestamp.
        base_params["from"] = _format_timestamp(db_incremental_field_last_value)

    while True:
        data = fetch({**base_params, "skip": skip})
        items = data.get("data", []) or []

        if items:
            yield items

        total = data.get("total_count")
        skip += len(items)
        if not items or (isinstance(total, int) and skip >= total):
            break

        # Save state AFTER yielding the page so a crash re-yields the last page
        # (merge dedupes on primary key) rather than skipping it.
        resumable_source_manager.save_state(CheckoutComResumeConfig(skip=skip))


def checkout_com_source(
    environment: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CheckoutComResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            environment=environment,
            client_id=client_id,
            client_secret=client_secret,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=["received_on"],
        # Disputes are returned newest-first; the pipeline commits desc
        # watermarks only when a run completes.
        sort_mode="desc",
    )
