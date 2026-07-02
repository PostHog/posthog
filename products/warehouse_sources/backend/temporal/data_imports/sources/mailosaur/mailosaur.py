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
from products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.settings import (
    MAILOSAUR_ENDPOINTS,
    MailosaurEndpointConfig,
)

# All Mailosaur API traffic is HTTPS against the single documented host.
MAILOSAUR_BASE_URL = "https://mailosaur.com"

# Messages list pagination — itemsPerPage caps at 1000 (default 50); pull the max to minimize round-trips.
MESSAGES_PAGE_SIZE = 1000

MAILOSAUR_HEADERS = {"Accept": "application/json"}


class MailosaurRetryableError(Exception):
    pass


@dataclasses.dataclass
class MailosaurResumeConfig:
    # Server whose messages we were paginating when the sync was interrupted. A stable
    # server-id bookmark (not a positional index) so servers added/removed between a crash
    # and the retry can't resume us into the wrong server. `None` for the non-fan-out
    # endpoints (servers, usage_transactions), which are a single request.
    server_id: str | None = None
    # Next page (0-based) to fetch for `server_id`.
    page: int = 0


def _auth(api_key: str) -> tuple[str, str]:
    """Mailosaur authenticates with the API key as the HTTP Basic auth username and no password."""
    return (api_key, "")


def _format_received_after(value: Any) -> str | None:
    """Format an incremental cursor value as an ISO-8601 UTC timestamp for `receivedAfter`."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if value:
        return str(value)
    return None


def _extract_items(data: Any) -> list[dict[str, Any]]:
    """Mailosaur list endpoints wrap results as ``{"items": [...]}``; be defensive and also
    accept a bare array in case a response comes back unwrapped."""
    if isinstance(data, dict):
        items = data.get("items")
        return items if isinstance(items, list) else []
    if isinstance(data, list):
        return data
    return []


@retry(
    retry=retry_if_exception_type(
        (
            MailosaurRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(
    session: requests.Session,
    api_key: str,
    path: str,
    logger: FilteringBoundLogger,
    params: dict[str, Any] | None = None,
) -> Any:
    url = f"{MAILOSAUR_BASE_URL}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"

    response = session.get(url, auth=_auth(api_key), headers=MAILOSAUR_HEADERS, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise MailosaurRetryableError(f"Mailosaur API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Mailosaur API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Probe the account-level `GET /api/servers` endpoint to confirm the key is genuine.

    An account-level key is required to enumerate servers (and therefore to sync any mail);
    a server-scoped key is rejected here, which is the correct signal for this connector.
    """
    url = f"{MAILOSAUR_BASE_URL}/api/servers"
    try:
        response = make_tracked_session().get(url, auth=_auth(api_key), headers=MAILOSAUR_HEADERS, timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Mailosaur API key"
    if response.status_code == 403:
        return False, "This Mailosaur API key cannot list servers. Use an account-level API key."
    return False, f"Mailosaur API error: {response.status_code}"


def _iter_servers(session: requests.Session, api_key: str, logger: FilteringBoundLogger) -> list[dict[str, Any]]:
    """List every server on the account. The endpoint returns all servers in one response."""
    data = _fetch(session, api_key, "/api/servers", logger)
    return _extract_items(data)


def _get_message_rows(
    session: requests.Session,
    api_key: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MailosaurResumeConfig],
    received_after: str | None,
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every server, yielding message summaries newest-first per server.

    Each summary omits its parent server, so we inject `server` onto every row to make the
    (server, id) primary key unique table-wide. `receivedAfter` bounds the low end server-side,
    so incremental syncs only walk the delta.
    """
    servers = _iter_servers(session, api_key, logger)
    server_ids = [server["id"] for server in servers]

    # Resolve the saved bookmark to the slice of servers still to process. If the bookmarked
    # server no longer exists (deleted between runs), start over from the first — merge dedupes
    # the re-pulled rows on the primary key.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = server_ids
    resume_page = 0
    if resume is not None and resume.server_id is not None and resume.server_id in server_ids:
        remaining = server_ids[server_ids.index(resume.server_id) :]
        resume_page = resume.page
        logger.debug(f"Mailosaur: resuming messages from server_id={resume.server_id}, page={resume_page}")

    for index, server_id in enumerate(remaining):
        page = resume_page if index == 0 else 0
        while True:
            params: dict[str, Any] = {
                "server": server_id,
                "page": page,
                "itemsPerPage": MESSAGES_PAGE_SIZE,
            }
            if received_after:
                params["receivedAfter"] = received_after

            items = _extract_items(_fetch(session, api_key, "/api/messages", logger, params))
            if items:
                for item in items:
                    item["server"] = server_id
                yield items

            # Offset pagination: a short (or empty) page means we've reached the end for this server.
            if len(items) < MESSAGES_PAGE_SIZE:
                break

            page += 1
            # Save AFTER yielding so a crash re-yields the last page (merge dedupes) rather than
            # skipping it. Bookmark the NEXT page to fetch for the current server.
            resumable_source_manager.save_state(MailosaurResumeConfig(server_id=server_id, page=page))

        # Advance the bookmark to the next server so a crash between servers resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(MailosaurResumeConfig(server_id=remaining[index + 1], page=0))


def _get_simple_rows(
    session: requests.Session,
    api_key: str,
    config: MailosaurEndpointConfig,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Single-request endpoints (servers, usage_transactions) that return the full table at once."""
    items = _extract_items(_fetch(session, api_key, config.path, logger))
    if items:
        yield items


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MailosaurResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = MAILOSAUR_ENDPOINTS[endpoint]
    # One session reused across every page (and, for the fan-out, every server) so urllib3
    # keeps the connection alive instead of re-handshaking per request.
    session = make_tracked_session()

    if config.fan_out_over_servers:
        received_after = (
            _format_received_after(db_incremental_field_last_value)
            if should_use_incremental_field and db_incremental_field_last_value
            else None
        )
        yield from _get_message_rows(session, api_key, logger, resumable_source_manager, received_after)
        return

    yield from _get_simple_rows(session, api_key, config, logger)


def mailosaur_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MailosaurResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = MAILOSAUR_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Messages arrive newest-first and the API exposes no ascending sort, so the watermark
        # (max received) is finalized only at end of sync — see finalize_desc_sort_incremental_value.
        sort_mode="desc" if endpoint_config.fan_out_over_servers else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
