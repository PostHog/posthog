import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode, urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.northpass_lms.settings import (
    NORTHPASS_ENDPOINTS,
    NorthpassEndpointConfig,
)

NORTHPASS_BASE_URL = "https://api.northpass.com/v2"
# Northpass serves every account from this single shared host (no per-account subdomains).
NORTHPASS_HOST = "api.northpass.com"
# Northpass doesn't publish its max page size; 100 is a conventional cap that keeps payloads small.
PAGE_SIZE = 100


def _is_northpass_url(url: str) -> bool:
    """Pin a URL to Northpass's HTTPS host.

    Pagination follows `links.next` from the response body, which is attacker-controlled if the
    upstream is compromised or spoofed. Since that URL is fetched with the API key attached, a
    hostile `next` pointing off-host would leak the credential. Northpass only ever serves from a
    single fixed host, so anything else is rejected before we fetch it.
    """
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.netloc == NORTHPASS_HOST


class NorthpassRetryableError(Exception):
    pass


@dataclasses.dataclass
class NorthpassResumeConfig:
    # Full URL of the next page to fetch (JSON:API `links.next`). None means "start from the first
    # page". For fan-out endpoints it's the next page within the current parent resource.
    next_url: str | None = None
    # Fan-out only: the parent resource id currently being processed. A stable id bookmark (not a
    # positional index) so parents added/removed between a crash and retry can't resume us into the
    # wrong parent. None for top-level endpoints.
    parent_id: str | None = None


def _headers(api_key: str) -> dict[str, str]:
    return {"X-Api-Key": api_key, "Accept": "application/json"}


def _build_url(path: str, params: dict[str, Any]) -> str:
    base = f"{NORTHPASS_BASE_URL}{path}"
    return f"{base}?{urlencode(params)}" if params else base


@retry(
    retry=retry_if_exception_type(
        (
            NorthpassRetryableError,
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
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=60)

    # Northpass references rate limits but doesn't publicly quantify them; back off on 429 and
    # transient 5xx rather than failing the sync.
    if response.status_code == 429 or response.status_code >= 500:
        raise NorthpassRetryableError(f"Northpass API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # A parent resource deleted mid fan-out 404s; the caller decides whether to skip or raise.
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Northpass API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _flatten_item(item: dict[str, Any], extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Promote a JSON:API resource's `attributes` to the root, keeping `id`/`type`/`relationships`.

    The per-item `links` block is dropped (it's only self/action hyperlinks). `extra` injects
    fan-out parent identifiers so child rows always carry their parent id even when the API omits
    it from `attributes`.
    """
    row = dict(item)
    attributes = row.pop("attributes", None)
    row.pop("links", None)
    if isinstance(attributes, dict):
        row.update(attributes)
    if extra:
        row.update(extra)
    return row


def _iter_pages(
    session: requests.Session,
    start_url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    """Yield `(items, next_url)` for each JSON:API page, following `links.next`."""
    url = start_url
    while True:
        # Refuse to send the credentialed request anywhere but Northpass's host — the first URL is
        # built by us, but every subsequent one comes from the (untrusted) response body.
        if not _is_northpass_url(url):
            logger.warning(f"Northpass: refusing to fetch off-host pagination URL: {url}")
            return
        data = _fetch_page(session, url, headers, logger)
        items = data.get("data", [])
        next_url = data.get("links", {}).get("next")
        yield items, next_url
        if not next_url:
            return
        url = next_url


def _iter_parent_ids(
    session: requests.Session, parent_path: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[str]:
    """Page through a parent collection and yield each resource id (for fan-out endpoints)."""
    for items, _ in _iter_pages(session, _build_url(parent_path, {"limit": PAGE_SIZE}), headers, logger):
        for item in items:
            yield item["id"]


def _get_top_level_rows(
    session: requests.Session,
    config: NorthpassEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NorthpassResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    resume_url = resume.next_url if resume is not None else None
    start_url = resume_url or _build_url(config.path, {"limit": PAGE_SIZE})
    if resume_url:
        logger.debug(f"Northpass: resuming {config.name} from {start_url}")

    for items, next_url in _iter_pages(session, start_url, headers, logger):
        if items:
            yield [_flatten_item(item) for item in items]
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it — merge
        # dedupes on the primary key.
        if next_url:
            resumable_source_manager.save_state(NorthpassResumeConfig(next_url=next_url))


def _get_fan_out_rows(
    session: requests.Session,
    config: NorthpassEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NorthpassResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    # Guard (and narrow the Optional fan-out fields to str) so `parent_id_field` can be used as a
    # dict key below. A `raise` rather than `assert` so it survives `python -O`.
    if config.fan_out_parent is None or config.parent_id_field is None:
        raise ValueError(f"_get_fan_out_rows called with non-fan-out config: {config.name}")
    parent_config = NORTHPASS_ENDPOINTS[config.fan_out_parent]

    parent_ids = list(_iter_parent_ids(session, parent_config.path, headers, logger))

    # Resolve the saved parent bookmark to the slice of parents still to process. If the bookmarked
    # parent no longer exists (deleted between runs), start over — merge dedupes re-pulled rows.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = parent_ids
    resume_url: str | None = None
    if resume is not None and resume.parent_id is not None and resume.parent_id in parent_ids:
        remaining = parent_ids[parent_ids.index(resume.parent_id) :]
        resume_url = resume.next_url
        logger.debug(f"Northpass: resuming {config.name} from parent={resume.parent_id}, url={resume_url}")

    for index, parent_id in enumerate(remaining):
        start_url = resume_url or _build_url(config.path.replace("{parent_id}", parent_id), {"limit": PAGE_SIZE})
        resume_url = None  # only the resumed-into parent uses the saved URL; the rest start fresh

        try:
            for items, next_url in _iter_pages(session, start_url, headers, logger):
                if items:
                    yield [_flatten_item(item, extra={config.parent_id_field: parent_id}) for item in items]
                if next_url:
                    resumable_source_manager.save_state(NorthpassResumeConfig(next_url=next_url, parent_id=parent_id))
        except requests.HTTPError as exc:
            # A parent deleted between enumeration and this fetch 404s. Skip it rather than failing
            # the whole sync — the enrollments are genuinely gone. Any other HTTP error re-raises.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Northpass: {config.fan_out_parent} {parent_id} not found, skipping")
            else:
                raise

        # Advance the bookmark to the next parent so a crash between parents resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(NorthpassResumeConfig(next_url=None, parent_id=remaining[index + 1]))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NorthpassResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = NORTHPASS_ENDPOINTS[endpoint]
    headers = _headers(api_key)
    # One session reused across every page (and, for fan-out, every parent) so urllib3 keeps the
    # connection alive instead of re-handshaking per request. `redact_values` scrubs the API key
    # from logged URLs and captured HTTP samples; `allow_redirects=False` stops a 30x from
    # forwarding the credentialed X-Api-Key header off-host.
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)

    if config.fan_out_parent is not None:
        yield from _get_fan_out_rows(session, config, headers, logger, resumable_source_manager)
    else:
        yield from _get_top_level_rows(session, config, headers, logger, resumable_source_manager)


def northpass_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NorthpassResumeConfig],
) -> SourceResponse:
    config = NORTHPASS_ENDPOINTS[endpoint]

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


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Probe a cheap list endpoint to confirm the API key is genuine.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error.
    """
    url = _build_url("/courses", {"limit": 1})
    try:
        session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
        response = session.get(url, headers=_headers(api_key), timeout=10)
    except Exception:
        return False, None
    return response.status_code == 200, response.status_code
