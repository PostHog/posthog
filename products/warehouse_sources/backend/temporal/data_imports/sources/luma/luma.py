import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.luma.settings import (
    EVENTS_PATH,
    LUMA_ENDPOINTS,
    LumaEndpointConfig,
)

LUMA_BASE_URL = "https://public-api.luma.com"
# The docs don't state a hard maximum for `pagination_limit`; 50 keeps pages small while staying
# well inside the 200-500 req/min rate limits.
PAGE_SIZE = 50
REQUEST_TIMEOUT_SECONDS = 60
# Cheap probe used to confirm an API key is genuine. Keys are calendar- or organization-scoped and
# grant access to every read endpoint, so one probe validates the whole source.
DEFAULT_PROBE_PATH = EVENTS_PATH


class LumaRetryableError(Exception):
    pass


@dataclasses.dataclass
class LumaResumeConfig:
    # `next_cursor` from the last fully processed page, passed back as `pagination_cursor`. For the
    # guests fan-out this is the *events list* cursor: state is saved only after every guest of an
    # events page has been yielded, so a resume re-pulls at most one page of parents and merge
    # dedupes the re-pulled rows on the primary key.
    pagination_cursor: str | None = None


def _headers(api_key: str) -> dict[str, str]:
    return {"x-luma-api-key": api_key, "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((LumaRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    cursor: str | None,
    logger: FilteringBoundLogger,
    extra_params: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    params: dict[str, Any] = {"pagination_limit": PAGE_SIZE, **(extra_params or {})}
    # The first request omits the cursor; subsequent requests pass `next_cursor` from the previous page.
    if cursor is not None:
        params["pagination_cursor"] = cursor

    response = session.get(f"{LUMA_BASE_URL}{path}", params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    # Luma returns 429 on rate-limit overage with a one-minute back-off window.
    if response.status_code == 429 or response.status_code >= 500:
        raise LumaRetryableError(f"Luma API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"Luma API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise LumaRetryableError(f"Luma returned an unexpected payload for {path}: {type(data).__name__}")

    next_cursor = data.get("next_cursor")
    # `has_more` is authoritative; a lingering `next_cursor` on the last page must not loop.
    if not data.get("has_more") or not isinstance(next_cursor, str) or not next_cursor:
        next_cursor = None

    return data["entries"], next_cursor


def _flatten_entry(entry: dict[str, Any], nested_key: str | None) -> dict[str, Any]:
    # Some list endpoints wrap the object in an envelope ({"api_id": ..., "event": {...}}); the
    # nested object carries its own `api_id`, so we yield it directly like other connectors do.
    if nested_key is not None:
        nested = entry.get(nested_key)
        if isinstance(nested, dict):
            return nested
    return entry


def _get_event_api_ids(entries: list[dict[str, Any]]) -> list[str]:
    api_ids: list[str] = []
    for entry in entries:
        event = _flatten_entry(entry, "event")
        api_id = event.get("api_id")
        if isinstance(api_id, str) and api_id:
            api_ids.append(api_id)
    return api_ids


def _get_guest_rows_for_event(
    session: requests.Session,
    event_api_id: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = LUMA_ENDPOINTS["guests"]
    cursor: str | None = None
    while True:
        entries, next_cursor = _fetch_page(
            session, config.path, cursor, logger, extra_params={"event_api_id": event_api_id}
        )
        rows = [{**_flatten_entry(entry, config.nested_key), "event_api_id": event_api_id} for entry in entries]
        if rows:
            yield rows
        if not next_cursor or not entries:
            break
        cursor = next_cursor


def _get_fan_out_rows(
    session: requests.Session,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LumaResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    events_cursor = resume.pagination_cursor if resume else None
    if events_cursor is not None:
        logger.debug(f"Luma: resuming guests fan-out from events cursor {events_cursor}")

    while True:
        event_entries, next_events_cursor = _fetch_page(session, EVENTS_PATH, events_cursor, logger)
        event_api_ids = _get_event_api_ids(event_entries)
        skipped = len(event_entries) - len(event_api_ids)
        if skipped:
            logger.warning(
                f"Luma: {skipped} of {len(event_entries)} events had no usable api_id; their guests are skipped"
            )
        for event_api_id in event_api_ids:
            yield from _get_guest_rows_for_event(session, event_api_id, logger)

        if not next_events_cursor or not event_entries:
            break

        events_cursor = next_events_cursor
        # Save AFTER yielding every guest of this events page, so a crash re-pulls at most one page
        # of parents; merge dedupes the re-pulled rows on the primary key.
        resumable_source_manager.save_state(LumaResumeConfig(pagination_cursor=events_cursor))


def _get_top_level_rows(
    session: requests.Session,
    config: LumaEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LumaResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.pagination_cursor if resume else None
    if cursor is not None:
        logger.debug(f"Luma: resuming {config.name} from cursor {cursor}")

    while True:
        entries, next_cursor = _fetch_page(session, config.path, cursor, logger)
        rows = [_flatten_entry(entry, config.nested_key) for entry in entries]
        if rows:
            yield rows

        # `has_more=false` ends the collection; an empty page also terminates defensively so a
        # lingering cursor can never produce an infinite loop.
        if not next_cursor or not entries:
            break

        cursor = next_cursor
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(LumaResumeConfig(pagination_cursor=cursor))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LumaResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = LUMA_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    if config.fan_out_over_events:
        yield from _get_fan_out_rows(session, logger, resumable_source_manager)
    else:
        yield from _get_top_level_rows(session, config, logger, resumable_source_manager)


def luma_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LumaResumeConfig],
) -> SourceResponse:
    config = LUMA_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API key.

    Returns ``(status, message)``: ``200`` reachable, ``400``/``401``/``403`` auth failure, ``0``
    for a connection problem, other HTTP status otherwise. Luma answers 400 when the key header is
    missing/blank and 401 when the key is not recognized.
    """
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(f"{LUMA_BASE_URL}{path}", params={"pagination_limit": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Luma: {e}"

    if response.status_code in (400, 401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Luma returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status in (400, 401, 403):
        return False, "Invalid Luma API key"
    return False, message or "Could not validate Luma API key"
