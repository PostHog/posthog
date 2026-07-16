import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.reply_io.settings import REPLY_IO_ENDPOINTS

REPLY_IO_BASE_URL = "https://api.reply.io/v3"
# List endpoints accept `top` up to 1000 (default 25); the largest page minimises round trips
# against Reply's 100 requests/minute rate limit.
PAGE_SIZE = 1000
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5
# Reply's 429s carry a Retry-After header (their rate window is per minute / per hour). Cap the
# in-function wait so a long window doesn't pin a worker; Temporal retries the whole activity
# later from saved page state if the attempts exhaust.
MAX_RETRY_AFTER_SECONDS = 120


class ReplyIoRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclasses.dataclass
class ReplyIoResumeConfig:
    # Reply paginates with `top`/`skip` offsets. A crashed full-refresh sync resumes from the
    # offset after the last yielded page; merge dedupes any re-pulled rows on `id`.
    skip: int = 0


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def _parse_retry_after(value: str | None) -> Optional[float]:
    # Retry-After is either delta-seconds or an HTTP-date (RFC 7231).
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())


_backoff = wait_exponential_jitter(initial=2, max=60)


def _wait_reply_io(retry_state: RetryCallState) -> float:
    # Prefer the server's own backoff instruction on rate limits; fall back to exponential
    # jitter when the header is absent (429 without one, or a 5xx).
    exc = retry_state.outcome.exception() if retry_state.outcome is not None else None
    if isinstance(exc, ReplyIoRetryableError) and exc.retry_after is not None:
        return min(exc.retry_after, MAX_RETRY_AFTER_SECONDS)
    return _backoff(retry_state)


@retry(
    retry=retry_if_exception_type((ReplyIoRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=_wait_reply_io,
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    skip: int,
    limit: int,
    logger: FilteringBoundLogger,
) -> tuple[list[dict[str, Any]], bool]:
    response = session.get(
        f"{REPLY_IO_BASE_URL}{path}",
        params={"top": limit, "skip": skip},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise ReplyIoRetryableError(
            f"Reply API error (retryable): status={response.status_code}, path={path}",
            retry_after=_parse_retry_after(response.headers.get("Retry-After")),
        )

    if not response.ok:
        logger.error(f"Reply API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    # Paginated list endpoints wrap rows in {"items": [...], "hasMore": bool}.
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ReplyIoRetryableError(f"Reply returned an unexpected payload for {path}: {type(data).__name__}")

    items: list[dict[str, Any]] = data["items"]
    has_more = bool(data.get("hasMore"))
    return items, has_more


@retry(
    retry=retry_if_exception_type((ReplyIoRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=_wait_reply_io,
    reraise=True,
)
def _fetch_all(
    session: requests.Session,
    path: str,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    # Small catalog endpoints (custom fields, template folders) return a bare, unpaginated array.
    response = session.get(f"{REPLY_IO_BASE_URL}{path}", timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise ReplyIoRetryableError(
            f"Reply API error (retryable): status={response.status_code}, path={path}",
            retry_after=_parse_retry_after(response.headers.get("Retry-After")),
        )

    if not response.ok:
        logger.error(f"Reply API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    if not isinstance(data, list):
        raise ReplyIoRetryableError(f"Reply returned an unexpected payload for {path}: {type(data).__name__}")
    return data


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ReplyIoResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = REPLY_IO_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    if not config.paginated:
        items = _fetch_all(session, config.path, logger)
        if items:
            yield items
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    skip = resume.skip if resume else 0
    if resume and resume.skip:
        logger.debug(f"Reply.io: resuming {endpoint} from offset {skip}")

    while True:
        items, has_more = _fetch_page(session, config.path, skip, PAGE_SIZE, logger)
        if items:
            yield items

        if not has_more or not items:
            break

        # Advance by the rows actually received, not PAGE_SIZE — robust to a server-side page cap.
        skip += len(items)
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes any re-pulled rows on the primary key.
        resumable_source_manager.save_state(ReplyIoResumeConfig(skip=skip))


def reply_io_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ReplyIoResumeConfig],
) -> SourceResponse:
    config = REPLY_IO_ENDPOINTS[endpoint]

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


def check_access(api_key: str, path: str, paginated: bool = False) -> tuple[int, Optional[str]]:
    """Probe an endpoint with the smallest possible request.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(
            f"{REPLY_IO_BASE_URL}{path}",
            params={"top": 1} if paginated else None,
            timeout=15,
        )
    except Exception as e:
        return 0, f"Could not connect to Reply: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Reply returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str, endpoint: Optional[str] = None) -> tuple[bool, str | None]:
    """Validate the API key against `/whoami` (needs no scope), or a specific endpoint's scope."""
    if endpoint is not None:
        config = REPLY_IO_ENDPOINTS[endpoint]
        status, message = check_access(api_key, config.path, paginated=config.paginated)
        if status == 403:
            return False, f"Your Reply API key is missing the `{config.scope}` scope"
    else:
        status, message = check_access(api_key, "/whoami")

    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Reply API key"
    return False, message or "Could not validate Reply API key"


def check_endpoint_permissions(api_key: str, endpoints: list[str]) -> dict[str, str | None]:
    """Per-table scope status for the schema picker. ``None`` = reachable, str = why not.

    Endpoints sharing a scope share one probe, so the whole check costs at most one request per
    distinct scope. Only a real 403 counts as a missing scope — throttles, 5xx, and network blips
    are reported as reachable so a transient error never blocks the picker.
    """
    verdict_by_scope: dict[str, str | None] = {}
    results: dict[str, str | None] = {}
    for name in endpoints:
        config = REPLY_IO_ENDPOINTS.get(name)
        if config is None:
            results[name] = None
            continue
        if config.scope not in verdict_by_scope:
            status, _ = check_access(api_key, config.path, paginated=config.paginated)
            verdict_by_scope[config.scope] = (
                f"Your Reply API key is missing the `{config.scope}` scope" if status == 403 else None
            )
        results[name] = verdict_by_scope[config.scope]
    return results
