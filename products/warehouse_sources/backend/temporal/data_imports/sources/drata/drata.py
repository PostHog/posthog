import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.drata.settings import (
    DRATA_ENDPOINTS,
    DrataEndpointConfig,
)

# Drata hosts its public API per data-residency region; the user picks their region at connect time.
REGION_BASE_URLS: dict[str, str] = {
    "US": "https://public-api.drata.com/public/v2",
    "EU": "https://public-api.eu.drata.com/public/v2",
    "APAC": "https://public-api.apac.drata.com/public/v2",
}
DEFAULT_REGION = "US"
REQUEST_TIMEOUT_SECONDS = 60
# Cheap list probe used to confirm an API key is genuine. Any authenticated endpoint works; the
# workspaces list is small on every account.
PROBE_PATH = "/workspaces"


class DrataRetryableError(Exception):
    pass


@dataclasses.dataclass
class DrataResumeConfig:
    # Opaque `pagination.cursor` pointing at the page after the last one yielded. A crashed sync
    # resumes from there; merge dedupes the re-pulled page on the primary key.
    cursor: str | None = None
    # For fan-out endpoints: a stable id bookmark of the parent currently being processed (not a
    # positional index, so parents added/removed between a crash and the retry can't resume us into
    # the wrong parent). None for top-level endpoints.
    parent_id: int | None = None


def base_url_for_region(region: str | None) -> str:
    return REGION_BASE_URLS.get((region or DEFAULT_REGION).upper(), REGION_BASE_URLS[DEFAULT_REGION])


def _scrub_url(url: str | None) -> str:
    # Drop the query string before a URL reaches any error message or log line. The API key rides in
    # the Authorization header, but keeping cursors and filters out of persisted job errors is
    # cheap. The scheme/host/path stays intact so `get_non_retryable_errors()` can still match.
    if not url:
        return REGION_BASE_URLS[DEFAULT_REGION]
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _format_incremental_value(value: Any) -> str:
    # Drata's date-time params take ISO 8601; normalize to UTC with a Z suffix to avoid ambiguity.
    if isinstance(value, datetime):
        utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return _format_incremental_value(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def _build_incremental_params(
    config: DrataEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, str]:
    if not should_use_incremental_field or db_incremental_field_last_value is None:
        return {}

    field = incremental_field or config.default_incremental_field
    if field is None:
        return {}

    param = config.incremental_param_by_field.get(field)
    if param is None:
        raise ValueError(f"Drata endpoint '{config.name}' has no server-side filter for field '{field}'")

    return {param: _format_incremental_value(db_incremental_field_last_value)}


@retry(
    retry=retry_if_exception_type((DrataRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(url, params=params or None, timeout=REQUEST_TIMEOUT_SECONDS)

    # Drata rate limits at 500 requests/minute per source IP; 429s and transient 5xx are retried
    # with backoff.
    if response.status_code == 429 or response.status_code >= 500:
        raise DrataRetryableError(
            f"Drata API error (retryable): status={response.status_code}, url={_scrub_url(response.url)}"
        )

    if not response.ok:
        logger.error(
            f"Drata API error: status={response.status_code}, body={response.text}, url={_scrub_url(response.url)}"
        )
        # Raise with the query scrubbed from the URL rather than calling raise_for_status(), whose
        # message embeds the full request URL. The base host stays intact so
        # `get_non_retryable_errors()` can still match on it.
        raise requests.HTTPError(
            f"{response.status_code} Client Error: {response.reason} for url: {_scrub_url(response.url)}",
            response=response,
        )

    data = response.json()
    # Every v2 list endpoint wraps its payload as {"data": [...], "pagination": {"cursor": ...}}.
    if not isinstance(data, dict) or "data" not in data:
        raise DrataRetryableError(f"Drata returned an unexpected payload for {_scrub_url(url)}: {type(data).__name__}")

    return data


def _rows_from_body(body: dict[str, Any], url: str) -> list[dict[str, Any]]:
    data = body["data"]
    if not isinstance(data, list):
        raise DrataRetryableError(f"Drata returned a non-list payload for {_scrub_url(url)}: {type(data).__name__}")
    return data


def _iter_pages(
    session: requests.Session,
    url: str,
    base_params: dict[str, Any],
    page_size: int,
    logger: FilteringBoundLogger,
    start_cursor: str | None = None,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    """Walk a cursor-paginated v2 list endpoint, yielding (rows, next_cursor) per page.

    The API returns `pagination.cursor` only while more pages exist; a missing/empty cursor (or a
    cursor that stops advancing) terminates the walk.
    """
    cursor = start_cursor

    while True:
        params = {**base_params, "size": page_size}
        if cursor:
            params["cursor"] = cursor

        body = _fetch_page(session, url, params, logger)
        items = _rows_from_body(body, url)

        pagination = body.get("pagination") or {}
        next_cursor = pagination.get("cursor")
        if not items or not next_cursor or next_cursor == cursor:
            yield items, None
            return

        yield items, next_cursor
        cursor = next_cursor


def _list_parent_ids(
    session: requests.Session,
    base_url: str,
    parent_config: DrataEndpointConfig,
    logger: FilteringBoundLogger,
) -> list[int]:
    """Page through a fan-out parent endpoint and return every parent id, in creation order."""
    url = f"{base_url}{parent_config.path}"
    params = {"sort": parent_config.sort, "sortDir": "ASC"}
    ids: list[int] = []
    for items, _next_cursor in _iter_pages(session, url, params, parent_config.page_size, logger):
        ids.extend(item["id"] for item in items)
    return ids


def _get_fan_out_rows(
    session: requests.Session,
    base_url: str,
    config: DrataEndpointConfig,
    base_params: dict[str, Any],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DrataResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    assert config.fan_out_parent is not None and config.fan_out_parent_id_column is not None
    parent_config = DRATA_ENDPOINTS[config.fan_out_parent]
    parent_ids = _list_parent_ids(session, base_url, parent_config, logger)

    # Resolve the saved parent-id bookmark to the slice of parents still to process. If the
    # bookmarked parent no longer exists (deleted between runs), start over from the first parent —
    # merge dedupes the re-pulled rows on the primary key. `resume_cursor` seeds the first parent
    # only.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = parent_ids
    resume_cursor: str | None = None
    if resume is not None and resume.parent_id is not None and resume.parent_id in parent_ids:
        remaining = parent_ids[parent_ids.index(resume.parent_id) :]
        resume_cursor = resume.cursor
        logger.debug(f"Drata: resuming {config.name} from parent_id={resume.parent_id}, cursor={resume_cursor}")

    for index, parent_id in enumerate(remaining):
        url = f"{base_url}{config.path.format(parent_id=parent_id)}"
        start_cursor = resume_cursor
        resume_cursor = None

        try:
            for items, next_cursor in _iter_pages(session, url, base_params, config.page_size, logger, start_cursor):
                if items:
                    yield [{**item, config.fan_out_parent_id_column: parent_id} for item in items]
                # Save AFTER yielding so a crash re-fetches the last page rather than skipping it;
                # merge dedupes the re-pulled rows on the primary key.
                if next_cursor:
                    resumable_source_manager.save_state(DrataResumeConfig(cursor=next_cursor, parent_id=parent_id))
        except requests.HTTPError as exc:
            # A parent deleted between enumeration and this fetch 404s. Skip it rather than failing
            # the whole sync — its children are genuinely gone. Any other HTTP error is re-raised.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Drata: {config.fan_out_parent} {parent_id} not found while fetching {config.name}")
            else:
                raise

        # Advance the bookmark to the next parent so a crash between parents resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(DrataResumeConfig(cursor=None, parent_id=remaining[index + 1]))


def _get_top_level_rows(
    session: requests.Session,
    url: str,
    config: DrataEndpointConfig,
    base_params: dict[str, Any],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DrataResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_cursor = resume.cursor if resume else None
    if start_cursor is not None:
        logger.debug(f"Drata: resuming {config.name} from cursor {start_cursor}")

    for items, next_cursor in _iter_pages(session, url, base_params, config.page_size, logger, start_cursor):
        if items:
            yield items
        # Save AFTER yielding so a crash re-fetches the last page rather than skipping it; merge
        # dedupes the re-pulled rows on the primary key.
        if next_cursor:
            resumable_source_manager.save_state(DrataResumeConfig(cursor=next_cursor))


def get_rows(
    api_key: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DrataResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = DRATA_ENDPOINTS[endpoint]
    session = make_tracked_session(
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        redact_values=(api_key,),
    )
    base_url = base_url_for_region(region)
    # An explicit stable creation-order sort keeps cursor pages consistent while rows are inserted
    # mid-sync.
    base_params: dict[str, Any] = {"sort": config.sort, "sortDir": "ASC"}
    base_params.update(
        _build_incremental_params(
            config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
        )
    )

    if config.fan_out_parent:
        yield from _get_fan_out_rows(session, base_url, config, base_params, logger, resumable_source_manager)
        return

    url = f"{base_url}{config.path}"
    yield from _get_top_level_rows(session, url, config, base_params, logger, resumable_source_manager)


def drata_source(
    api_key: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DrataResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = DRATA_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            region=region,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Every request passes sort=createdAt&sortDir=ASC, but the ordering couldn't be verified
        # against a live account, so the incremental endpoint declares "desc": the pipeline then
        # commits the watermark only after a complete sync, which stays correct regardless of the
        # actual arrival order.
        sort_mode="desc" if config.incremental_fields else "asc",
    )


def check_access(api_key: str, region: str, path: str = PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403``/``412`` auth-shaped statuses,
    ``0`` for a connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        redact_values=(api_key,),
    )
    try:
        response = session.get(
            f"{base_url_for_region(region)}{path}", params={"size": 1}, timeout=REQUEST_TIMEOUT_SECONDS
        )
    except Exception as e:
        return 0, f"Could not connect to Drata: {e}"

    if response.status_code in (401, 403, 412):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Drata returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str, region: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key, region)
    if status == 200:
        return True, None
    if status == 401:
        return False, "Invalid Drata API key"
    if status == 403:
        # The key is genuine but lacks the workspaces read scope. Custom-scoped keys may
        # legitimately only grant the endpoints the user wants to sync, so don't block
        # source-create on it; sync-time 403s are surfaced per table.
        return True, None
    if status == 412:
        return False, "You must accept the Drata API terms and conditions in your Drata account before connecting"
    return False, message or "Could not validate Drata API key"
