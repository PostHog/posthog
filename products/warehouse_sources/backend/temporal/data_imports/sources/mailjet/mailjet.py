import base64
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
from products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.settings import (
    MAILJET_ENDPOINTS,
    MailjetEndpointConfig,
)

MAILJET_BASE_URL = "https://api.mailjet.com/v3/REST"


class MailjetRetryableError(Exception):
    pass


@dataclasses.dataclass
class MailjetResumeConfig:
    offset: int = 0
    # The schema this offset belongs to. A single job can sync multiple schemas, so we
    # guard against applying one endpoint's offset to another on resume.
    endpoint: Optional[str] = None


def _get_headers(api_key: str, secret_key: str) -> dict[str, str]:
    token = base64.b64encode(f"{api_key}:{secret_key}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
    }


def _to_unix_ts(value: Any) -> Optional[int]:
    """Convert an incremental field value to a Unix timestamp for Mailjet's FromTS filter."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    if isinstance(value, int | float):
        return int(value)
    return None


def validate_credentials(api_key: str, secret_key: str) -> bool:
    # /contactmetadata is a small read-only resource — 200 confirms the basic-auth
    # credentials are valid, 401 means they're not.
    url = f"{MAILJET_BASE_URL}/contactmetadata"
    try:
        response = make_tracked_session(headers=_get_headers(api_key, secret_key)).get(
            url, params={"Limit": 1}, timeout=10
        )
        return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type((MailjetRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict:
    response = session.get(url, params=params, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise MailjetRetryableError(f"Mailjet API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Mailjet API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _build_base_params(
    config: MailjetEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    """Build the static query params shared across pages (Sort + optional FromTS window)."""
    params: dict[str, Any] = {}
    if config.sort:
        params["Sort"] = config.sort

    if config.from_ts_field and should_use_incremental_field:
        from_ts = _to_unix_ts(db_incremental_field_last_value)
        if from_ts is not None:
            params["FromTS"] = from_ts

    return params


def get_rows(
    api_key: str,
    secret_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MailjetResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = MAILJET_ENDPOINTS[endpoint]

    # One tracked session for the whole sync — keeps urllib3's TLS connection warm
    # across pages, and every request inherits the basic-auth headers.
    session = make_tracked_session(headers=_get_headers(api_key, secret_key))
    url = f"{MAILJET_BASE_URL}/{config.path}"
    limit = config.page_size

    base_params = _build_base_params(config, should_use_incremental_field, db_incremental_field_last_value)

    # Resume only if the saved state belongs to this endpoint.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if (resume is not None and resume.endpoint == endpoint) else 0
    if offset:
        logger.debug(f"Mailjet: resuming {endpoint} from offset={offset}")

    while True:
        params: dict[str, Any] = {**base_params, "Limit": limit, "Offset": offset}
        data = _fetch(session, url, params, logger)

        rows = data.get("Data") or []
        total = data.get("Total")

        if rows:
            # Yield the page as-is and let the pipeline batch it. Persist state only after the
            # yield so a crash re-yields the last page (deduped on the primary key via merge)
            # rather than skipping it.
            yield rows
            offset += len(rows)
            resumable_source_manager.save_state(MailjetResumeConfig(offset=offset, endpoint=endpoint))

        # Terminate on a short/empty page, or once Total is reached (guards the
        # exact-multiple-of-Limit case so we issue at most one extra empty request).
        if not rows or len(rows) < limit:
            break
        if total is not None and offset >= total:
            break


def mailjet_source(
    api_key: str,
    secret_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MailjetResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = MAILJET_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            secret_key=secret_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
