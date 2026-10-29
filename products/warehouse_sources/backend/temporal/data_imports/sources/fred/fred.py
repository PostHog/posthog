import re
import dataclasses
from collections.abc import Callable, Iterable, Iterator
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.interruptible_wait import (
    interruptible_wait,
)
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
# FRED serves a 429 above 120 requests a minute per key, and the release and category fan-outs
# make hundreds to thousands of requests, so space them out below that limit.
FAN_OUT_REQUEST_INTERVAL_SECONDS = 0.6
ROOT_CATEGORY_ID = 0

# Series ids are pasted by hand, so accept commas, semicolons and newlines as separators.
SERIES_ID_SEPARATOR = re.compile(r"[\s,;]+")
SERIES_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclasses.dataclass(frozen=True)
class FredResumeConfig:
    # Position in the source's series list. Always 0 for endpoints that don't fan out.
    series_index: int = 0
    offset: int = 0
    # Release fan-out: the lowest release id not synced yet.
    next_release_id: Optional[int] = None
    # Release table drill-down: the elements of `next_release_id` not fetched yet.
    pending_element_ids: Optional[list[int]] = None
    # Category tree walk: the categories whose children are not fetched yet, as a DFS stack.
    pending_category_ids: Optional[list[int]] = None


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


def _flatten_elements(elements: Iterable[Any], rows: dict[Any, dict[str, Any]]) -> None:
    """Flatten a release table tree into one row per element.

    FRED lists each element at the top level and again inside its parent's `children`, so an
    element seen twice is kept once.
    """
    for element in elements:
        if not isinstance(element, dict):
            continue
        rows.setdefault(element.get("element_id"), {k: v for k, v in element.items() if k != "children"})
        _flatten_elements(element.get("children") or [], rows)


def _elements_to_drill_into(elements: Iterable[Any], found: list[int]) -> None:
    for element in elements:
        if not isinstance(element, dict):
            continue
        children = element.get("children") or []
        if children:
            _elements_to_drill_into(children, found)
        elif element.get("type") != "series" and isinstance(element.get("element_id"), int):
            found.append(element["element_id"])


def _extract_rows(payload: dict[str, Any], config: FredEndpointConfig, stamp: dict[str, Any]) -> list[dict[str, Any]]:
    entries = payload.get(config.data_key) or []
    rows: list[dict[str, Any]]
    if isinstance(entries, dict):
        elements: dict[Any, dict[str, Any]] = {}
        _flatten_elements(entries.values(), elements)
        rows = list(elements.values())
    elif config.value_key is not None:
        rows = [{config.value_key: entry} for entry in entries if entry is not None]
    else:
        rows = [row for row in entries if isinstance(row, dict)]
    for row in rows:
        row.update(stamp)
    return rows


def _walk(
    session: requests.Session,
    api_key: str,
    config: FredEndpointConfig,
    extra_params: dict[str, Any],
    start_offset: int,
    stamp: dict[str, Any],
    on_page_complete: Callable[[int], None],
) -> Iterator[list[dict[str, Any]]]:
    """Yield one batch per response, walking offset pages until FRED returns a short page.

    `on_page_complete(next_offset)` runs after a full page has been yielded so the caller can
    checkpoint. Re-yielding the last page after a crash is harmless: the merge de-duplicates
    on the endpoint's primary key.
    """
    params = {**config.params, **extra_params}

    if not config.paginated:
        rows = _extract_rows(_fetch(session, api_key, config.path, params), config, stamp)
        if rows:
            yield rows
        return

    offset = start_offset
    while True:
        payload = _fetch(session, api_key, config.path, {**params, "limit": config.page_size, "offset": offset})
        page_size = len(payload.get(config.data_key) or [])
        rows = _extract_rows(payload, config, stamp)
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


def _release_ids(
    session: requests.Session, api_key: str, resumable_source_manager: ResumableSourceManager[FredResumeConfig]
) -> list[int]:
    release_ids: set[int] = set()
    for page in _walk(
        session, api_key, FRED_ENDPOINTS["releases"], {}, 0, {}, lambda _: resumable_source_manager.safe_point()
    ):
        release_ids.update(row["id"] for row in page if isinstance(row.get("id"), int))
    return sorted(release_ids)


def _walk_releases(
    session: requests.Session,
    api_key: str,
    config: FredEndpointConfig,
    resume_config: Optional[FredResumeConfig],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FredResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Fetch the endpoint once per release FRED lists, in release id order."""
    start_release_id = 0
    if resume_config is not None and resume_config.next_release_id is not None:
        start_release_id = resume_config.next_release_id

    for release_id in _release_ids(session, api_key, resumable_source_manager):
        if release_id < start_release_id:
            continue

        # None stands for the release root, which is requested without an element_id.
        pending: list[Optional[int]] = [None]
        if (
            resume_config is not None
            and resume_config.next_release_id == release_id
            and resume_config.pending_element_ids is not None
        ):
            pending = list(resume_config.pending_element_ids)
        requested = {element_id for element_id in pending if element_id is not None}
        emitted: set[Any] = set()

        while pending:
            element_id = pending.pop()
            params: dict[str, Any] = {**config.params, "release_id": release_id}
            if element_id is not None:
                params["element_id"] = element_id

            interruptible_wait(FAN_OUT_REQUEST_INTERVAL_SECONDS, safe_point=resumable_source_manager.safe_point)
            try:
                payload = _fetch(session, api_key, config.path, params)
            except FredRequestError as error:
                # One release FRED rejects (for example one with no table tree) must not fail the
                # whole table. A bad key raises FredAuthenticationError and still fails the sync.
                logger.warning(f"FRED: skipping release {release_id} element {element_id} for {config.name}: {error}")
                payload = {}

            if config.drill_down_elements and isinstance(payload.get(config.data_key), dict):
                found: list[int] = []
                _elements_to_drill_into(payload[config.data_key].values(), found)
                for child_id in reversed(found):
                    if child_id not in requested:
                        requested.add(child_id)
                        pending.append(child_id)

            rows = _extract_rows(payload, config, {"release_id": release_id} if config.stamp_release_id else {})
            if config.drill_down_elements:
                # A drilled element's response can repeat elements an earlier response listed.
                rows = [row for row in rows if row.get("element_id") not in emitted]
                emitted.update(row.get("element_id") for row in rows)

            if pending:
                next_state = FredResumeConfig(
                    next_release_id=release_id,
                    pending_element_ids=[pending_id for pending_id in pending if pending_id is not None],
                )
            else:
                next_state = FredResumeConfig(next_release_id=release_id + 1)
            resumable_source_manager.save_state(next_state)
            if rows:
                yield rows
            else:
                resumable_source_manager.safe_point()


def _walk_category_tree(
    session: requests.Session,
    api_key: str,
    config: FredEndpointConfig,
    resume_config: Optional[FredResumeConfig],
    resumable_source_manager: ResumableSourceManager[FredResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Walk the category tree depth first from the root, one children request per category.

    Depth first keeps the pending stack to the unvisited siblings along one path, so the resume
    state stays small.
    """
    pending = [ROOT_CATEGORY_ID]
    if resume_config is not None and resume_config.pending_category_ids is not None:
        pending = list(resume_config.pending_category_ids)
    # FRED's categories form a tree, but a cycle would otherwise loop forever.
    seen = set(pending)

    while pending:
        category_id = pending.pop()
        payload = _fetch(session, api_key, config.path, {**config.params, "category_id": category_id})
        rows = _extract_rows(payload, config, {})

        children = [row["id"] for row in rows if isinstance(row.get("id"), int) and row["id"] not in seen]
        seen.update(children)
        pending.extend(reversed(children))

        resumable_source_manager.save_state(FredResumeConfig(pending_category_ids=list(pending)))
        if rows:
            yield rows
        else:
            resumable_source_manager.safe_point()

        if pending:
            interruptible_wait(FAN_OUT_REQUEST_INTERVAL_SECONDS, safe_point=resumable_source_manager.safe_point)


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

    if config.category_tree:
        yield from _walk_category_tree(session, api_key, config, resume_config, resumable_source_manager)
        return

    if config.per_release:
        yield from _walk_releases(session, api_key, config, resume_config, logger, resumable_source_manager)
        return

    if not config.per_series:
        yield from _walk(
            session,
            api_key,
            config,
            {},
            resume_config.offset if resume_config is not None else 0,
            {},
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
            {"series_id": series_id} if config.stamp_series_id else {},
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
