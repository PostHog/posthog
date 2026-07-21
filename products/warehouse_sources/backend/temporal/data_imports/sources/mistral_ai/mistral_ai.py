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
from products.warehouse_sources.backend.temporal.data_imports.sources.mistral_ai.settings import (
    MISTRAL_AI_ENDPOINTS,
    MistralAIEndpointConfig,
)

MISTRAL_AI_BASE_URL = "https://api.mistral.ai"

# Offset pagination has no server-signalled end for the bare-array endpoints, so we stop when a page
# comes back empty. This cap is a backstop against an API that ignores `page` and loops forever.
MAX_PAGES = 10_000

REQUEST_TIMEOUT_SECONDS = 60


class MistralAIRetryableError(Exception):
    pass


class MistralAIUnexpectedResponseError(Exception):
    """A 2xx response whose body doesn't match any shape we know how to read rows from.

    Deterministic (a wrong data_key, a schema change, or a wrapped-vs-bare mismatch), so it is not
    retried — we fail the sync loudly rather than treat the un-parseable page as "no more rows" and
    finish a green sync with data silently missing.
    """

    pass


@dataclasses.dataclass
class MistralAIResumeConfig:
    # Next 0-indexed page to fetch. Pages already yielded are persisted to staging before a crash,
    # so resuming mid-endpoint continues from here rather than restarting.
    page: int = 0


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _format_created_after(value: Any) -> str:
    """Format an incremental watermark as the ISO 8601 date-time Mistral's `created_after` expects.

    Mistral returns `created`/`created_at` as Unix timestamps (integer seconds), so the stored
    watermark arrives as an int; convert it to a UTC date-time string.
    """
    # bool is a subclass of int, so guard it before the int/float branch — a stray bool would
    # otherwise be read as a Unix timestamp. Fail loudly rather than emit an invalid param.
    if isinstance(value, bool):
        raise ValueError(f"Boolean value {value} cannot be formatted as a created_after timestamp")
    if isinstance(value, int | float):
        dt = datetime.fromtimestamp(value, tz=UTC)
    elif isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        return str(value)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_base_params(
    config: MistralAIEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    """Query params shared across every page of one endpoint (excludes page/page_size)."""
    params: dict[str, Any] = {}

    if config.order_by is not None:
        order_param, order_value = config.order_by
        params[order_param] = order_value

    if (
        config.supports_incremental
        and should_use_incremental_field
        and db_incremental_field_last_value is not None
        and config.created_after_param is not None
    ):
        params[config.created_after_param] = _format_created_after(db_incremental_field_last_value)

    return params


@retry(
    retry=retry_if_exception_type(
        (
            MistralAIRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, params: dict[str, Any], logger: FilteringBoundLogger) -> Any:
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    # 429 (rate limit) and 5xx are transient — retry. Everything else (esp. 401/403) is terminal and
    # surfaces via raise_for_status so get_non_retryable_errors can permanently fail the sync.
    if response.status_code == 429 or response.status_code >= 500:
        raise MistralAIRetryableError(f"Mistral AI API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Mistral AI API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _extract_rows(config: MistralAIEndpointConfig, data: Any) -> list[dict[str, Any]]:
    """Pull the list of rows out of a response body.

    Most endpoints wrap rows in `{"data": [...]}`; /v1/agents and /v1/conversations return a bare
    JSON array. A bare array is accepted for any endpoint so a wrapped-vs-bare mismatch still syncs
    instead of silently dropping every row. Anything we can't read a list out of raises rather than
    returning `[]`, because `get_rows` treats `[]` as end-of-pagination.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and config.data_key is not None:
        rows = data.get(config.data_key)
        if isinstance(rows, list):
            return rows
    raise MistralAIUnexpectedResponseError(
        f"Mistral AI {config.name}: unexpected response shape (expected a JSON array"
        f"{f' or object with key {config.data_key!r}' if config.data_key is not None else ''}, "
        f"got {type(data).__name__})"
    )


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MistralAIResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = MISTRAL_AI_ENDPOINTS[endpoint]
    # One session reused across every page so urllib3 keeps the connection alive. `redact_values`
    # masks the raw API key if a request is sampled into HTTP telemetry (Bearer auth isn't one of
    # the header names the transport scrubs by default).
    session = make_tracked_session(headers=_get_headers(api_key), redact_values=(api_key,))
    base_params = _build_base_params(config, should_use_incremental_field, db_incremental_field_last_value)
    url = f"{MISTRAL_AI_BASE_URL}{config.path}"

    if not config.paginated:
        rows = _extract_rows(config, _fetch_page(session, url, base_params, logger))
        if rows:
            yield rows
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume is not None else 0
    if resume is not None:
        logger.debug(f"Mistral AI: resuming {endpoint} from page {page}")

    while page < MAX_PAGES:
        params = {**base_params, "page": page, "page_size": config.page_size}
        rows = _extract_rows(config, _fetch_page(session, url, params, logger))
        if not rows:
            break

        yield rows
        page += 1
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it — merge
        # dedupes on the primary key, and full-refresh runs simply re-stage it.
        resumable_source_manager.save_state(MistralAIResumeConfig(page=page))
    else:
        logger.warning(f"Mistral AI: hit page cap ({MAX_PAGES}) for {endpoint}, stopping pagination")


def mistral_ai_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MistralAIResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = MISTRAL_AI_ENDPOINTS[endpoint]

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
        # "asc" where we can guarantee ascending page order (batch jobs force order_by=created);
        # "desc" where we can't (fine-tuning jobs) so the watermark is only persisted at the end of a
        # successful run. Full-refresh endpoints ignore sort_mode.
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
    )


def validate_credentials(api_key: str) -> bool:
    # /v1/models is the cheapest authenticated probe: unpaginated, needs no extra scopes.
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{MISTRAL_AI_BASE_URL}/v1/models",
            headers=_get_headers(api_key),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False
