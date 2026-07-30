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
from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.settings import (
    ELEVENLABS_ENDPOINTS,
    ElevenLabsEndpointConfig,
)

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io"

REQUEST_TIMEOUT_SECONDS = 60


class ElevenLabsRetryableError(Exception):
    """Raised for 429 / 5xx responses so tenacity retries them; credential/4xx errors are not wrapped."""

    pass


@dataclasses.dataclass
class ElevenLabsResumeConfig:
    # Next-page cursor for whichever endpoint this job syncs. Only one endpoint runs per job, so a
    # single opaque cursor slot is enough; each endpoint sends it under its own cursor param.
    cursor: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "xi-api-key": api_key,
        "Accept": "application/json",
    }


def _to_unix_seconds(value: Any) -> int:
    """Coerce an incremental watermark to Unix seconds for the API's `*_after_unix` filters.

    The incremental field is declared as an integer (Unix seconds), so the pipeline normally hands
    back an int; datetime/date are handled defensively in case a stored value was coerced upstream.
    """
    if isinstance(value, datetime):
        # A naive datetime's timestamp() would assume the server's local timezone, so pin it to UTC
        # to keep incremental boundaries identical across environments.
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return int(value.timestamp())
    if isinstance(value, date):
        return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp())
    return int(value)


def _build_params(
    config: ElevenLabsEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Build the constant per-request query params (page size, sort, server-side incremental filter).

    The cursor is added per page by the caller. The incremental filter is applied on every page (the
    API keeps the time-window filter alongside the cursor), so pagination terminates at `has_more`
    rather than re-walking full history each incremental run.
    """
    params: dict[str, Any] = {"page_size": config.page_size}
    params.update(config.extra_params)

    if (
        should_use_incremental_field
        and config.incremental_param
        and db_incremental_field_last_value is not None
        # `incremental_field` is the user's chosen cursor column; each endpoint exposes exactly one, so
        # only apply the server filter when it matches (or the caller didn't pin one).
        and (incremental_field is None or incremental_field == config.incremental_field)
    ):
        params[config.incremental_param] = _to_unix_seconds(db_incremental_field_last_value)

    return params


def validate_credentials(api_key: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    """Probe the API key. 200 => valid. 401 => invalid key. 403 => valid key missing a scope.

    At source-create (`schema_name=None`) a 403 is accepted: users may grant only the scopes for the
    endpoints they want, so a missing scope must not block connecting. When probing a specific schema
    a 403 is a genuine per-table scope error and is surfaced. Sync-time 403s are handled separately by
    `get_non_retryable_errors`.

    Any other status (429, 5xx, or an unexpected code) means the key was never actually verified, so
    validation fails rather than saving an unverified key as valid — the user can retry a transient blip.
    """
    config = ELEVENLABS_ENDPOINTS.get(schema_name) if schema_name else None
    probe_path = config.path if config else "/v1/user"
    url = f"{ELEVENLABS_BASE_URL}{probe_path}"
    params: dict[str, Any] = {"page_size": 1} if config else {}

    try:
        response = make_tracked_session(redact_values=(api_key,), allow_redirects=False).get(
            url, headers=_get_headers(api_key), params=params, timeout=10
        )
    except Exception:
        return False, "Could not reach the ElevenLabs API. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid ElevenLabs API key"
    if response.status_code == 403:
        if schema_name is None:
            return True, None
        return False, f"Your ElevenLabs API key is missing the permission required to sync `{schema_name}`."
    # A 429/5xx/unexpected status leaves the key unverified. Don't accept it — surface it so the user
    # can retry, rather than saving a source that only fails on its first sync.
    return False, f"Could not verify the ElevenLabs API key (status {response.status_code}). Please try again."


@retry(
    retry=retry_if_exception_type(
        (
            ElevenLabsRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> dict:
    response = session.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    # ElevenLabs rate limiting is concurrency-based per plan; a 429 clears once in-flight requests
    # drain, so back off and retry. 5xx are transient server faults.
    if response.status_code == 429 or response.status_code >= 500:
        raise ElevenLabsRetryableError(f"ElevenLabs API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"ElevenLabs API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ElevenLabsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = ELEVENLABS_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across pages so urllib3 keeps the connection alive instead of re-handshaking.
    # Redact the key so it can't leak into captured HTTP samples or logged URLs. Don't follow redirects:
    # requests preserves the custom `xi-api-key` header across a cross-origin 3xx, so a redirect off the
    # fixed API host could replay the key to another origin — fail the request instead.
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
    url = f"{ELEVENLABS_BASE_URL}{config.path}"

    params = _build_params(config, should_use_incremental_field, db_incremental_field_last_value, incremental_field)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.cursor if resume is not None else None
    if cursor:
        logger.debug(f"ElevenLabs: resuming {endpoint} from cursor")

    while True:
        page_params = dict(params)
        if cursor:
            page_params[config.cursor_param] = cursor

        data = _fetch_page(session, url, page_params, headers, logger)

        items = data.get(config.items_key) or []
        if items:
            # Yield the rows in the shape the API returns them; the pipeline batches and merges on the
            # endpoint's primary key.
            yield items

        next_cursor = data.get(config.cursor_response_key)
        has_more = bool(data.get("has_more"))
        if not has_more or not next_cursor:
            break

        # Save state AFTER yielding so a crash re-yields the last page rather than skipping it; merge
        # dedupes the re-pulled rows on the primary key.
        resumable_source_manager.save_state(ElevenLabsResumeConfig(cursor=next_cursor))
        cursor = next_cursor


def elevenlabs_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ElevenLabsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = ELEVENLABS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        sort_mode=config.sort_mode,  # type: ignore[arg-type]
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
    )
