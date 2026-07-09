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
from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.settings import (
    ELEVENLABS_ENDPOINTS,
    ElevenLabsEndpointConfig,
)

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5


class ElevenLabsRetryableError(Exception):
    pass


@dataclasses.dataclass
class ElevenLabsResumeConfig:
    # Opaque pagination cursor of the next page to fetch. Only the cursor is persisted — the
    # request URL is rebuilt locally from the endpoint catalog, so tampered resume state can't
    # redirect the credential-bearing request to another host.
    cursor: str


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "xi-api-key": api_key,
        "Accept": "application/json",
    }


def _to_epoch(value: Any) -> Optional[int]:
    """Coerce an incremental cursor value to a UNIX timestamp for ElevenLabs' time filters.

    ElevenLabs stores and filters timestamps as epoch seconds, so the persisted watermark is
    already an int in the common case; datetimes are accepted defensively.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_params(config: ElevenLabsEndpointConfig, watermark: Optional[int], cursor: Optional[str]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if config.page_size is not None:
        params["page_size"] = config.page_size
    params.update(config.extra_params)
    if watermark is not None and config.incremental_param is not None:
        params[config.incremental_param] = watermark
    if cursor and config.cursor_param is not None:
        params[config.cursor_param] = cursor
    return params


def _build_url(config: ElevenLabsEndpointConfig, params: dict[str, Any]) -> str:
    if not params:
        return f"{ELEVENLABS_BASE_URL}{config.path}"
    return f"{ELEVENLABS_BASE_URL}{config.path}?{urlencode(params)}"


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is genuine with one cheap probe against /v1/user.

    ElevenLabs keys carry granular endpoint permissions and return 401 both for a fake key
    (detail.status == "invalid_api_key") and for a real key missing the probed endpoint's
    permission (detail.status == "missing_permissions"). A scoped-but-genuine key must pass
    source-create — users may only grant the endpoints they intend to sync — so only an
    invalid/unparseable 401 rejects.
    """
    try:
        response = make_tracked_session().get(
            f"{ELEVENLABS_BASE_URL}/v1/user", headers=_get_headers(api_key), timeout=10
        )
        if response.status_code == 200:
            return True
        if response.status_code == 401:
            try:
                detail = response.json().get("detail", {})
            except ValueError:
                return False
            status_text = detail.get("status") if isinstance(detail, dict) else None
            return status_text == "missing_permissions"
        return False
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type((ElevenLabsRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> Any:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    # ElevenLabs rate limiting is concurrency-based per plan tier; a 429 clears as soon as
    # in-flight requests drain, so exponential backoff is sufficient.
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
    # One session reused across every page so urllib3 keeps the connection alive instead of
    # re-handshaking per request.
    session = make_tracked_session()

    watermark = _to_epoch(db_incremental_field_last_value) if should_use_incremental_field else None
    guard_field = incremental_field or (config.incremental_fields[0]["field"] if config.incremental_fields else None)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor: str | None = resume.cursor if resume is not None else None
    if cursor:
        logger.debug(f"ElevenLabs: resuming {endpoint} from cursor: {cursor}")

    while True:
        url = _build_url(config, _build_params(config, watermark, cursor))
        data = _fetch(session, url, headers, logger)

        items = data if config.data_key is None else (data.get(config.data_key) or [])
        if not items:
            break

        yield items

        if config.data_key is None or config.cursor_param is None:
            # The whole collection arrives in one response (models) — nothing to paginate.
            break

        next_cursor = data.get(config.cursor_response_key)
        if not data.get("has_more") or not next_cursor:
            break

        # Belt-and-braces stop for descending incremental endpoints: the server-side time
        # filter is documented but couldn't be smoke-tested without credentials. If it were
        # silently ignored, cursor pagination would otherwise walk the full history on every
        # incremental sync — so stop once an entire page predates the watermark. (Never applied
        # to ascending endpoints, where old rows arrive first by design.)
        if watermark is not None and config.sort_mode == "desc" and guard_field is not None:
            page_max = max(
                (ts for ts in (_to_epoch(item.get(guard_field)) for item in items) if ts is not None),
                default=None,
            )
            if page_max is not None and page_max < watermark:
                break

        # Save AFTER yielding the page so a crash re-yields the just-finished page rather than
        # skipping it — merge dedupes on the primary key. Resume picks up at the next page.
        cursor = next_cursor
        resumable_source_manager.save_state(ElevenLabsResumeConfig(cursor=next_cursor))


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
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=config.sort_mode,
    )
