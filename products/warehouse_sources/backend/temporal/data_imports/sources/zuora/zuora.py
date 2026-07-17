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
from products.warehouse_sources.backend.temporal.data_imports.sources.zuora.settings import (
    PAGE_SIZE,
    ZUORA_ENDPOINTS,
    ZUORA_ENVIRONMENT_HOSTS,
)

REQUEST_TIMEOUT_SECONDS = 60
# Zuora recommends exponential backoff; limits are generous (50k RPM) but
# concurrency-capped.
MAX_RETRY_ATTEMPTS = 5


class ZuoraRetryableError(Exception):
    pass


@dataclasses.dataclass
class ZuoraResumeConfig:
    # The nextPage cursor of the next unfetched Object Query page.
    cursor: str


def _get_session(client_secret: str) -> requests.Session:
    return make_tracked_session(redact_values=(client_secret,))


def _base_url(environment: str) -> str:
    host = ZUORA_ENVIRONMENT_HOSTS.get(environment)
    if host is None:
        raise ValueError(f"Invalid Zuora environment: {environment}")
    return host


def _mint_token(session: requests.Session, environment: str, client_id: str, client_secret: str) -> str:
    """Exchange client credentials for a bearer token (~1h lifetime)."""
    response = session.post(
        f"{_base_url(environment)}/oauth/token",
        data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _format_timestamp(value: Any) -> str:
    """Format an incremental cursor for the updateddate.GT filter (ISO 8601 UTC)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


def validate_credentials(environment: str, client_id: str, client_secret: str) -> bool:
    """Confirm the OAuth client credentials are valid by minting a token."""
    try:
        _mint_token(_get_session(client_secret), environment, client_id, client_secret)
        return True
    except requests.HTTPError:
        # A rejected token request means the credentials are wrong. Let other
        # failures (network/DNS/timeout) propagate so they aren't misreported
        # to the user as invalid credentials.
        return False


def get_rows(
    environment: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZuoraResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    path_segment = ZUORA_ENDPOINTS[endpoint]
    session = _get_session(client_secret)
    base_url = _base_url(environment)
    token = _mint_token(session, environment, client_id, client_secret)

    @retry(
        retry=retry_if_exception_type((ZuoraRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=90),
        reraise=True,
    )
    def fetch(url: str) -> dict[str, Any]:
        nonlocal token
        response = session.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=REQUEST_TIMEOUT_SECONDS)

        # Tokens last ~1h; re-mint once if one expires mid-sync.
        if response.status_code == 401:
            token = _mint_token(session, environment, client_id, client_secret)
            response = session.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise ZuoraRetryableError(f"Zuora API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Zuora API error: status={response.status_code}, body={response.text[:500]}, url={url}")
            response.raise_for_status()

        return response.json()

    # Filters use lowercase field names (updateddate); rows come back camelCase
    # (updatedDate). Ascending sort lets the pipeline commit the watermark
    # progressively as pages complete.
    params: list[tuple[str, Any]] = [("pageSize", PAGE_SIZE), ("sort[]", "updateddate.ASC")]
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        params.append(("filter[]", f"updateddate.GT:{_format_timestamp(db_incremental_field_last_value)}"))

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume_config.cursor if resume_config is not None else None
    if resume_config is not None:
        logger.debug(f"Zuora: resuming {endpoint} from saved cursor")

    while True:
        # The cursor encodes the full query context (pageSize/sort/filter), so
        # send it alone — repeating the original params risks a 400.
        page_params = [("cursor", cursor)] if cursor else params
        url = f"{base_url}/object-query/{path_segment}?{urlencode(page_params)}"
        body = fetch(url)
        items = body.get("data") or []
        rows = [row for row in items if isinstance(row, dict)]

        if rows:
            yield rows

        cursor = body.get("nextPage") or None
        if not cursor:
            return

        # Save state AFTER yielding so a crash re-yields the in-flight page
        # (merge dedupes on primary key).
        resumable_source_manager.save_state(ZuoraResumeConfig(cursor=cursor))


def zuora_source(
    environment: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZuoraResumeConfig],
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
        # Pages are requested sorted ascending by updateddate.
        sort_mode="asc",
    )
