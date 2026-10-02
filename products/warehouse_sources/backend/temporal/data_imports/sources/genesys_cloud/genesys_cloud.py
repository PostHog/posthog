from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
import structlog

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAuth2Auth,
    OAuth2AuthRequestError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.genesys_cloud.settings import (
    ANALYTICS_PAGE_SIZE,
    CONVERSATION_DETAILS_PATH,
    GENESYS_CLOUD_ENDPOINTS,
    LISTING_PAGE_SIZE,
    REGIONS,
    GenesysCloudEndpointConfig,
)

logger = structlog.get_logger(__name__)

REQUEST_TIMEOUT_SECONDS = 60
VALIDATION_TIMEOUT_SECONDS = 10

# History read on the first sync and on every full refresh.
INITIAL_HISTORY = timedelta(days=365)
ANALYTICS_WINDOW = timedelta(days=1)
# A conversation keeps changing after it starts (it ends, participants join), so an incremental
# sync reads again from a bit before the watermark. Merge on the primary key removes the overlap.
INCREMENTAL_LOOKBACK = timedelta(days=2)
# The details query pages by page number, which does not scale to very large result sets. A window
# with more hits than this is split in half until it fits, down to MIN_ANALYTICS_WINDOW.
MAX_RESULTS_PER_WINDOW = 10_000
MIN_ANALYTICS_WINDOW = timedelta(seconds=1)


class InvalidGenesysCloudRegionError(ValueError):
    pass


@frozen
class GenesysCloudResumeConfig:
    # Analytics endpoints: start of the next window to read (ISO 8601).
    window_start: Optional[str] = None
    # Listing endpoints: next page number to read.
    page_number: Optional[int] = None


def _validated_region(region: str) -> str:
    if region not in REGIONS:
        raise InvalidGenesysCloudRegionError(f"Unknown Genesys Cloud region: {region!r}")
    return region


def _make_auth(region: str, client_id: str, client_secret: str) -> OAuth2Auth:
    return OAuth2Auth(
        token_url=f"https://login.{_validated_region(region)}/oauth/token",
        client_id=client_id,
        client_secret=client_secret,
        grant_type="client_credentials",
        client_auth_method="basic",
    )


def _make_session(region: str, client_id: str, client_secret: str) -> requests.Session:
    session = make_tracked_session(redact_values=(client_secret,))
    session.auth = _make_auth(region, client_id, client_secret)
    return session


def _api_base_url(region: str) -> str:
    return f"https://api.{_validated_region(region)}"


def _to_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    parsed = datetime.fromisoformat(str(value))
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _format_instant(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"


def _interval(start: datetime, end: datetime) -> str:
    return f"{_format_instant(start)}/{_format_instant(end)}"


def _starts_in_window(conversation: dict[str, Any], start: datetime, end: datetime) -> bool:
    # The API can return conversations outside the exact interval (it matches by day), so keep
    # windows disjoint here. That prevents duplicate rows across windows.
    raw = conversation.get("conversationStart")
    if not raw:
        return True
    return start <= _to_utc(raw) < end


def _to_rows(conversations: list[dict[str, Any]], flatten_participants: bool) -> list[dict[str, Any]]:
    if not flatten_participants:
        return conversations
    rows: list[dict[str, Any]] = []
    for conversation in conversations:
        for participant in conversation.get("participants") or []:
            rows.append(
                {
                    **participant,
                    "conversationId": conversation.get("conversationId"),
                    "conversationStart": conversation.get("conversationStart"),
                    "conversationEnd": conversation.get("conversationEnd"),
                }
            )
    return rows


def _query_window(
    session: requests.Session,
    url: str,
    config: GenesysCloudEndpointConfig,
    start: datetime,
    end: datetime,
) -> Iterator[tuple[list[dict[str, Any]], Optional[datetime]]]:
    """Yield `(conversations, window_end)` per page. `window_end` is set on the last page of a window."""
    page_number = 1
    while True:
        body = {
            **config.query_body,
            "interval": _interval(start, end),
            "order": "asc",
            "orderBy": "conversationStart",
            "paging": {"pageSize": ANALYTICS_PAGE_SIZE, "pageNumber": page_number},
        }
        response = session.post(url, json=body, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json() or {}
        total_hits = int(data.get("totalHits") or 0)

        if page_number == 1 and total_hits > MAX_RESULTS_PER_WINDOW:
            if end - start > MIN_ANALYTICS_WINDOW:
                middle = start + (end - start) / 2
                yield from _query_window(session, url, config, start, middle)
                yield from _query_window(session, url, config, middle, end)
                return
            logger.warning(
                "genesys_cloud_window_over_result_limit",
                endpoint=config.name,
                interval=_interval(start, end),
                total_hits=total_hits,
            )

        conversations = [c for c in data.get("conversations") or [] if _starts_in_window(c, start, end)]
        returned = len(data.get("conversations") or [])
        is_last_page = returned < ANALYTICS_PAGE_SIZE or page_number * ANALYTICS_PAGE_SIZE >= total_hits
        yield conversations, (end if is_last_page else None)
        if is_last_page:
            return
        page_number += 1


def _iter_analytics_rows(
    session: requests.Session,
    base_url: str,
    config: GenesysCloudEndpointConfig,
    resumable_source_manager: ResumableSourceManager[GenesysCloudResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> Iterator[list[dict[str, Any]]]:
    now = datetime.now(UTC)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.window_start:
        start = _to_utc(resume.window_start)
    elif db_incremental_field_last_value is not None:
        start = _to_utc(db_incremental_field_last_value) - INCREMENTAL_LOOKBACK
    else:
        start = now - INITIAL_HISTORY

    url = f"{base_url}{CONVERSATION_DETAILS_PATH}"
    while start < now:
        window_end = min(start + ANALYTICS_WINDOW, now)
        for conversations, finished_window_end in _query_window(session, url, config, start, window_end):
            rows = _to_rows(conversations, config.flatten_participants)
            if finished_window_end is not None:
                # Stage the cursor before the yield that covers it, so a resume starts after this window.
                resumable_source_manager.save_state(
                    GenesysCloudResumeConfig(window_start=_format_instant(finished_window_end))
                )
                if not rows:
                    resumable_source_manager.safe_point()
            if rows:
                yield rows
        start = window_end

    # A later sync must derive a fresh start from its watermark instead of reusing this run's cursor.
    resumable_source_manager.clear_state()


def _iter_listing_rows(
    session: requests.Session,
    base_url: str,
    config: GenesysCloudEndpointConfig,
    resumable_source_manager: ResumableSourceManager[GenesysCloudResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page_number = resume.page_number if resume is not None and resume.page_number else 1

    url = f"{base_url}{config.path}"
    while True:
        response = session.get(
            url,
            params={**config.params, "pageSize": LISTING_PAGE_SIZE, "pageNumber": page_number},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json() or {}
        entities = data.get("entities") or []
        page_count = int(data.get("pageCount") or 0)
        has_next_page = bool(entities) and page_number < page_count
        if has_next_page:
            resumable_source_manager.save_state(GenesysCloudResumeConfig(page_number=page_number + 1))
        if entities:
            yield entities
        if not has_next_page:
            # A later full refresh must restart at page one, not the last checkpoint from this run.
            resumable_source_manager.clear_state()
            return
        page_number += 1


def genesys_cloud_source(
    region: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[GenesysCloudResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = GENESYS_CLOUD_ENDPOINTS[endpoint]
    base_url = _api_base_url(region)

    def items() -> Iterator[list[dict[str, Any]]]:
        session = _make_session(region, client_id, client_secret)
        if config.kind == "analytics":
            yield from _iter_analytics_rows(
                session, base_url, config, resumable_source_manager, db_incremental_field_last_value
            )
        else:
            yield from _iter_listing_rows(session, base_url, config, resumable_source_manager)

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=list(config.primary_keys),
        partition_mode="datetime" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        sort_mode="asc",
    )


def validate_credentials(
    region: str, client_id: str, client_secret: str, endpoint: Optional[str] = None
) -> tuple[bool, str | None]:
    if region not in REGIONS:
        return False, "Select the Genesys Cloud region your organization is hosted in."

    config = GENESYS_CLOUD_ENDPOINTS[endpoint] if endpoint else None
    base_url = _api_base_url(region)
    session = _make_session(region, client_id, client_secret)
    try:
        if config is None:
            response = session.get(f"{base_url}/api/v2/organizations/me", timeout=VALIDATION_TIMEOUT_SECONDS)
        elif config.kind == "analytics":
            now = datetime.now(UTC)
            response = session.post(
                f"{base_url}{CONVERSATION_DETAILS_PATH}",
                json={"interval": _interval(now - timedelta(hours=1), now), "paging": {"pageSize": 1, "pageNumber": 1}},
                timeout=VALIDATION_TIMEOUT_SECONDS,
            )
        else:
            response = session.get(
                f"{base_url}{config.path}",
                params={"pageSize": 1, "pageNumber": 1},
                timeout=VALIDATION_TIMEOUT_SECONDS,
            )
    except OAuth2AuthRequestError as e:
        if e.is_permanent:
            return (
                False,
                "Genesys Cloud rejected the client ID and secret. Check that the OAuth client uses the client credentials grant and belongs to the selected region.",
            )
        return False, "Could not get an access token from Genesys Cloud. Try again in a few minutes."
    except requests.RequestException:
        return False, "Could not connect to Genesys Cloud. Check the selected region and try again."

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Genesys Cloud rejected the access token. Check the client ID, client secret, and region."
    if response.status_code == 403:
        # The token is valid. A missing permission only matters for the table the user asked about.
        if config is None:
            return True, None
        if config.permission:
            return (
                False,
                f"The OAuth client's role is missing the `{config.permission}` permission, which the {config.name} table needs.",
            )
        return False, f"The OAuth client does not have access to the {config.name} table."
    return False, f"Genesys Cloud returned HTTP {response.status_code}. Try again in a few minutes."
