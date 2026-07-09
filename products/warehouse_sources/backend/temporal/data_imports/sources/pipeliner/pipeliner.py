import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.pipeliner.settings import PIPELINER_ENDPOINTS

# Pipeliner caps list pages at 100 records (default 30); the largest page minimizes round trips.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5

HOST_NOT_ALLOWED_ERROR = "Pipeliner service URL is not allowed"

# Cheap collection used to confirm the API key pair is genuine. The keys are space-wide, so one
# probe validates access to every entity collection.
DEFAULT_PROBE_ENTITY = "Clients"

# The default cursor advertised in settings.py; every Pipeliner entity carries `modified`.
DEFAULT_INCREMENTAL_FIELD = "modified"


class PipelinerRetryableError(Exception):
    pass


class PipelinerHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class PipelinerResumeConfig:
    # `page_info.end_cursor` of the last page yielded; passed back via `after` to resume from the
    # next page. Merge dedupes any re-pulled rows on the primary key.
    cursor: str | None = None
    # The formatted incremental filter value the cursor was minted under. Reapplied verbatim on
    # resume so the resumed query walks the same result set even if the stored watermark advanced
    # while earlier batches were being persisted.
    filter_value: str | None = None


def normalize_service_url(service_url: str) -> str:
    """Turn whatever the user typed into a bare API host.

    Accepts values like ``us-east.api.pipelinersales.com``,
    ``https://us-east.api.pipelinersales.com/``, or a full base URL including the
    ``/api/v100/rest/spaces/...`` path, and returns just the host.
    """
    service_url = service_url.strip()
    service_url = re.sub(r"^https?://", "", service_url, flags=re.IGNORECASE)
    return service_url.split("/")[0].strip()


def _base_url(service_url: str, space_id: str) -> str:
    return f"https://{normalize_service_url(service_url)}/api/v100/rest/spaces/{space_id.strip()}"


def _make_session(username: str, password: str) -> requests.Session:
    # allow_redirects=False: the service URL is user-controlled, so never follow a redirect that
    # could point at an internal address (SSRF).
    session = make_tracked_session(
        headers={"Accept": "application/json"},
        redact_values=(username, password),
        allow_redirects=False,
    )
    session.auth = (username, password)
    return session


def _format_incremental_value(value: Any) -> str:
    """Pipeliner stores every timestamp in UTC and accepts ISO 8601 values in filters."""
    if isinstance(value, datetime):
        utc_dt = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return utc_dt.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d 00:00:00")
    return str(value)


def _reject_redirect(response: requests.Response) -> None:
    # A 3xx isn't an error status (`response.ok` is True), so reject it explicitly rather than
    # parsing the redirect body as data — the Location could point at an internal address (SSRF).
    if response.is_redirect or response.is_permanent_redirect:
        raise PipelinerHostNotAllowedError(
            f"Pipeliner API returned an unexpected redirect (status={response.status_code}); refusing to follow it"
        )


@retry(
    retry=retry_if_exception_type((PipelinerRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise PipelinerRetryableError(f"Pipeliner API error (retryable): status={response.status_code}, url={url}")

    _reject_redirect(response)

    if not response.ok:
        logger.error(f"Pipeliner API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    # List endpoints wrap records in {"success": bool, "data": [...], "page_info": {...}}.
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise PipelinerRetryableError(f"Pipeliner returned an unexpected payload for {url}: {type(data).__name__}")

    page_info = data.get("page_info") or {}
    end_cursor = page_info.get("end_cursor") if isinstance(page_info, dict) else None
    has_next_page = bool(page_info.get("has_next_page")) if isinstance(page_info, dict) else False
    return data["data"], end_cursor if isinstance(end_cursor, str) else None, has_next_page


def get_rows(
    service_url: str,
    space_id: str,
    username: str,
    password: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PipelinerResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = PIPELINER_ENDPOINTS[endpoint]

    # Re-check at run time (not just at source-create) in case the service URL was edited or now
    # resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(normalize_service_url(service_url), team_id)
    if not host_ok:
        raise PipelinerHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

    session = _make_session(username, password)
    url = f"{_base_url(service_url, space_id)}/entities/{config.entity}"

    cursor_field = incremental_field or DEFAULT_INCREMENTAL_FIELD
    filter_value: str | None = None
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        filter_value = _format_incremental_value(db_incremental_field_last_value)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor: str | None = None
    if resume is not None:
        cursor = resume.cursor
        filter_value = resume.filter_value
        logger.debug(f"Pipeliner: resuming {endpoint} from cursor {cursor}")

    # Ascending sort on a monotonic field keeps page boundaries stable, and for incremental syncs
    # matches sort_mode="asc" so the pipeline's watermark checkpoints correctly. `filter`,
    # `order-by`, and the `after` cursor are documented as regular list parameters and are re-sent
    # on every page, so the time window applies to the whole walk, not just page one.
    order_by = cursor_field if should_use_incremental_field else config.partition_key

    while True:
        params: dict[str, Any] = {"first": PAGE_SIZE, "order-by": order_by}
        if filter_value is not None:
            params[f"filter[{cursor_field}]"] = filter_value
            params[f"filter-op[{cursor_field}]"] = "gte"
        if cursor is not None:
            params["after"] = cursor

        items, end_cursor, has_next_page = _fetch_page(session, url, params, logger)
        if items:
            yield items

        # `has_next_page` false (or an empty/cursor-less page, defensively) ends the collection.
        if not has_next_page or not end_cursor or not items:
            break

        cursor = end_cursor
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes any re-pulled rows on the primary key.
        resumable_source_manager.save_state(PipelinerResumeConfig(cursor=cursor, filter_value=filter_value))


def pipeliner_source(
    service_url: str,
    space_id: str,
    username: str,
    password: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PipelinerResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = PIPELINER_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            service_url=service_url,
            space_id=space_id,
            username=username,
            password=password,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            team_id=team_id,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
    )


def check_access(
    service_url: str,
    space_id: str,
    username: str,
    password: str,
    entity: str = DEFAULT_PROBE_ENTITY,
) -> tuple[int, Optional[str]]:
    """Probe a single entity collection to validate the API key pair.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = _make_session(username, password)
    url = f"{_base_url(service_url, space_id)}/entities/{entity}"
    try:
        response = session.get(url, params={"first": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Pipeliner: {e}"

    if response.is_redirect or response.is_permanent_redirect:
        return 0, HOST_NOT_ALLOWED_ERROR

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        # Error responses carry {"code", "name", "message", ...}; surface the message when present.
        try:
            message = response.json().get("message")
        except Exception:
            message = None
        return response.status_code, message or f"Pipeliner returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(
    service_url: str,
    space_id: str,
    username: str,
    password: str,
    schema_name: Optional[str] = None,
    team_id: Optional[int] = None,
) -> tuple[bool, str | None]:
    host = normalize_service_url(service_url)
    if not host or not re.match(r"^[A-Za-z0-9.\-]+$", host):
        return False, "Invalid Pipeliner service URL"

    if not space_id.strip() or not re.match(r"^[A-Za-z0-9\-]+$", space_id.strip()):
        return False, "Invalid Pipeliner space ID"

    # The service URL is fully customer-controlled, so block hosts that resolve to private/
    # internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(host, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    status, message = check_access(service_url, space_id, username, password)
    if status == 200:
        return True, None
    if status == 401:
        return False, "Invalid Pipeliner API credentials"
    if status == 403:
        if schema_name is None:
            # Valid credentials, missing permission for this probe — let source creation through.
            return True, None
        return False, "Your Pipeliner API application lacks the required permissions for this endpoint"
    return False, message or "Could not validate Pipeliner API credentials"
