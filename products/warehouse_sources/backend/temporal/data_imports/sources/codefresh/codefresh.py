import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.codefresh.settings import (
    CODEFRESH_ENDPOINTS,
    CodefreshEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# Only the US SaaS host is supported. EU / self-hosted installs use a different host, which we don't
# let the user retarget yet (it would mean sending the stored API key to an arbitrary host).
CODEFRESH_BASE_URL = "https://g.codefresh.io/api"

_DEFAULT_TIMEOUT = 60


class CodefreshRetryableError(Exception):
    pass


@dataclasses.dataclass
class CodefreshResumeConfig:
    # Offset pagination position (projects, pipelines, images, step_types).
    offset: int | None = None
    # Page pagination position (builds) plus the stable pagination session cursor so resumed pages
    # read against the same snapshot the first page opened.
    page: int | None = None
    session_id: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    # Codefresh expects the raw token as the Authorization header value — no "Bearer " prefix.
    return {"Authorization": api_key, "Accept": "application/json"}


def _build_url(path: str, params: Optional[dict[str, Any]] = None) -> str:
    url = f"{CODEFRESH_BASE_URL}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    return url


def _extract_items(data: Any, data_key: Optional[list[str]]) -> list[dict[str, Any]]:
    """Pull the record list out of a response. Codefresh returns either a bare array or an envelope
    (``{docs: [...]}``, ``{workflows: {docs: [...]}}``), so ``data_key`` is the path to walk."""
    if data_key is None:
        return data if isinstance(data, list) else []
    node: Any = data
    for key in data_key:
        if not isinstance(node, dict):
            return []
        node = node.get(key)
    return node if isinstance(node, list) else []


def _flatten(item: dict[str, Any], flatten_key: Optional[str]) -> dict[str, Any]:
    """Lift the fields of a nested object (e.g. a pipeline's ``metadata``) to the row top level so
    the primary key / partition columns resolve against real top-level fields. Top-level fields win
    on a name clash."""
    if flatten_key and isinstance(item.get(flatten_key), dict):
        item = dict(item)
        nested = item.pop(flatten_key)
        return {**nested, **item}
    return item


def _redact_key(row: dict[str, Any], dotted_key: str) -> dict[str, Any]:
    """Return ``row`` with a possibly-nested field removed. ``"variables"`` drops a top-level field;
    ``"spec.variables"`` walks into ``spec`` and drops its ``variables``. Only the nodes on the path
    are copied, so the upstream item is left unmodified; a missing or non-dict node is a no-op."""
    head, _, rest = dotted_key.partition(".")
    if head not in row:
        return row
    if not rest:
        return {k: v for k, v in row.items() if k != head}
    nested = row[head]
    if not isinstance(nested, dict):
        return row
    return {**row, head: _redact_key(nested, rest)}


def _transform_row(item: dict[str, Any], config: CodefreshEndpointConfig) -> dict[str, Any]:
    """Flatten the row, then drop any redacted fields. Redaction runs after flattening so a key that
    only surfaces once a nested object is lifted (and a top-level key of the same name) are both
    caught. Redact keys may be dotted paths (e.g. ``spec.variables``) to reach nested fields."""
    row = _flatten(item, config.flatten_key)
    for key in config.redact_keys:
        row = _redact_key(row, key)
    return row


@retry(
    retry=retry_if_exception_type((CodefreshRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> Any:
    response = session.get(url, headers=headers, timeout=_DEFAULT_TIMEOUT)

    # Codefresh rate-limits per account with a 429; retry those and transient 5xx with backoff.
    if response.status_code == 429 or response.status_code >= 500:
        raise CodefreshRetryableError(f"Codefresh API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Codefresh API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _iter_offset(
    session: requests.Session,
    config: CodefreshEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[CodefreshResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = manager.load_state() if manager.can_resume() else None
    offset = resume.offset if resume is not None and resume.offset is not None else 0

    while True:
        url = _build_url(config.path, {"limit": config.page_size, "offset": offset})
        data = _fetch_page(session, url, headers, logger)
        items = _extract_items(data, config.data_key)
        if not items:
            break

        yield [_transform_row(item, config) for item in items]

        # A short page is the last page. We don't save state on it: there's nothing left to resume to.
        if len(items) < config.page_size:
            break

        offset += config.page_size
        # Save AFTER yielding so a crash re-pulls the page we just emitted rather than skipping it —
        # merge dedupes the re-pulled rows on the primary key.
        manager.save_state(CodefreshResumeConfig(offset=offset))


def _iter_page(
    session: requests.Session,
    config: CodefreshEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[CodefreshResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = manager.load_state() if manager.can_resume() else None
    page = resume.page if resume is not None and resume.page is not None else 1
    session_id = resume.session_id if resume is not None else None

    while True:
        req_headers = dict(headers)
        if session_id:
            # Pin every page to the snapshot the first page opened, so builds created mid-sync can't
            # shift the window underneath us.
            req_headers["X-Pagination-Session-Id"] = session_id

        url = _build_url(config.path, {"limit": config.page_size, "page": page})
        data = _fetch_page(session, url, req_headers, logger)

        items = _extract_items(data, config.data_key)
        pagination = data.get("pagination", {}) if isinstance(data, dict) else {}
        session_id = pagination.get("sessionId") or session_id

        # An empty page terminates the stream even if the API keeps advertising nextPage. Without
        # this, a server-side cursor bug that streams empty pages forever would loop indefinitely.
        if not items:
            break

        yield [_transform_row(item, config) for item in items]

        if not pagination.get("nextPage"):
            break

        page += 1
        manager.save_state(CodefreshResumeConfig(page=page, session_id=session_id))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CodefreshResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = CODEFRESH_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across every page so urllib3 keeps the connection alive.
    session = make_tracked_session()

    if config.pagination == "none":
        data = _fetch_page(session, _build_url(config.path), headers, logger)
        items = [_transform_row(item, config) for item in _extract_items(data, config.data_key)]
        if items:
            yield items
        return

    if config.pagination == "offset":
        yield from _iter_offset(session, config, headers, logger, resumable_source_manager)
        return

    yield from _iter_page(session, config, headers, logger, resumable_source_manager)


def validate_credentials(api_key: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    """Probe the token. Codefresh keys are scoped per resource, so at source-create (``schema_name``
    is ``None``) a 403 means the token is genuine but lacks scope for the probed resource — accept it
    and let the user pick the tables their key can reach. A 401 always means a bad token."""
    config = CODEFRESH_ENDPOINTS.get(schema_name) if schema_name else None
    path = config.path if config is not None else "/projects"

    try:
        response = make_tracked_session().get(_build_url(path, {"limit": 1}), headers=_get_headers(api_key), timeout=10)
    except Exception:
        return False, "Could not connect to Codefresh. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Your Codefresh API key is invalid or has been revoked."
    if response.status_code == 403:
        if schema_name:
            return False, f"Your Codefresh API key is missing the access scope required to sync '{schema_name}'."
        # Valid token, but it lacks scope for the probe resource — don't block source creation.
        return True, None
    if response.status_code == 429 or response.status_code >= 500:
        # Transient: a rate-limit or server error doesn't mean the key is bad. Surface it as a
        # retryable failure rather than telling the user their credentials are invalid.
        return False, "Codefresh is temporarily unavailable. Please try again in a moment."
    return False, f"Codefresh API returned an unexpected status ({response.status_code})."


def codefresh_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CodefreshResumeConfig],
) -> SourceResponse:
    config = CODEFRESH_ENDPOINTS[endpoint]

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
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
