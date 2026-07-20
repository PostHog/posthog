import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.uservoice.settings import (
    PER_PAGE,
    USERVOICE_ENDPOINTS,
    UservoiceEndpointConfig,
)

USERVOICE_API_PATH = "/api/v2/admin"

# A single DNS label: letters, digits, hyphens (not leading/trailing). Rejects anything that could
# retarget the host (slashes, `@`, dots) so the stored token is only ever sent to `<subdomain>.uservoice.com`.
_SUBDOMAIN_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


class UservoiceRetryableError(Exception):
    pass


@dataclasses.dataclass
class UservoiceResumeConfig:
    # Opaque cursor token from `pagination.cursor`, when the account uses cursor pagination.
    cursor: str | None = None
    # 1-indexed page for the page-number fallback. Only one of `cursor`/`page` is set at a time.
    page: int | None = None


@dataclasses.dataclass
class _NextPage:
    cursor: str | None = None
    page: int | None = None


def normalize_subdomain(subdomain: str) -> str:
    """Reduce user input to a bare, validated UserVoice subdomain label.

    Accepts either the full host (``yourcompany.uservoice.com``) or the bare subdomain
    (``yourcompany``). Raises ``ValueError`` on anything that isn't a single DNS label so the
    token can never be retargeted away from ``<subdomain>.uservoice.com``.
    """
    cleaned = subdomain.strip().removeprefix("https://").removeprefix("http://")
    cleaned = cleaned.strip("/")
    cleaned = cleaned.removesuffix(".uservoice.com")
    if not _SUBDOMAIN_RE.match(cleaned):
        raise ValueError(
            f"Invalid UserVoice account subdomain: {subdomain!r}. Enter just your subdomain, e.g. "
            "'yourcompany' for yourcompany.uservoice.com."
        )
    return cleaned


def _base_url(subdomain: str) -> str:
    return f"https://{normalize_subdomain(subdomain)}.uservoice.com{USERVOICE_API_PATH}"


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def _format_updated_after(value: Any) -> str:
    """Format an incremental cursor as the ISO8601 UTC string UserVoice expects for `updated_after`.

    UserVoice documents the ``YYYY-mm-ddThh:mm:ssZ`` shape, so we emit the ``Z`` suffix rather than the
    ``+00:00`` offset that ``isoformat()`` produces.
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _build_url(base_url: str, path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{base_url}{path}"
    return f"{base_url}{path}?{urlencode(params)}"


def _build_initial_params(
    config: UservoiceEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": PER_PAGE}
    # Only the `updated_after`-capable endpoints filter server-side; everything else is full refresh.
    if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value:
        params["updated_after"] = _format_updated_after(db_incremental_field_last_value)
    return params


@retry(
    retry=retry_if_exception_type(
        (
            UservoiceRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    response = session.get(url, headers=headers, timeout=60)

    # UserVoice enforces a per-minute rate limit and returns 429 on exceed (requests taking >1s count
    # as extra requests). Back off and retry rather than failing the sync; transient 5xx are retryable too.
    if response.status_code == 429 or response.status_code >= 500:
        raise UservoiceRetryableError(f"UserVoice API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"UserVoice API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _next_page(pagination: dict[str, Any], current_page: int, item_count: int) -> _NextPage | None:
    """Decide how (and whether) to fetch the next page.

    Prefer UserVoice's cursor (``pagination.cursor``); fall back to page numbers
    (``pagination.page`` / ``pagination.total_pages``), and finally to a full-page heuristic if the
    metadata is ever absent (a full page implies there may be more).
    """
    cursor = pagination.get("cursor")
    if cursor:
        return _NextPage(cursor=str(cursor))

    page = pagination.get("page", pagination.get("current_page"))
    total_pages = pagination.get("total_pages")
    if isinstance(page, int) and isinstance(total_pages, int):
        return _NextPage(page=page + 1) if page < total_pages else None

    return _NextPage(page=current_page + 1) if item_count >= PER_PAGE else None


def get_rows(
    subdomain: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UservoiceResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict]]:
    config = USERVOICE_ENDPOINTS[endpoint]
    base_url = _base_url(subdomain)
    headers = _headers(api_key)
    session = make_tracked_session()

    base_params = _build_initial_params(config, should_use_incremental_field, db_incremental_field_last_value)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.cursor if resume is not None else None
    page = resume.page if resume is not None else None
    if cursor or page:
        logger.debug(f"UserVoice: resuming {endpoint} from cursor={cursor}, page={page}")

    while True:
        params = dict(base_params)
        # Keep the `updated_after` filter present on every request: with page numbers it must persist,
        # and appending the opaque cursor alongside it is idempotent if the cursor already encodes it.
        if cursor:
            params["cursor"] = cursor
        elif page:
            params["page"] = page

        data = _fetch_page(session, _build_url(base_url, config.path, params), headers, logger)
        items = data.get(config.response_key, []) or []
        pagination = data.get("pagination", {}) or {}
        next_page = _next_page(pagination, page or 1, len(items))

        if items:
            yield items

        if next_page is None:
            break
        # Guard against a non-advancing cursor to avoid looping forever on the same page.
        if next_page.cursor is not None and next_page.cursor == cursor:
            logger.warning(f"UserVoice: {endpoint} returned a non-advancing cursor, stopping pagination")
            break

        # Save AFTER yielding so a crash re-yields the last page rather than skipping it —
        # merge dedupes on the primary key.
        resumable_source_manager.save_state(UservoiceResumeConfig(cursor=next_page.cursor, page=next_page.page))
        cursor, page = next_page.cursor, next_page.page


def uservoice_source(
    subdomain: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UservoiceResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = USERVOICE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            subdomain=subdomain,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        # UserVoice's list order isn't a documented, verifiable guarantee, and its feedback endpoints
        # tend to return newest-first. "desc" defers the incremental watermark write to successful job
        # end (see finalize_desc_sort_incremental_value), so a crashed mid-sync run can't advance the
        # watermark past rows it never fetched; the next run re-pulls from the old watermark and merge
        # dedupes. Full-refresh endpoints don't checkpoint a watermark, so their sort_mode is moot.
        sort_mode="desc" if config.supports_incremental else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(subdomain: str, api_key: str) -> tuple[bool, int | None]:
    """Probe UserVoice's suggestions list to confirm the token is genuine.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error. Raises
    ``ValueError`` if the subdomain is malformed so the caller can surface a precise message.
    """
    url = _build_url(_base_url(subdomain), "/suggestions", {"per_page": 1})
    try:
        response = make_tracked_session().get(url, headers=_headers(api_key), timeout=10)
    except Exception:
        return False, None
    return response.status_code == 200, response.status_code
