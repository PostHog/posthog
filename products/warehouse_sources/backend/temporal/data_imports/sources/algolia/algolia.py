import re
import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.algolia.settings import (
    ALGOLIA_ENDPOINTS,
    AlgoliaEndpointConfig,
    PaginationStyle,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# Algolia's REST API is served per-application. The main host handles both reads and the
# admin/list operations we use; the `-dsn` replica is only a latency optimisation for search,
# which doesn't matter for a batch import.
ALGOLIA_HOST_TEMPLATE = "https://{application_id}.algolia.net"

# Both 401 and 403 carry this exact message when the application ID / API key pair is wrong.
# A genuine key that merely lacks the ACL for an endpoint returns a different 403 message
# ("Method not allowed with this API key"), which lets us tell "bad credentials" apart from
# "valid credentials, missing scope".
INVALID_CREDENTIALS_MESSAGE = "Invalid Application-ID or API key"

# Algolia application IDs are short alphanumeric tokens. We interpolate the ID into the request
# host, so anything outside this set could break out of the `*.algolia.net` domain and point the
# request (carrying the API key) at an attacker-controlled host — reject it.
_APPLICATION_ID_RE = re.compile(r"^[A-Za-z0-9]+$")


class InvalidApplicationIdError(ValueError):
    pass


@dataclasses.dataclass
class AlgoliaResumeConfig:
    # Browse cursor token to continue an index scan from. None on the first page.
    cursor: str | None = None
    # 0-based page number for the page-paginated endpoints (synonyms, rules, indices).
    page: int | None = None


class AlgoliaRetryableError(Exception):
    pass


def _base_url(application_id: str) -> str:
    if not _APPLICATION_ID_RE.match(application_id):
        raise InvalidApplicationIdError("Algolia Application ID must be alphanumeric (letters and digits only)")
    return ALGOLIA_HOST_TEMPLATE.format(application_id=application_id)


def _get_headers(application_id: str, api_key: str) -> dict[str, str]:
    return {
        "X-Algolia-Application-Id": application_id,
        "X-Algolia-API-Key": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _endpoint_url(application_id: str, config: AlgoliaEndpointConfig, index_name: str | None) -> str:
    path = config.path
    if config.requires_index:
        if not index_name:
            raise ValueError(f"Algolia endpoint '{config.name}' requires an index name")
        path = path.format(index=quote(index_name, safe=""))
    return f"{_base_url(application_id)}{path}"


@retry(
    retry=retry_if_exception_type((AlgoliaRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(
    session: requests.Session,
    method: str,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> dict:
    response = session.request(method, url, headers=headers, params=params, json=body, timeout=60)

    # Algolia rate-limits the API and surfaces transient errors as 429 / 5xx; retry those.
    if response.status_code == 429 or response.status_code >= 500:
        raise AlgoliaRetryableError(f"Algolia API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Algolia API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _iter_cursor(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    config: AlgoliaEndpointConfig,
    logger: FilteringBoundLogger,
    batcher: Batcher,
    manager: ResumableSourceManager[AlgoliaResumeConfig],
    resume: AlgoliaResumeConfig | None,
) -> Iterator[Any]:
    """Page the browse endpoint via its opaque cursor; a missing cursor signals end of index."""
    cursor = resume.cursor if resume else None
    while True:
        body: dict[str, Any] = {"hitsPerPage": config.page_size}
        if cursor:
            body["cursor"] = cursor
        data = _fetch(session, "POST", url, headers, logger, body=body)

        next_cursor = data.get("cursor")
        for item in data.get(config.data_selector, []):
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                # Save after yielding so a crash re-yields the last batch (merge dedupes on
                # the primary key) rather than skipping it.
                if next_cursor:
                    manager.save_state(AlgoliaResumeConfig(cursor=next_cursor))

        if not next_cursor:
            break
        cursor = next_cursor
        manager.save_state(AlgoliaResumeConfig(cursor=cursor))


def _iter_pages(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    config: AlgoliaEndpointConfig,
    logger: FilteringBoundLogger,
    batcher: Batcher,
    manager: ResumableSourceManager[AlgoliaResumeConfig],
    resume: AlgoliaResumeConfig | None,
) -> Iterator[Any]:
    """Page the search (synonyms/rules) and list (indices) endpoints via 0-based page numbers."""
    page = resume.page if resume and resume.page is not None else 0
    while True:
        if config.method == "POST":
            data = _fetch(session, "POST", url, headers, logger, body={"page": page, "hitsPerPage": config.page_size})
        else:
            data = _fetch(session, "GET", url, headers, logger, params={"page": page, "hitsPerPage": config.page_size})

        items = data.get(config.data_selector, [])
        next_page = page + 1
        for item in items:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                manager.save_state(AlgoliaResumeConfig(page=next_page))

        if not items:
            break
        # `indices` reports the page count directly; the search endpoints don't, so fall back to
        # a short final page (fewer rows than requested) to detect the end.
        nb_pages = data.get("nbPages")
        if nb_pages is not None:
            if next_page >= nb_pages:
                break
        elif len(items) < config.page_size:
            break

        page = next_page
        manager.save_state(AlgoliaResumeConfig(page=page))


def get_rows(
    endpoint: str,
    application_id: str,
    api_key: str,
    index_name: str | None,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AlgoliaResumeConfig],
) -> Iterator[Any]:
    config = ALGOLIA_ENDPOINTS[endpoint]
    headers = _get_headers(application_id, api_key)
    url = _endpoint_url(application_id, config, index_name)
    batcher = Batcher(logger=logger, chunk_size=5000, chunk_size_bytes=100 * 1024 * 1024)
    session = make_tracked_session(redact_values=(api_key,))

    resume = manager.load_state() if manager.can_resume() else None

    if config.pagination == PaginationStyle.CURSOR:
        yield from _iter_cursor(session, url, headers, config, logger, batcher, manager, resume)
    else:
        yield from _iter_pages(session, url, headers, config, logger, batcher, manager, resume)

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def validate_credentials(
    application_id: str,
    api_key: str,
    index_name: str | None = None,
    schema_name: str | None = None,
) -> tuple[bool, str | None]:
    """Confirm the application ID / API key pair is genuine.

    Probes the endpoint matching ``schema_name`` (or the configured index browse, falling back to
    listing indices) with a minimal request. A bad credential pair returns a 403 carrying
    ``INVALID_CREDENTIALS_MESSAGE``; a genuine key that simply lacks the ACL for the probed
    endpoint returns a different 403. At source-create (``schema_name is None``) we accept the
    latter — users may only grant scopes for the endpoints they intend to sync — but reject it for
    a specific schema check.
    """
    config = ALGOLIA_ENDPOINTS.get(schema_name) if schema_name else None
    if config is None:
        config = ALGOLIA_ENDPOINTS["records"] if index_name else ALGOLIA_ENDPOINTS["indices"]

    # An index-scoped probe with no index name configured falls back to listing indices.
    if config.requires_index and not index_name:
        config = ALGOLIA_ENDPOINTS["indices"]

    headers = _get_headers(application_id, api_key)
    try:
        url = _endpoint_url(application_id, config, index_name)
    except InvalidApplicationIdError as exc:
        return False, str(exc)

    session = make_tracked_session(redact_values=(api_key,))
    try:
        if config.method == "POST":
            response = session.post(url, headers=headers, json={"hitsPerPage": 0}, timeout=10)
        else:
            response = session.get(url, headers=headers, timeout=10)
    except requests.RequestException as exc:
        return False, f"Could not reach Algolia: {exc}"

    if response.ok:
        return True, None

    if response.status_code in (401, 403):
        message = ""
        try:
            message = response.json().get("message", "")
        except ValueError:
            pass

        if INVALID_CREDENTIALS_MESSAGE in message:
            return False, "Invalid Algolia Application ID or API key"

        # Genuine credentials, but the key lacks the ACL for the probed endpoint.
        if schema_name is None:
            return True, None
        return False, f"Your Algolia API key is missing the ACL required to sync '{schema_name}'"

    return False, f"Algolia API returned status {response.status_code}"


def algolia_source(
    endpoint: str,
    application_id: str,
    api_key: str,
    index_name: str | None,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AlgoliaResumeConfig],
) -> SourceResponse:
    config = ALGOLIA_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            endpoint=endpoint,
            application_id=application_id,
            api_key=api_key,
            index_name=index_name,
            logger=logger,
            manager=manager,
        ),
        primary_keys=config.primary_keys,
        # Full-refresh endpoints with no stable datetime field to partition on.
        partition_count=1,
        partition_size=1,
    )
