import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from dateutil import parser as date_parser
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.persona.settings import (
    PERSONA_ENDPOINTS,
    PersonaEndpointConfig,
)

PERSONA_BASE_URL = "https://api.withpersona.com/api/v1"

# Persona's default rate limit is 300 req/min; it returns 429 with a reset header on excess.
PAGE_SIZE = 100  # Persona caps page[size] at 100 (default 10).


class PersonaRetryableError(Exception):
    pass


@dataclasses.dataclass
class PersonaResumeConfig:
    # `page[after]` cursor (the id of the last object we durably yielded). On resume we re-window the
    # request with the same created-at filter and continue from this object. `None` starts at page one.
    after: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    # No `Persona-Version` header is sent: omitting it applies the account's dashboard-configured
    # default API version, which is always valid. Pinning a version we can't test risks a 400 if the
    # value predates a field or is rejected. The attributes we read (`created-at`, `id`) are stable
    # across versions.
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    """Build a Persona URL with literal brackets in the query string.

    Persona uses JSON:API-style bracketed params (`page[size]`, `page[after]`,
    `filter[created-at-start]`). Every key and value here is internally constructed from object ids,
    integers, and `Z`-suffixed ISO timestamps — none contain characters that need percent-encoding.
    """
    if not params:
        return base_url
    parts = [f"{key}={value}" for key, value in params.items()]
    return f"{base_url}?{'&'.join(parts)}"


def _format_datetime_z(dt: datetime) -> str:
    """Format a datetime as RFC 3339 with millisecond precision and a Z suffix (Persona's format)."""
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _to_datetime(value: Any) -> Optional[datetime]:
    """Coerce a stored watermark or a record's `created-at` string to an aware UTC datetime.

    Returns None when the value can't be parsed, so callers skip the comparison rather than crash.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    try:
        parsed = date_parser.parse(str(value))
    except (ValueError, OverflowError, TypeError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _clamp_future_to_now(dt: datetime) -> datetime:
    """Cap a future cursor at now. A future `created-at-start` returns nothing anyway; capping keeps
    the request sensible and avoids ever wedging on a future-dated record."""
    now = datetime.now(UTC)
    return now if dt > now else dt


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    """Lift the JSON:API `attributes` object into the row root, keeping `id`/`type` at top level.

    Attribute keys stay in Persona's kebab-case (e.g. `created-at`); the pipeline snake-cases column
    names downstream, so `created-at` lands as the `created_at` warehouse column.
    """
    if "attributes" in item and isinstance(item["attributes"], dict):
        attributes = item.pop("attributes")
        item.update(attributes)
    return item


def validate_credentials(api_key: str) -> int:
    """Probe the cheapest core list endpoint and return the HTTP status (0 on network error).

    Callers map the status: 200 = valid, 401 = bad key, 403 = valid key missing a scope.
    """
    url = _build_url(f"{PERSONA_BASE_URL}/inquiries", {"page[size]": 1})
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
        return response.status_code
    except Exception:
        return 0


@retry(
    retry=retry_if_exception_type(
        (
            PersonaRetryableError,
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
    session: requests.Session, page_url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict:
    response = session.get(page_url, headers=headers, timeout=60)

    # 429 (rate limit) and 5xx are transient — retry with backoff. Persona sends rate-limit reset
    # headers on 429; exponential jitter is a safe fallback that respects the 300 req/min budget.
    if response.status_code == 429 or response.status_code >= 500:
        raise PersonaRetryableError(f"Persona API error (retryable): status={response.status_code}, url={page_url}")

    if not response.ok:
        logger.error(f"Persona API error: status={response.status_code}, body={response.text}, url={page_url}")
        response.raise_for_status()

    return response.json()


def _build_params(config: PersonaEndpointConfig, watermark: Optional[datetime], after: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {"page[size]": PAGE_SIZE}
    if watermark is not None:
        # Server-side incremental window on the immutable created-at timestamp (inclusive start).
        params["filter[created-at-start]"] = _format_datetime_z(watermark)
    if after is not None:
        params["page[after]"] = after
    return params


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PersonaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = PERSONA_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # One session reused across every page so urllib3 keeps the connection alive.
    session = make_tracked_session()

    use_incremental = should_use_incremental_field and config.supports_incremental
    watermark = _to_datetime(db_incremental_field_last_value) if use_incremental else None
    if watermark is not None:
        watermark = _clamp_future_to_now(watermark)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    after = resume.after if resume else None
    if after is not None:
        logger.debug(f"Persona: resuming {endpoint} from page[after]={after}")

    stop = False
    while not stop:
        url = _build_url(f"{PERSONA_BASE_URL}{config.path}", _build_params(config, watermark, after))
        data = _fetch_page(session, url, headers, logger)

        items = data.get("data", [])
        if not items:
            break

        has_next = bool(data.get("links", {}).get("next"))

        for item in items:
            # Client-side watermark guard. Persona filters server-side, but if a future API change
            # were to drop the created-at window past page one, the newest-first ordering lets us stop
            # as soon as we cross below the watermark instead of re-walking full history every sync.
            if watermark is not None:
                created = _to_datetime(item.get("attributes", {}).get("created-at"))
                if created is not None and created < watermark:
                    stop = True
                    break

            batcher.batch(_flatten_item(item))

            while batcher.should_yield():
                py_table = batcher.get_table()
                yield py_table
                # Save AFTER yielding so a crash re-yields the last batch (merge dedupes on the
                # primary key) rather than skipping it. Only checkpoint while more pages remain.
                if has_next:
                    last_id = py_table.column("id")[-1].as_py()
                    resumable_source_manager.save_state(PersonaResumeConfig(after=last_id))

        if stop or not has_next:
            break
        after = items[-1]["id"]

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def persona_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PersonaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = PERSONA_ENDPOINTS[endpoint]

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
        # Persona returns records newest-first; the pipeline defers the watermark advance to end-of-sync
        # for desc sources, and resumption is handled by the saved page[after] cursor.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
