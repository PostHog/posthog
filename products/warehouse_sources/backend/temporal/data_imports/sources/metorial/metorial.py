import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SortMode, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.metorial.settings import (
    METORIAL_ENDPOINTS,
    MetorialEndpointConfig,
)

METORIAL_BASE_URL = "https://api.metorial.com"
# Pin the API version so response shapes don't shift under us when Metorial changes an environment's
# default version. See https://metorial.com/api ("Versioning").
METORIAL_API_VERSION = "2025-01-01"
# Default page size. Metorial doesn't document a max, so stay conservatively within a value cursor
# APIs commonly accept while keeping request counts down against the tight per-key rate limit.
DEFAULT_PAGE_SIZE = 100


class MetorialRetryableError(Exception):
    pass


@dataclasses.dataclass
class MetorialResumeConfig:
    # Cursor (a record id) to fetch the next page from. None means "start at the first page".
    after: str | None = None


def _format_datetime_z(dt: datetime) -> str:
    """Format a datetime as ISO 8601 with a millisecond precision and a Z suffix (Metorial's format)."""
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _format_incremental_value(value: Any) -> str:
    if isinstance(value, datetime):
        return _format_datetime_z(value)
    if isinstance(value, date):
        return _format_datetime_z(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Metorial-Version": METORIAL_API_VERSION,
        "Accept": "application/json",
    }


def _build_params(
    config: MetorialEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Build the base query params reused on every page of a list request.

    `order=asc` paginates deterministically by record id. The incremental filter is re-sent on every
    page so pagination can never walk back past the watermark. Note this orders by id, not by the
    incremental field: `created_at` tracks id order (safe to checkpoint per batch), but `updated_at`
    does not, so `updated_at` syncs run in `sort_mode="desc"` (see `metorial_source`).
    """
    params: dict[str, Any] = {"limit": DEFAULT_PAGE_SIZE, "order": "asc"}

    if config.incremental_fields and should_use_incremental_field and db_incremental_field_last_value:
        field_name = incremental_field or config.default_incremental_field
        # Metorial documents these as `created_at`/`updated_at` objects with `.gt`/`.lt` operators.
        # Bracket notation is the standard query-string encoding for such nested filter objects on a
        # JSON/Node backend; confirm against the live API before relying on it in anger.
        params[f"{field_name}[gt]"] = _format_incremental_value(db_incremental_field_last_value)

    return params


def validate_credentials(api_key: str) -> bool:
    # A single cheap probe: list one session. 200 => the secret key is genuine and project-scoped.
    try:
        response = make_tracked_session().get(
            f"{METORIAL_BASE_URL}/sessions",
            params={"limit": 1},
            headers=_get_headers(api_key),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type(
        (
            MetorialRetryableError,
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
    path: str,
    params: dict[str, Any],
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> dict:
    response = session.get(f"{METORIAL_BASE_URL}{path}", params=params, headers=headers, timeout=60)

    # 429 (rate limited) and 5xx are transient; back off and retry rather than failing the sync.
    if response.status_code == 429 or response.status_code >= 500:
        raise MetorialRetryableError(f"Metorial API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"Metorial API error: status={response.status_code}, path={path}")
        # raise_for_status() would embed the full request URL (including the query string, which
        # carries the incremental watermark and cursor) in the exception, and response.text can echo
        # synced session content, tool-call payloads, or secret values. Both are surfaced as the
        # schema's latest_error outside the warehouse table ACLs. Rebuild the error from
        # scheme/host/path only so no response body or query string can leak into stored error state.
        # The "<status> Client Error: <reason> for url: https://api.metorial.com" prefix stays stable
        # for get_non_retryable_errors() matching.
        safe = urlsplit(response.url)
        raise requests.HTTPError(
            f"{response.status_code} Client Error: {response.reason} for url: {safe.scheme}://{safe.netloc}{safe.path}",
            response=response,
        )

    return response.json()


def _normalize(item: dict[str, Any], drop_fields: list[str]) -> dict[str, Any]:
    if not drop_fields:
        return item
    return {key: value for key, value in item.items() if key not in drop_fields}


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MetorialResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = METORIAL_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across every page so urllib3 keeps the connection alive.
    session = make_tracked_session()

    params = _build_params(config, should_use_incremental_field, db_incremental_field_last_value, incremental_field)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    after: str | None = resume.after if resume else None
    if after:
        logger.debug(f"Metorial: resuming {endpoint} from cursor {after}")

    while True:
        page_params = dict(params)
        if after:
            page_params["after"] = after

        data = _fetch_page(session, config.path, page_params, headers, logger)

        raw_items = data.get("items", [])
        if raw_items:
            yield [_normalize(item, config.drop_fields) for item in raw_items]

        pagination = data.get("pagination", {})
        if not raw_items or not pagination.get("has_more_after", False):
            break

        after = raw_items[-1]["id"]
        # Save AFTER yielding the page so a crash re-fetches the last page (merge dedupes on the
        # primary key) rather than skipping it.
        resumable_source_manager.save_state(MetorialResumeConfig(after=after))


def metorial_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MetorialResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = METORIAL_ENDPOINTS[endpoint]

    # Pagination is `order=asc` by record id. Metorial ids are time-sorted, so a `created_at` sync
    # genuinely arrives oldest-first and the pipeline can safely checkpoint the watermark after each
    # batch. `updated_at` is NOT monotonic in id order (a row created long ago can be updated
    # recently), so those syncs run `desc`: the pipeline then commits the watermark only after a full
    # successful run, so an interrupted sync can't advance past rows it hasn't fetched yet.
    chosen_field = incremental_field or config.default_incremental_field
    sort_mode: SortMode = "asc" if chosen_field in (None, "created_at") else "desc"

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
        sort_mode=sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="week",
        partition_keys=[config.partition_key],
    )
