import base64
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.onepagecrm.settings import (
    ONEPAGECRM_ENDPOINTS,
    OnepagecrmEndpointConfig,
)

ONEPAGECRM_BASE_URL = "https://app.onepagecrm.com/api/v3"
# List endpoints accept a `per_page` of up to 100; the largest page minimises round trips.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
# Cheap endpoint used to confirm the user ID / API key pair is genuine. The key grants read access
# to the whole account, so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/contacts"


class OnepagecrmRetryableError(Exception):
    pass


@dataclasses.dataclass
class OnepagecrmResumeConfig:
    # Next page to fetch (1-based). Page numbering is only stable for a fixed query, so the
    # `modified_since` anchor the run started with is persisted alongside it — resuming with a
    # fresher watermark would renumber the pages and skip rows.
    page: int = 1
    modified_since: str | None = None


def _basic_auth_token(user_id: str, api_key: str) -> str:
    return base64.b64encode(f"{user_id}:{api_key}".encode("ascii")).decode("ascii")


def _headers(user_id: str, api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Basic {_basic_auth_token(user_id, api_key)}",
        "Accept": "application/json",
    }


def _to_epoch(value: Any) -> Optional[int]:
    """Coerce an incremental cursor value to a UNIX timestamp for the `modified_since` filter.

    OnePageCRM returns `modified_at` as an ISO 8601 string, so the persisted watermark can be a
    string or a parsed datetime depending on how the column was typed; ints are accepted
    defensively.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                return int(value)
            except ValueError:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return int(parsed.timestamp())
    return None


def modified_since_anchor(db_incremental_field_last_value: Any) -> str | None:
    """Compute the `modified_since` value for an incremental run.

    The anchor is backed off by one second: the API doesn't document whether the filter is
    inclusive, and re-fetching the boundary second is free (merge dedupes on `id`) while missing
    it would drop rows.
    """
    epoch = _to_epoch(db_incremental_field_last_value)
    if epoch is None:
        return None
    return str(max(0, epoch - 1))


def _build_params(
    config: OnepagecrmEndpointConfig,
    page: int,
    modified_since: str | None,
    should_use_incremental_field: bool,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if config.paginated:
        params["page"] = page
        params["per_page"] = PAGE_SIZE
    if config.supports_sort:
        # Incremental runs sort by the cursor field so the per-batch watermark advances
        # monotonically (sort_mode="asc"). Full-refresh runs sort by the immutable created_at so
        # rows never shift into already-fetched pages mid-sync.
        params["sort_by"] = "modified_at" if should_use_incremental_field else "created_at"
        params["order"] = "asc"
    if modified_since is not None:
        params["modified_since"] = modified_since
    return params


def _unwrap_items(config: OnepagecrmEndpointConfig, raw_items: list[Any]) -> list[dict[str, Any]]:
    # Paginated list responses wrap each record under its singular resource name
    # (e.g. {"contact": {...}, "next_actions": [...]}); config endpoints vary — users/statuses wrap,
    # lead_sources doesn't.
    items: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        if config.item_key is not None and isinstance(raw.get(config.item_key), dict):
            items.append(raw[config.item_key])
        else:
            items.append(raw)
    return items


def get_rows(
    user_id: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OnepagecrmResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = ONEPAGECRM_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(user_id, api_key), redact_values=(api_key,))

    @retry(
        retry=retry_if_exception_type((OnepagecrmRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(params: dict[str, Any]) -> dict[str, Any]:
        response = session.get(
            f"{ONEPAGECRM_BASE_URL}{config.path}",
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        if response.status_code == 429 or response.status_code >= 500:
            raise OnepagecrmRetryableError(
                f"OnePageCRM API error (retryable): status={response.status_code}, path={config.path}"
            )

        if not response.ok:
            logger.error(
                f"OnePageCRM API error: status={response.status_code}, body={response.text}, path={config.path}"
            )
            response.raise_for_status()

        body = response.json()
        if not isinstance(body, dict):
            raise OnepagecrmRetryableError(
                f"OnePageCRM returned an unexpected payload for {config.path}: {type(body).__name__}"
            )
        return body

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        page = resume.page
        modified_since = resume.modified_since
        logger.debug(f"OnePageCRM: resuming {endpoint} from page {page} (modified_since={modified_since})")
    else:
        page = 1
        modified_since = (
            modified_since_anchor(db_incremental_field_last_value) if should_use_incremental_field else None
        )

    if not config.paginated:
        body = fetch_page(_build_params(config, page, modified_since, should_use_incremental_field))
        raw_items = body.get("data")
        if not isinstance(raw_items, list):
            raise OnepagecrmRetryableError(
                f"OnePageCRM returned an unexpected 'data' field for {config.path}: {type(raw_items).__name__}"
            )
        items = _unwrap_items(config, raw_items)
        if items:
            yield items
        return

    while True:
        body = fetch_page(_build_params(config, page, modified_since, should_use_incremental_field))
        data = body.get("data")
        if not isinstance(data, dict) or not isinstance(data.get(config.data_key), list):
            raise OnepagecrmRetryableError(
                f"OnePageCRM returned an unexpected 'data' field for {config.path}: {type(data).__name__}"
            )

        items = _unwrap_items(config, data[config.data_key])
        if items:
            yield items

        # `max_page` marks the last page of the filtered listing; an empty or short page also
        # terminates defensively in case it's ever missing.
        max_page = data.get("max_page")
        if not items:
            break
        if isinstance(max_page, int) and page >= max_page:
            break
        if not isinstance(max_page, int) and len(items) < PAGE_SIZE:
            break

        page += 1
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(OnepagecrmResumeConfig(page=page, modified_since=modified_since))


def onepagecrm_source(
    user_id: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OnepagecrmResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ONEPAGECRM_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            user_id=user_id,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def check_access(user_id: str, api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the user ID / API key pair.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(user_id, api_key), redact_values=(api_key,))
    try:
        response = session.get(f"{ONEPAGECRM_BASE_URL}{path}", params={"per_page": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to OnePageCRM: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"OnePageCRM returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(user_id: str, api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(user_id, api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid OnePageCRM user ID or API key"
    return False, message or "Could not validate OnePageCRM credentials"
