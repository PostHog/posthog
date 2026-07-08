import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.settings import (
    CULTURE_AMP_BASE_URL,
    CULTURE_AMP_ENDPOINTS,
    CULTURE_AMP_TOKEN_URL,
)

REQUEST_TIMEOUT_SECONDS = 60
# Rate limits are undisclosed ("generous"); back off on 429/503.
MAX_RETRY_ATTEMPTS = 5


class CultureAmpRetryableError(Exception):
    pass


@dataclasses.dataclass
class CultureAmpResumeConfig:
    # Cursor endpoints: the afterKey of the next unfetched page. Fan-out: the id
    # of the last fully-processed employee, re-located in a freshly-fetched list
    # on resume so an employee added/removed mid-sync can't shift the position.
    cursor: Optional[str] = None
    last_processed_employee_id: Optional[str] = None


def _get_session(client_secret: str) -> requests.Session:
    return make_tracked_session(redact_values=(client_secret,))


def _mint_token(session: requests.Session, client_id: str, client_secret: str, account_id: str, scopes: str) -> str:
    """Exchange client credentials for a bearer JWT (~1h lifetime)."""
    response = session.post(
        CULTURE_AMP_TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": f"target-entity:{account_id}:{scopes}",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _format_timestamp(value: Any) -> str:
    """Format an incremental cursor for the RFC 3339 after_date filter."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


def validate_credentials(client_id: str, client_secret: str, account_id: str) -> bool:
    """Confirm the credentials are valid by minting an employees-read token."""
    try:
        _mint_token(_get_session(client_secret), client_id, client_secret, account_id, "employees-read")
        return True
    except Exception:
        return False


def get_rows(
    client_id: str,
    client_secret: str,
    account_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CultureAmpResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = CULTURE_AMP_ENDPOINTS[endpoint]
    session = _get_session(client_secret)
    token = _mint_token(session, client_id, client_secret, account_id, config.scopes)

    @retry(
        retry=retry_if_exception_type((CultureAmpRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=90),
        reraise=True,
    )
    def fetch(url: str) -> dict[str, Any]:
        nonlocal token
        response = session.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=REQUEST_TIMEOUT_SECONDS)

        # Tokens expire after ~1h; re-mint once if one expires mid-sync.
        if response.status_code == 401:
            token = _mint_token(session, client_id, client_secret, account_id, config.scopes)
            response = session.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code in (429, 503) or response.status_code >= 500:
            raise CultureAmpRetryableError(
                f"Culture Amp API error (retryable): status={response.status_code}, url={url}"
            )

        if not response.ok:
            logger.error(f"Culture Amp API error: status={response.status_code}, body={response.text[:500]}, url={url}")
            response.raise_for_status()

        return response.json()

    def paginate(path: str, params: dict[str, Any], on_page_done: Any = None) -> Iterator[list[dict[str, Any]]]:
        cursor = params.pop("cursor", None)
        while True:
            query = dict(params)
            if cursor:
                query["cursor"] = cursor
            url = f"{CULTURE_AMP_BASE_URL}{path}"
            if query:
                url = f"{url}?{urlencode(query)}"

            body = fetch(url)
            items = body.get("data") or []
            if isinstance(items, dict):
                items = [items]
            items = [row for row in items if isinstance(row, dict)]

            if items:
                yield items

            cursor = (body.get("pagination") or {}).get("afterKey")
            if not cursor:
                return
            if on_page_done is not None:
                on_page_done(cursor)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.per_employee:
        employee_ids: list[str] = []
        for page in paginate("/employees", {}):
            employee_ids.extend(str(row["id"]) for row in page)

        start_index = 0
        if resume_config is not None and resume_config.last_processed_employee_id is not None:
            start_id = resume_config.last_processed_employee_id
            logger.debug(f"Culture Amp: resuming {endpoint} from after employee id {start_id}")
            try:
                start_index = employee_ids.index(start_id) + 1
            except ValueError:
                # The saved employee no longer exists; restart from the beginning
                # (merge dedupes on primary key, so re-yielding is safe).
                start_index = 0

        for index in range(start_index, len(employee_ids)):
            employee_id = employee_ids[index]
            path = config.path.format(employee_id=quote(employee_id, safe=""))
            for page in paginate(path, {}):
                yield [{**row, "_employee_id": employee_id} for row in page]
            # Save state AFTER yielding so a crash re-yields the in-flight
            # employee (merge dedupes on primary key).
            resumable_source_manager.save_state(CultureAmpResumeConfig(last_processed_employee_id=employee_id))
        return

    params: dict[str, Any] = {}
    if config.incremental_fields and should_use_incremental_field and db_incremental_field_last_value is not None:
        params["after_date"] = _format_timestamp(db_incremental_field_last_value)
    if resume_config is not None and resume_config.cursor:
        params["cursor"] = resume_config.cursor
        logger.debug(f"Culture Amp: resuming {endpoint} from saved cursor")

    def save_cursor(after_key: str) -> None:
        # Save state AFTER the previous page yielded so a crash re-yields it.
        resumable_source_manager.save_state(CultureAmpResumeConfig(cursor=after_key))

    yield from paginate(config.path, params, on_page_done=save_cursor)


def culture_amp_source(
    client_id: str,
    client_secret: str,
    account_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CultureAmpResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CULTURE_AMP_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            client_id=client_id,
            client_secret=client_secret,
            account_id=account_id,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=list(config.primary_keys) if config.primary_keys else None,
        partition_count=1,
        partition_size=1,
        # Result ordering within an after_date window is undocumented, so the
        # pipeline defers incremental watermark commits until a run completes.
        sort_mode="desc" if config.incremental_fields else "asc",
    )
