import dataclasses
from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.baseten.settings import (
    BASETEN_ENDPOINTS,
    BasetenEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

BASETEN_BASE_URL = "https://api.baseten.co"
# Cursor-paginated endpoints (users, model_apis) accept a `limit`; the entity endpoints ignore it.
PAGE_SIZE = 100
REQUEST_TIMEOUT = 60


class BasetenRetryableError(Exception):
    pass


@dataclasses.dataclass
class BasetenResumeConfig:
    # Cursor for the current page of a cursor-paginated endpoint (users, model_apis).
    cursor: str | None = None
    # For fan-out endpoints: the next parent id to process. A stable id (not a positional index) so
    # parents added/removed between a crash and the retry can't resume us into the wrong parent.
    parent_id: str | None = None


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _get_session(api_key: str) -> requests.Session:
    # Redact the key everywhere the tracked transport might surface it (logged URLs, captured
    # samples). The `Authorization` header is already dropped wholesale by the sampler, but masking
    # the literal value is cheap defense-in-depth in case it ever lands in an error body or URL.
    return make_tracked_session(redact_values=(api_key,))


@retry(
    retry=retry_if_exception_type(
        (
            BasetenRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    params: dict[str, Any] | None,
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)

    # 429 responses carry a `retry_after` seconds hint; exponential backoff subsumes it without us
    # having to sleep here. 5xx are transient too.
    if response.status_code == 429 or response.status_code >= 500:
        raise BasetenRetryableError(f"Baseten API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # 404 is expected during fan-out when a parent resource is deleted mid-sync; caller handles it.
        # Log only status + url — upstream error bodies can echo workspace metadata or secret-adjacent
        # data, so we never persist `response.text`.
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Baseten API error: status={response.status_code}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> bool:
    # /v1/users/me is the cheapest workspace-scoped probe and doesn't depend on any resource existing.
    url = f"{BASETEN_BASE_URL}/v1/users/me"
    try:
        response = _get_session(api_key).get(url, headers=_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _flatten_row(item: dict[str, Any], flatten_key: str | None) -> dict[str, Any]:
    """Lift a nested object (e.g. instance_type_prices' `instance_type`) up into the root."""
    if flatten_key and isinstance(item.get(flatten_key), dict):
        nested = item.pop(flatten_key)
        # Root-level siblings (e.g. `price`) take precedence over nested keys on collision.
        return {**nested, **item}
    return item


def _top_level_rows(
    session: requests.Session,
    headers: dict[str, str],
    config: BasetenEndpointConfig,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Single unpaginated request returning a full array under `config.data_key`."""
    data = _fetch(session, f"{BASETEN_BASE_URL}{config.path}", headers, None, logger)
    rows = [_flatten_row(item, config.flatten_key) for item in data.get(config.data_key, [])]
    if rows:
        yield rows


def _paginated_rows(
    session: requests.Session,
    headers: dict[str, str],
    config: BasetenEndpointConfig,
    manager: ResumableSourceManager[BasetenResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Cursor+limit pagination: {"items": [...], "pagination": {"has_more": bool, "cursor": str}}."""
    resume = manager.load_state() if manager.can_resume() else None
    cursor = resume.cursor if resume else None

    url = f"{BASETEN_BASE_URL}{config.path}"
    while True:
        params: dict[str, Any] = {"limit": PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor

        data = _fetch(session, url, headers, params, logger)
        rows = data.get(config.data_key, [])
        if rows:
            yield rows

        pagination = data.get("pagination") or {}
        next_cursor = pagination.get("cursor") if pagination.get("has_more") else None
        if not next_cursor:
            break

        # Save AFTER yielding so a crash re-yields the last page rather than skipping it. These are
        # full-refresh tables (append writes, no primary-key merge), so a resumed run can re-append
        # at most the one in-flight page — bounded, and cleared by the next clean full refresh. We
        # prefer that transient duplicate over the alternative (save-before-yield), which would drop
        # a page entirely on a crash in the same window.
        manager.save_state(BasetenResumeConfig(cursor=next_cursor))
        cursor = next_cursor


def _iter_parents(
    session: requests.Session,
    headers: dict[str, str],
    parent_config: BasetenEndpointConfig,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    """Fetch the (unpaginated) parent list for a fan-out."""
    data = _fetch(session, f"{BASETEN_BASE_URL}{parent_config.path}", headers, None, logger)
    return list(data.get(parent_config.data_key, []))


def _fan_out_rows(
    session: requests.Session,
    headers: dict[str, str],
    config: BasetenEndpointConfig,
    manager: ResumableSourceManager[BasetenResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Iterate a parent resource and fetch this child endpoint once per parent row."""
    assert config.fan_out_parent is not None
    parent_config = BASETEN_ENDPOINTS[config.fan_out_parent]
    parents = _iter_parents(session, headers, parent_config, logger)

    # Drop parents missing the fan-out id. Stringifying a missing id would build a bogus child path
    # (e.g. `/v1/models/None/deployments`) and could sync child rows keyed to a literal "None".
    parented: list[tuple[str, dict[str, Any]]] = []
    for parent in parents:
        raw_id = parent.get(config.fan_out_parent_field)
        if raw_id is None or raw_id == "":
            logger.warning(f"Baseten: skipping {config.fan_out_parent} without {config.fan_out_parent_field}")
            continue
        parented.append((str(raw_id), parent))
    parent_ids = [pid for pid, _ in parented]

    # Resolve the saved parent bookmark to the slice still to process. If the bookmarked parent no
    # longer exists (deleted between runs), start over. These are full-refresh tables, so re-pulling
    # a parent's children can at most re-append them (bounded, cleared by the next clean full refresh).
    resume = manager.load_state() if manager.can_resume() else None
    remaining = parented
    if resume is not None and resume.parent_id is not None and resume.parent_id in parent_ids:
        start = parent_ids.index(resume.parent_id)
        remaining = remaining[start:]
        logger.debug(f"Baseten: resuming {config.name} from parent_id={resume.parent_id}")

    for index, (parent_id, parent) in enumerate(remaining):
        child_path = config.path.replace(f"{{{config.fan_out_path_param}}}", parent_id)
        try:
            data = _fetch(session, f"{BASETEN_BASE_URL}{child_path}", headers, None, logger)
        except requests.HTTPError as exc:
            # A parent deleted between enumeration and this fetch 404s. Skip it rather than failing
            # the whole sync. Any other HTTP error is re-raised.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Baseten: {config.fan_out_parent} {parent_id} not found for {config.name}, skipping")
                continue
            raise

        rows = []
        for item in data.get(config.data_key, []):
            row = _flatten_row(item, config.flatten_key)
            if config.fan_out_include_parent_fields:
                for parent_field, child_column in config.fan_out_include_parent_fields.items():
                    row[child_column] = parent.get(parent_field)
            rows.append(row)

        if rows:
            yield rows

        # Advance the bookmark to the next parent so a crash between parents resumes correctly.
        if index + 1 < len(remaining):
            manager.save_state(BasetenResumeConfig(parent_id=remaining[index + 1][0]))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BasetenResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = BASETEN_ENDPOINTS[endpoint]
    headers = _headers(api_key)
    # One session reused across every page/parent so urllib3 keeps the connection alive.
    session = _get_session(api_key)

    if config.paginated:
        yield from _paginated_rows(session, headers, config, resumable_source_manager, logger)
    elif config.fan_out_parent:
        yield from _fan_out_rows(session, headers, config, resumable_source_manager, logger)
    else:
        yield from _top_level_rows(session, headers, config, logger)


def baseten_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BasetenResumeConfig],
) -> SourceResponse:
    config = BASETEN_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
