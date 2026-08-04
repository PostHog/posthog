import re
import dataclasses
from collections.abc import Callable, Iterator
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.fred.settings import (
    FRED_ENDPOINTS,
    FredEndpointConfig,
)

# FRED is a single global deployment with no tenant subdomain and no version segment: the
# `/fred/v2/` family added in late 2025 only covers release-level bulk observations, which
# this source doesn't use.
FRED_BASE_URL = "https://api.stlouisfed.org/fred"
REQUEST_TIMEOUT_SECONDS = 60

# Series ids are pasted by hand, so accept commas, semicolons and newlines as separators.
SERIES_ID_SEPARATOR = re.compile(r"[\s,;]+")
SERIES_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclasses.dataclass
class FredResumeConfig:
    # Position in the source's series list. Always 0 for endpoints that don't fan out.
    series_index: int = 0
    offset: int = 0


class FredApiError(Exception):
    pass


class FredAuthenticationError(FredApiError):
    pass


class FredRequestError(FredApiError):
    """A rejected request that retrying cannot fix — an unknown series id, a bad param."""


def parse_series_ids(raw: str) -> list[str]:
    """Split the source's series-id field into an ordered, de-duplicated list.

    Case is preserved rather than normalized: FRED's own ids are uppercase, but nothing in
    the docs promises the API folds case, and a silent rewrite would make the `series_id`
    column disagree with what the user typed.
    """
    series_ids: dict[str, None] = {}
    for token in SERIES_ID_SEPARATOR.split(raw or ""):
        cleaned = token.strip()
        if cleaned:
            series_ids.setdefault(cleaned, None)
    return list(series_ids)


def _build_url(path: str, params: dict[str, Any]) -> str:
    clean_params = {key: value for key, value in params.items() if value is not None}
    return f"{FRED_BASE_URL}{path}?{urlencode(clean_params)}"


def _error_message(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    if isinstance(body, dict):
        return str(body.get("error_message") or "")
    return ""


def _raise_for_status(response: requests.Response, path: str) -> None:
    if response.ok:
        return

    # FRED carries the api_key in the query string, so the URL never goes into an exception
    # message — `requests.raise_for_status()` would put the whole thing there.
    detail = _error_message(response)

    if response.status_code in (401, 403) or (response.status_code == 400 and "api_key" in detail):
        raise FredAuthenticationError(f"FRED authentication failed: {detail}")

    if response.status_code == 400:
        raise FredRequestError(f"FRED rejected the request (path={path}): {detail}")

    raise FredApiError(f"FRED API error: status={response.status_code}, path={path}, message={detail}")


def _fetch(session: requests.Session, api_key: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
    url = _build_url(path, {**params, "api_key": api_key, "file_type": "json"})
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as error:
        # A connection or timeout failure carries the prepared URL — and therefore the
        # api_key query param — in its own message. The tracked session only redacts its
        # telemetry, so letting this escape unchanged would write the key into job logs and
        # into `latest_error`, where any project member viewing a failed import could read
        # it back. Rebuild the failure from non-sensitive fields only, and suppress the
        # original with `from None` so the chained message can't leak it either. The
        # exception class name keeps the useful part (DNS vs TLS vs read timeout).
        raise FredApiError(f"FRED transport error: {type(error).__name__}, path={path}") from None
    _raise_for_status(response, path)
    body = response.json()
    return body if isinstance(body, dict) else {}


def _extract_rows(
    payload: dict[str, Any], config: FredEndpointConfig, series_id: Optional[str]
) -> list[dict[str, Any]]:
    rows = [row for row in (payload.get(config.data_key) or []) if isinstance(row, dict)]
    if config.stamp_series_id and series_id is not None:
        for row in rows:
            row["series_id"] = series_id
    return rows


def _walk(
    session: requests.Session,
    api_key: str,
    config: FredEndpointConfig,
    extra_params: dict[str, Any],
    start_offset: int,
    series_id: Optional[str],
    on_page_complete: Callable[[int], None],
) -> Iterator[list[dict[str, Any]]]:
    """Yield one batch per response, walking offset pages until FRED returns a short page.

    `on_page_complete(next_offset)` runs after a full page has been yielded so the caller can
    checkpoint. Re-yielding the last page after a crash is harmless: the merge de-duplicates
    on the endpoint's primary key.
    """
    params = {**config.params, **extra_params}

    if not config.paginated:
        rows = _extract_rows(_fetch(session, api_key, config.path, params), config, series_id)
        if rows:
            yield rows
        return

    offset = start_offset
    while True:
        payload = _fetch(session, api_key, config.path, {**params, "limit": config.page_size, "offset": offset})
        page_size = len(payload.get(config.data_key) or [])
        rows = _extract_rows(payload, config, series_id)
        if rows:
            yield rows

        # FRED reports `count`/`offset`/`limit` alongside the rows, but a short page is the
        # one termination signal that holds for every endpoint.
        if page_size < config.page_size:
            break

        offset += config.page_size
        on_page_complete(offset)


def _checkpoint(
    resumable_source_manager: ResumableSourceManager[FredResumeConfig], series_index: int
) -> Callable[[int], None]:
    def save(next_offset: int) -> None:
        resumable_source_manager.save_state(FredResumeConfig(series_index=series_index, offset=next_offset))

    return save


def get_rows(
    api_key: str,
    series_ids: list[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FredResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = FRED_ENDPOINTS[endpoint]
    session = make_tracked_session(redact_values=(api_key,))

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        logger.debug(
            f"FRED: resuming {endpoint} from series_index={resume_config.series_index}, offset={resume_config.offset}"
        )

    if not config.per_series:
        yield from _walk(
            session,
            api_key,
            config,
            {},
            resume_config.offset if resume_config is not None else 0,
            None,
            _checkpoint(resumable_source_manager, 0),
        )
        return

    resume_index = resume_config.series_index if resume_config is not None else 0
    for index, series_id in enumerate(series_ids):
        if index < resume_index:
            continue

        start_offset = resume_config.offset if (resume_config is not None and index == resume_index) else 0

        yield from _walk(
            session,
            api_key,
            config,
            {"series_id": series_id},
            start_offset,
            series_id,
            _checkpoint(resumable_source_manager, index),
        )

        # Checkpoint the next series so a resume doesn't rewalk the one just finished.
        resumable_source_manager.save_state(FredResumeConfig(series_index=index + 1, offset=0))


def validate_credentials(api_key: str, series_id: str) -> tuple[bool, str | None]:
    """Probe `/fred/series` once: it checks the key and the first series id together."""
    session = make_tracked_session(redact_values=(api_key,))
    try:
        _fetch(session, api_key, "/series", {"series_id": series_id})
    except FredAuthenticationError:
        return False, "Invalid FRED API key. Check the key you requested at fred.stlouisfed.org."
    except FredRequestError:
        return False, f"FRED has no series with the ID {series_id}. Check it on fred.stlouisfed.org."
    except Exception:
        return False, "Could not reach the FRED API. Try again in a moment."
    return True, None


def fred_source(
    api_key: str,
    series_ids: list[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FredResumeConfig],
) -> SourceResponse:
    config = FRED_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            series_ids=series_ids,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=list(config.primary_keys),
        # Per-series endpoints emit one series at a time, so the stream restarts at each
        # series' earliest row and is not globally ordered by any column.
        sort_mode=None,
    )
