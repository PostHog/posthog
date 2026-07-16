import dataclasses
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.mailtrap.settings import (
    MAILTRAP_ENDPOINTS,
    MailtrapEndpointConfig,
)

# Management/logs host. Sending hosts (send.api.mailtrap.io, bulk.api.mailtrap.io) are write-only
# and never used by this connector.
MAILTRAP_BASE_URL = "https://mailtrap.io"
REQUEST_TIMEOUT_SECONDS = 60
# Cheap probe to confirm a token is genuine: every token can list the accounts it has access to.
DEFAULT_PROBE_PATH = "/api/accounts"


class MailtrapRetryableError(Exception):
    pass


@dataclasses.dataclass
class MailtrapResumeConfig:
    # Opaque cursor for the next page: `next_page_cursor` for email_logs, the last suppression's
    # UUID for suppressions. A crashed sync resumes from the page after the last one yielded; merge
    # dedupes the re-pulled page on the primary key. `None` means start from the first page.
    cursor: str | None = None


def _headers(api_token: str) -> dict[str, str]:
    return {"Api-Token": api_token, "Accept": "application/json"}


def _format_timestamp(value: Any) -> str:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


@retry(
    retry=retry_if_exception_type((MailtrapRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> Any:
    response = session.get(f"{MAILTRAP_BASE_URL}{path}", params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    # Mailtrap rate limits per token (and per account for suppressions); 429s are retried with
    # backoff alongside transient 5xx.
    if response.status_code == 429 or response.status_code >= 500:
        raise MailtrapRetryableError(f"Mailtrap API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"Mailtrap API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    return response.json()


def _extract_rows(config: MailtrapEndpointConfig, data: Any, path: str) -> list[dict[str, Any]]:
    if config.data_key is not None:
        if not isinstance(data, dict) or not isinstance(data.get(config.data_key), list):
            raise MailtrapRetryableError(f"Mailtrap returned an unexpected payload for {path}: {type(data).__name__}")
        return data[config.data_key]

    if not isinstance(data, list):
        raise MailtrapRetryableError(f"Mailtrap returned an unexpected payload for {path}: {type(data).__name__}")
    return data


def _next_cursor(config: MailtrapEndpointConfig, data: Any, rows: list[dict[str, Any]]) -> Optional[str]:
    if config.cursor_param is None or not rows:
        return None

    if config.cursor_response_key is not None:
        cursor = data.get(config.cursor_response_key) if isinstance(data, dict) else None
        return str(cursor) if cursor else None

    if config.cursor_row_field is not None:
        # No explicit next-page signal: a full page means there may be more rows after the last id.
        if config.page_size is not None and len(rows) < config.page_size:
            return None
        cursor = rows[-1][config.cursor_row_field]
        return str(cursor) if cursor is not None else None

    return None


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MailtrapResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = MAILTRAP_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))

    base_params: dict[str, Any] = {}
    if config.incremental_param and should_use_incremental_field and db_incremental_field_last_value is not None:
        # Server-side lower bound (filters[sent_after] / start_time) is re-sent on every page so
        # cursor pagination never walks past the watermark into already-synced history.
        base_params[config.incremental_param] = _format_timestamp(db_incremental_field_last_value)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.cursor if resume else None
    if cursor is not None:
        logger.debug(f"Mailtrap: resuming {endpoint} from cursor {cursor}")

    while True:
        params = dict(base_params)
        if cursor is not None and config.cursor_param is not None:
            params[config.cursor_param] = cursor

        data = _fetch_page(session, config.path, params, logger)
        rows = _extract_rows(config, data, config.path)
        if rows:
            yield rows

        cursor = _next_cursor(config, data, rows)
        if cursor is None:
            break

        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(MailtrapResumeConfig(cursor=cursor))


def mailtrap_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MailtrapResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = MAILTRAP_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
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
        # email_logs is documented newest-first; suppressions ordering is undocumented. "desc" makes
        # the pipeline commit the incremental watermark only after a sync completes, which is safe
        # in both cases.
        sort_mode="desc" if config.incremental_param else "asc",
    )


def check_access(api_token: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API token.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))
    try:
        response = session.get(f"{MAILTRAP_BASE_URL}{path}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Mailtrap: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Mailtrap returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    status, message = check_access(api_token)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Mailtrap API token"
    return False, message or "Could not validate Mailtrap API token"
