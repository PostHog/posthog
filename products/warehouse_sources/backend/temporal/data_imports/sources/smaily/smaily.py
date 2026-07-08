import re
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.smaily.settings import (
    CAMPAIGN_STATISTICS,
    SEGMENT_SUBSCRIBERS,
    SMAILY_ENDPOINTS,
    SmailyEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
# Fan-out endpoints issue one request per parent; yield + checkpoint every N parents so a resumed
# job re-fetches at most one chunk.
STATS_CHUNK_SIZE = 100
# Cheap endpoint used to confirm credentials are genuine: `list.php` takes no params and every API
# user can read it, so one probe validates access to the account.
DEFAULT_PROBE_PATH = "list.php"
# Smaily represents empty datetimes as a zero date instead of null.
ZERO_DATETIME = "0000-00-00 00:00:00"

_SUBDOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class SmailyRetryableError(Exception):
    pass


@dataclasses.dataclass
class SmailyResumeConfig:
    # Page index within the endpoint (or within the current parent for fan-out endpoints).
    page: int = 0
    # Fan-out endpoints only: parent ids (segments / campaigns) still to fetch, current one first.
    # `None` for top-level endpoints.
    pending_parent_ids: list[str] | None = None


def normalize_subdomain(subdomain: str) -> str:
    """Reduce whatever the user pasted (bare subdomain, full URL, `x.sendsmaily.net`) to the bare
    subdomain, and reject anything that couldn't be one — the subdomain is interpolated into the
    request host, so it must never smuggle in another domain or a path."""
    value = subdomain.strip().lower()
    value = re.sub(r"^https?://", "", value)
    value = value.split("/", 1)[0]
    value = value.removesuffix(".sendsmaily.net")
    if not _SUBDOMAIN_RE.match(value):
        raise ValueError(f"Invalid Smaily subdomain: '{subdomain}'")
    return value


def _base_url(subdomain: str) -> str:
    return f"https://{normalize_subdomain(subdomain)}.sendsmaily.net/api"


def _make_session(username: str, password: str) -> requests.Session:
    session = make_tracked_session(headers={"Accept": "application/json"}, redact_values=(password,))
    session.auth = (username, password)
    return session


@retry(
    retry=retry_if_exception_type((SmailyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> Any:
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    # Smaily rate limits at 5 requests/second per IP and returns 429 when exceeded.
    if response.status_code == 429 or response.status_code >= 500:
        raise SmailyRetryableError(f"Smaily API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Smaily API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    try:
        # Smaily serves JSON with a text/html Content-Type header, so parse unconditionally.
        return response.json()
    except ValueError as e:
        raise SmailyRetryableError(f"Smaily returned a non-JSON payload for {url}") from e


def _as_row_list(data: Any, url: str) -> list[dict[str, Any]]:
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise SmailyRetryableError(f"Smaily returned an unexpected payload for {url}: {type(data).__name__}")
    return data


def _paged_params(config: SmailyEndpointConfig, page: int) -> dict[str, Any]:
    assert config.page_param is not None
    return {**config.extra_params, "limit": config.page_size, config.page_param: page}


def _list_rows(
    session: requests.Session,
    base_url: str,
    config: SmailyEndpointConfig,
    manager: ResumableSourceManager[SmailyResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    url = f"{base_url}/{config.path}"

    if config.page_param is None:
        rows = _as_row_list(_fetch(session, url, dict(config.extra_params), logger), url)
        if rows:
            yield rows
        return

    resume = manager.load_state() if manager.can_resume() else None
    page = resume.page if resume else 0

    while True:
        rows = _as_row_list(_fetch(session, url, _paged_params(config, page), logger), url)
        if rows:
            yield rows

        assert config.page_size is not None
        if len(rows) < config.page_size:
            break

        page += 1
        # Save AFTER yielding so a crash re-fetches the last page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        manager.save_state(SmailyResumeConfig(page=page))


def _fetch_all_pages(
    session: requests.Session,
    base_url: str,
    config: SmailyEndpointConfig,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    url = f"{base_url}/{config.path}"
    rows: list[dict[str, Any]] = []
    page = 0
    while True:
        page_rows = _as_row_list(_fetch(session, url, _paged_params(config, page), logger), url)
        rows.extend(page_rows)
        assert config.page_size is not None
        if len(page_rows) < config.page_size:
            return rows
        page += 1


def _normalize_subscriber(row: dict[str, Any], segment_id: str) -> dict[str, Any]:
    # Zero dates become nulls so the columns can be parsed as timestamps downstream. `segment_id`
    # is injected for the composite primary key (subscriber rows don't carry their segment).
    normalized: dict[str, Any] = {key: (None if value == ZERO_DATETIME else value) for key, value in row.items()}
    normalized["segment_id"] = segment_id
    return normalized


def _segment_subscriber_rows(
    session: requests.Session,
    base_url: str,
    manager: ResumableSourceManager[SmailyResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = SMAILY_ENDPOINTS[SEGMENT_SUBSCRIBERS]
    url = f"{base_url}/{config.path}"

    resume = manager.load_state() if manager.can_resume() else None
    if resume and resume.pending_parent_ids is not None:
        pending = list(resume.pending_parent_ids)
        page = resume.page
    else:
        segments = _as_row_list(
            _fetch(session, f"{base_url}/list.php", {}, logger),
            f"{base_url}/list.php",
        )
        # Sort by id so the resume queue stays deterministic (list.php orders by mutable name).
        pending = sorted(str(segment["id"]) for segment in segments)
        page = 0

    while pending:
        segment_id = pending[0]

        while True:
            params = {"list": segment_id, **_paged_params(config, page)}
            rows = _as_row_list(_fetch(session, url, params, logger), url)
            normalized = [_normalize_subscriber(row, segment_id) for row in rows]
            if normalized:
                yield normalized

            assert config.page_size is not None
            if len(rows) < config.page_size:
                break

            page += 1
            manager.save_state(SmailyResumeConfig(page=page, pending_parent_ids=pending))

        pending = pending[1:]
        page = 0
        manager.save_state(SmailyResumeConfig(page=0, pending_parent_ids=pending))


def _campaign_statistics_rows(
    session: requests.Session,
    base_url: str,
    manager: ResumableSourceManager[SmailyResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = SMAILY_ENDPOINTS[CAMPAIGN_STATISTICS]
    url = f"{base_url}/{config.path}"

    resume = manager.load_state() if manager.can_resume() else None
    if resume and resume.pending_parent_ids is not None:
        pending = list(resume.pending_parent_ids)
    else:
        campaigns = _fetch_all_pages(session, base_url, SMAILY_ENDPOINTS["campaigns"], logger)
        pending = [str(campaign["id"]) for campaign in campaigns]

    batch: list[dict[str, Any]] = []
    while pending:
        campaign_id = pending[0]
        stats = _fetch(session, url, {"id": campaign_id}, logger)
        if isinstance(stats, dict) and stats:
            batch.append(stats)
        else:
            logger.warning(f"Smaily: skipping campaign {campaign_id} statistics, unexpected payload shape")

        pending = pending[1:]
        if batch and (len(batch) >= STATS_CHUNK_SIZE or not pending):
            yield batch
            batch = []
            manager.save_state(SmailyResumeConfig(page=0, pending_parent_ids=pending))


def get_rows(
    subdomain: str,
    username: str,
    password: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SmailyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = SMAILY_ENDPOINTS[endpoint]
    session = _make_session(username, password)
    base_url = _base_url(subdomain)

    if endpoint == SEGMENT_SUBSCRIBERS:
        yield from _segment_subscriber_rows(session, base_url, resumable_source_manager, logger)
    elif endpoint == CAMPAIGN_STATISTICS:
        yield from _campaign_statistics_rows(session, base_url, resumable_source_manager, logger)
    else:
        yield from _list_rows(session, base_url, config, resumable_source_manager, logger)


def smaily_source(
    subdomain: str,
    username: str,
    password: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SmailyResumeConfig],
) -> SourceResponse:
    config = SMAILY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            subdomain=subdomain,
            username=username,
            password=password,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(subdomain: str, username: str, password: str) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the credentials.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem or malformed subdomain, other HTTP status otherwise.
    """
    try:
        base_url = _base_url(subdomain)
    except ValueError as e:
        return 0, str(e)

    session = _make_session(username, password)
    try:
        response = session.get(f"{base_url}/{DEFAULT_PROBE_PATH}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Smaily: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Smaily returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(subdomain: str, username: str, password: str) -> tuple[bool, str | None]:
    status, message = check_access(subdomain, username, password)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Smaily credentials. Check your subdomain, API username and password."
    return False, message or "Could not validate Smaily credentials"
