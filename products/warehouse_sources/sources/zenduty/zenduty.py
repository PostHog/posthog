import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode, urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    make_tracked_session,
    retry_with_deadline,
)
from products.warehouse_sources.sources.zenduty.settings import (
    FAN_OUT_PARENTS,
    ZENDUTY_ENDPOINTS,
    ZendutyEndpointConfig,
    ZendutyFanOutParent,
)

ZENDUTY_BASE_URL = "https://www.zenduty.com"
REQUEST_TIMEOUT_SECONDS = 60


class ZendutyRetryableError(Exception):
    pass


@dataclasses.dataclass(frozen=False)
class ZendutyResumeConfig:
    # The next page URL (DRF returns absolute `next` URLs that already carry the page cursor).
    next_url: str | None = None
    # For fan-out endpoints: the parent list page that holds the parent in progress, and that parent
    # (the field named by the parent's `path_param`). A resume starts at that page, skips the parents
    # before it, and picks it back up at `next_url`. No parent id means the start of the page.
    parent_page_url: str | None = None
    team_id: str | None = None
    incident_number: int | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Token {api_key}",
        "Accept": "application/json",
    }


def _initial_url(path: str, page_size: int) -> str:
    # `page_size` only steers the first request; DRF may cap or ignore it, after which we simply
    # follow the server's `next` links.
    return f"{ZENDUTY_BASE_URL}{path}?{urlencode({'page_size': page_size})}"


def _ensure_zenduty_url(url: str) -> str:
    """Require an HTTPS www.zenduty.com URL. Every request carries the account API key, so a
    pagination `next` URL (or a poisoned resume checkpoint) pointing anywhere else would leak the
    key and let the worker be steered at arbitrary/internal hosts."""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != "www.zenduty.com":
        raise ValueError(f"Refusing non-Zenduty pagination URL: {url}")
    return url


def _extract_items_and_next(data: Any) -> tuple[list[dict[str, Any]], str | None]:
    """Normalize a Zenduty list response into (rows, next_url).

    Zenduty is Django REST framework, so collections come back either as a page-number envelope
    (`{"count", "next", "previous", "results"}`) or, for smaller team-nested collections, as a bare
    JSON array. Handle both, plus a lone object, so a per-endpoint pagination difference can't drop rows.
    """
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)], None
    if isinstance(data, dict):
        if "results" in data:
            results = data.get("results") or []
            rows = [row for row in results if isinstance(row, dict)] if isinstance(results, list) else []
            next_url = data.get("next")
            return rows, next_url if isinstance(next_url, str) else None
        # A single resource object (not expected for list routes, but keep it lossless).
        return [data], None
    return [], None


@retry_with_deadline(
    retry=retry_if_exception_type((ZendutyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> Any:
    # Redirects are refused: following one off the validated origin would re-send the API key
    # to wherever the response points.
    response = session.get(
        _ensure_zenduty_url(url), headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False
    )

    if 300 <= response.status_code < 400:
        raise ValueError(
            f"Zenduty returned an unexpected redirect: status={response.status_code}, "
            f"location={response.headers.get('Location')}, url={url}"
        )

    # 429 (rate limited) and 5xx are transient; retry them.
    if response.status_code == 429 or response.status_code >= 500:
        raise ZendutyRetryableError(f"Zenduty API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Zenduty API error: status={response.status_code}, body={response.text[:500]}, url={url}")
        response.raise_for_status()

    try:
        return response.json()
    except ValueError:
        # A 2xx that isn't JSON (e.g. a WAF interstitial). Treat as transient rather than crashing
        # the sync on a body we can't parse.
        raise ZendutyRetryableError(f"Zenduty returned a non-JSON body: status={response.status_code}, url={url}")


def _parent_ids(rows: list[dict[str, Any]], parent: ZendutyFanOutParent) -> list[str | int]:
    parent_ids: list[str | int] = []
    for row in rows:
        parent_id = row.get(parent.id_field)
        # Team ids are UUID strings, incident numbers are integers. Keep the type so the injected
        # column joins to the parent table.
        if (isinstance(parent_id, str) and parent_id) or (
            isinstance(parent_id, int) and not isinstance(parent_id, bool)
        ):
            parent_ids.append(parent_id)
    return parent_ids


def _paginate_top_level(
    session: requests.Session,
    headers: dict[str, str],
    config: ZendutyEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZendutyResumeConfig],
    resume: ZendutyResumeConfig | None,
    page_size: int,
) -> Iterator[list[dict[str, Any]]]:
    url = resume.next_url if (resume and resume.next_url) else _initial_url(config.path, page_size)
    while True:
        data = _fetch_page(session, url, headers, logger)
        rows, next_url = _extract_items_and_next(data)
        if rows:
            yield rows
        if not next_url:
            break
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it — merge
        # dedupes on the primary key. Advance the URL before the next fetch to avoid re-looping it.
        # Validate before saving so an off-origin URL never lands in the resume checkpoint.
        resumable_source_manager.save_state(ZendutyResumeConfig(next_url=_ensure_zenduty_url(next_url)))
        resumable_source_manager.safe_point()
        url = next_url


def _paginate_fan_out(
    session: requests.Session,
    headers: dict[str, str],
    config: ZendutyEndpointConfig,
    parent: ZendutyFanOutParent,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZendutyResumeConfig],
    resume: ZendutyResumeConfig | None,
    page_size: int,
) -> Iterator[list[dict[str, Any]]]:
    # Parent pages are streamed, not listed up front, so a resume of a large incident history
    # starts at the saved parent page instead of reading every parent page again.
    resume_parent_id = getattr(resume, parent.path_param) if resume else None
    page_url: str | None = _initial_url(ZENDUTY_ENDPOINTS[parent.endpoint].path, page_size)
    if resume and resume.parent_page_url:
        page_url = resume.parent_page_url
    else:
        resume_parent_id = None

    def _state(page: str, parent_id: Any, next_url: str | None) -> ZendutyResumeConfig:
        return ZendutyResumeConfig(parent_page_url=page, next_url=next_url, **{parent.path_param: parent_id})

    while page_url:
        data = _fetch_page(session, page_url, headers, logger)
        parent_rows, next_page = _extract_items_and_next(data)
        next_page_url = _ensure_zenduty_url(next_page) if next_page else None
        parent_ids = _parent_ids(parent_rows, parent)
        resumable_source_manager.safe_point()

        start_index = 0
        child_url: str | None = None
        if resume_parent_id is not None and resume_parent_id in parent_ids:
            start_index = parent_ids.index(resume_parent_id)
            child_url = resume.next_url if resume else None
        resume_parent_id = None

        for idx in range(start_index, len(parent_ids)):
            parent_id = parent_ids[idx]
            url: str | None = child_url or _initial_url(config.path.format(**{parent.path_param: parent_id}), page_size)
            child_url = None
            while url:
                data = _fetch_page(session, url, headers, logger)
                rows, next_url = _extract_items_and_next(data)
                if next_url:
                    state: ZendutyResumeConfig | None = _state(page_url, parent_id, _ensure_zenduty_url(next_url))
                elif idx + 1 < len(parent_ids):
                    # Parent done: point at the next parent so a resume skips completed parents.
                    state = _state(page_url, parent_ids[idx + 1], None)
                elif next_page_url:
                    state = _state(next_page_url, None, None)
                else:
                    state = None
                if state:
                    resumable_source_manager.save_state(state)
                if rows:
                    yield [{**row, parent.injected_field: parent_id} for row in rows]
                resumable_source_manager.safe_point()
                url = next_url

        page_url = next_page_url


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZendutyResumeConfig],
    page_size: int = 100,
) -> Iterator[list[dict[str, Any]]]:
    config = ZENDUTY_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across pages so urllib3 keeps the connection alive.
    session = make_tracked_session()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.parent is not None:
        parent = FAN_OUT_PARENTS[config.parent]
        yield from _paginate_fan_out(
            session, headers, config, parent, logger, resumable_source_manager, resume, page_size
        )
    else:
        yield from _paginate_top_level(session, headers, config, logger, resumable_source_manager, resume, page_size)


def zenduty_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZendutyResumeConfig],
    page_size: int = 100,
) -> SourceResponse:
    config = ZENDUTY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            page_size=page_size,
        ),
        primary_keys=config.primary_keys,
        # No partitioning: Zenduty's per-resource creation-timestamp field names aren't verified
        # against a live account, and partitioning on an absent field fails the sync. Partitioning
        # can be added later once the stable creation-date column is confirmed per endpoint.
    )


def probe_credentials(api_key: str) -> int | None:
    """Cheap probe of the account teams collection. Returns the HTTP status code, or None on a
    connection failure. Zenduty returns 403 with `{"error": "Invalid or Inactive Token"}` for a bad
    token (there is no 401), and 200 for a valid one."""
    url = _initial_url(ZENDUTY_ENDPOINTS["teams"].path, page_size=1)
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
    except Exception:
        return None
    return response.status_code
