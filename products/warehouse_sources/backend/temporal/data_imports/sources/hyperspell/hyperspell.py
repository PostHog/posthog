import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.settings import HYPERSPELL_ENDPOINTS

# Hyperspell runs two isolated regions with separate base URLs; API keys are only valid in
# the region they were created in, so the region is part of the source config.
REGION_BASE_URLS: dict[str, str] = {
    "us": "https://api.hyperspell.com",
    "eu": "https://api.eu.hyperspell.com",
}

# Hyperspell documents no rate limits, but we still retry transient 5xx and 429 with bounded
# exponential backoff so a blip or an undocumented throttle doesn't fail the whole sync.
_MAX_ATTEMPTS = 8
_REQUEST_TIMEOUT_SECONDS = 60

# Memory rows carry the full nested document payload (text + chunk children), so cap the
# per-chunk byte size below the batcher default to avoid materialising oversized Arrow tables.
_MEMORIES_CHUNK_SIZE_BYTES = 100 * 1024 * 1024


class HyperspellRetryableError(Exception):
    """Raised for rate-limit (429) and transient 5xx responses so tenacity retries them."""

    pass


@dataclasses.dataclass
class HyperspellResumeConfig:
    # The cursor used to fetch the page most recently yielded (None for the first page). On
    # resume we re-fetch this page and re-yield it (merge dedupes on the primary key) rather
    # than risk skipping rows that were batched but not yet persisted when the worker stopped.
    cursor: Optional[str] = None


def _base_url(region: str) -> str:
    return REGION_BASE_URLS.get(region, REGION_BASE_URLS["us"])


def _get_headers(api_key: str, user_id: Optional[str]) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {api_key}"}
    if user_id:
        # Memories are per-user scoped; an app-level API key plus X-As-User reads a specific
        # user's data (equivalent to exchanging the API key for that user's token).
        headers["X-As-User"] = user_id
    return headers


def _get_session(api_key: str, user_id: Optional[str]) -> requests.Session:
    # One session per sync so keep-alive is preserved across pages and retries. `redact_values`
    # masks the key from request telemetry/log samples, and `allow_redirects=False` keeps a
    # credentialed request pinned to the validated Hyperspell host. `capture=False` keeps the
    # arbitrary user-authored memory documents and query logs out of HTTP sample storage, since
    # the name-based scrubbers can't recognise that free-form content.
    return make_tracked_session(
        headers=_get_headers(api_key, user_id),
        redact_values=(api_key,),
        allow_redirects=False,
        capture=False,
    )


def _build_url(base_url: str, path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{base_url}{path}"
    return f"{base_url}{path}?{urlencode(params)}"


@retry(
    retry=retry_if_exception_type((HyperspellRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(_MAX_ATTEMPTS),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> requests.Response:
    response = session.get(url, timeout=_REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise HyperspellRetryableError(f"Hyperspell API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Hyperspell API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response


def get_rows(
    api_key: str,
    region: str,
    user_id: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HyperspellResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = HYPERSPELL_ENDPOINTS[endpoint]
    session = _get_session(api_key, user_id)
    base_url = _base_url(region)

    if not config.paginated:
        response = _fetch_page(session, _build_url(base_url, config.path, {}), logger)
        rows = response.json().get(config.data_key) or []
        if rows:
            yield rows
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor: Optional[str] = resume.cursor if resume is not None else None
    if resume is not None:
        logger.debug(f"Hyperspell: resuming {endpoint} from cursor={cursor}")

    while True:
        params: dict[str, Any] = {config.size_param: config.page_size}
        if cursor is not None:
            params["cursor"] = cursor
        response = _fetch_page(session, _build_url(base_url, config.path, params), logger)
        body = response.json()
        rows = body.get(config.data_key) or []
        if rows:
            yield rows
            resumable_source_manager.save_state(HyperspellResumeConfig(cursor=cursor))
        next_cursor = body.get("next_cursor")
        if not next_cursor:
            return
        cursor = next_cursor


def validate_credentials(api_key: str, region: str, user_id: Optional[str]) -> tuple[bool, str | None]:
    """Confirm the key is genuine with one cheap probe against the primary listing we sync."""
    url = _build_url(_base_url(region), "/memories/list", {"size": 1})
    try:
        response = _get_session(api_key, user_id).get(url, timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, (
            "Invalid Hyperspell API key. Please check your API key and the region it was created in, and try again."
        )
    if response.status_code == 403:
        return False, "Your Hyperspell API key does not have permission to list memories."

    try:
        body = response.json()
        message = body.get("message") if isinstance(body, dict) else response.text
    except Exception:
        message = response.text
    return False, message or response.text


def hyperspell_source(
    api_key: str,
    region: str,
    user_id: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HyperspellResumeConfig],
) -> SourceResponse:
    config = HYPERSPELL_ENDPOINTS[endpoint]

    def items() -> Iterator[list[dict[str, Any]]]:
        return get_rows(api_key, region, user_id, endpoint, logger, resumable_source_manager)

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_key,
        # Full refresh only — Hyperspell exposes no server-side timestamp filter — so no
        # incremental watermark depends on row order. Declared where documented, None otherwise.
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        chunk_size_bytes=_MEMORIES_CHUNK_SIZE_BYTES if endpoint == "memories" else None,
    )
