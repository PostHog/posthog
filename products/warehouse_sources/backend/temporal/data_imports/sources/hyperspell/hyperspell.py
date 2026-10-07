from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.settings import (
    HYPERSPELL_ENDPOINTS,
    HyperspellEndpointConfig,
)

# Hyperspell runs two isolated regions; API keys are only valid in the region they were
# created in, so the base URL is a source config option.
HYPERSPELL_BASE_URLS: dict[str, str] = {
    "us": "https://api.hyperspell.com",
    "eu": "https://api.eu.hyperspell.com",
}
DEFAULT_REGION = "us"

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5


class HyperspellRetryableError(Exception):
    pass


@frozen
class HyperspellResumeConfig:
    # Opaque next-page cursor for the endpoint being synced. None means "start the current
    # user's listing from its first page".
    cursor: str | None = None
    # The user (X-As-User value) currently being fanned out over. A stable user-ID bookmark
    # (not a positional index) so a config edit between a crash and the retry can't resume
    # into the wrong user. None when querying as the app.
    user_id: str | None = None


def get_base_url(region: str | None) -> str:
    return HYPERSPELL_BASE_URLS.get((region or DEFAULT_REGION).strip().lower(), HYPERSPELL_BASE_URLS[DEFAULT_REGION])


def parse_user_ids(raw: str | None) -> list[str]:
    """Split the comma-separated user IDs field into a deduplicated, order-preserving list."""
    if not raw:
        return []
    seen: set[str] = set()
    user_ids: list[str] = []
    for part in raw.replace("\n", ",").split(","):
        user_id = part.strip()
        if user_id and user_id not in seen:
            seen.add(user_id)
            user_ids.append(user_id)
    return user_ids


def _get_headers(api_key: str, user_id: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    if user_id:
        # Memories and connections are per-user; X-As-User scopes an API-key request to one user.
        headers["X-As-User"] = user_id
    return headers


def _build_url(base_url: str, path: str, params: dict[str, Any]) -> str:
    url = f"{base_url}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    return url


def validate_credentials(
    api_key: str, region: str | None, schema_name: Optional[str] = None
) -> tuple[bool, str | None]:
    """Probe /integrations/list to confirm the API key is genuine.

    It's the cheapest app-level endpoint that works with a bare API key (no user context),
    so it validates the key without depending on which streams the team will sync.
    Hyperspell keys have no per-endpoint scopes, so one probe covers every schema.
    """
    url = _build_url(get_base_url(region), HYPERSPELL_ENDPOINTS["integrations"].path, {})
    try:
        response = make_tracked_session(redact_values=(api_key,), allow_redirects=False, capture=False).get(
            url, headers=_get_headers(api_key), timeout=REQUEST_TIMEOUT_SECONDS
        )
    except Exception:
        return False, "Could not reach the Hyperspell API. Please try again."

    if response.status_code == 200:
        return True, None
    # 401 = invalid key ("InvalidAPIKey"), 403 = missing auth ("Not authenticated"). Keys are
    # region-bound, so a valid key sent to the wrong region also surfaces as a 401.
    if response.status_code in (401, 403):
        return (
            False,
            "Invalid Hyperspell API key. Keys are region-specific, so check that the key matches the selected region.",
        )

    return False, f"Hyperspell API returned an unexpected status code: {response.status_code}"


@retry(
    retry=retry_if_exception_type((HyperspellRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, page_url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    # Rate limits aren't documented; treat 429 and transient 5xx as retryable with backoff.
    if response.status_code == 429 or response.status_code >= 500:
        raise HyperspellRetryableError(
            f"Hyperspell API error (retryable): status={response.status_code}, url={page_url}"
        )

    if not response.ok:
        logger.error(f"Hyperspell API error: status={response.status_code}, body={response.text}, url={page_url}")
        response.raise_for_status()

    return response.json()


def _normalize_row(config: HyperspellEndpointConfig, item: dict[str, Any], user_id: str | None) -> dict[str, Any]:
    row = dict(item)
    for key, default in config.null_key_defaults.items():
        if row.get(key) is None:
            row[key] = default
    if config.user_scoped:
        # Stamp the acting user on every row — the API responses don't carry it, and it's part
        # of the primary key so rows from different users can't collide. Empty string = app scope.
        row["user_id"] = user_id or ""
    return row


def _page_params(config: HyperspellEndpointConfig, cursor: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if config.pagination == "none":
        return params
    if config.page_size_param:
        params[config.page_size_param] = config.page_size
    if config.pagination == "offset":
        params["offset"] = int(cursor or 0)
    elif cursor:
        params["cursor"] = cursor
    return params


def _next_cursor(
    config: HyperspellEndpointConfig, data: dict[str, Any], items: list[dict[str, Any]], cursor: str | None
) -> str | None:
    if config.pagination == "cursor":
        return data.get("next_cursor")
    if config.pagination == "offset":
        next_offset = int(cursor or 0) + len(items)
        if items and next_offset < data.get("total", 0):
            return str(next_offset)
    return None


def _get_list_rows(
    session: requests.Session,
    base_url: str,
    config: HyperspellEndpointConfig,
    headers: dict[str, str],
    principal: str | None,
    cursor: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HyperspellResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    while True:
        url = _build_url(base_url, config.path, _page_params(config, cursor))

        data = _fetch_page(session, url, headers, logger)
        items = data.get(config.data_key) or []
        next_cursor = _next_cursor(config, data, items, cursor)

        if items:
            yield [_normalize_row(config, item, principal) for item in items]

        if not next_cursor:
            break

        # Save state AFTER yielding so a crash re-yields the last page (deduped on the
        # primary key) rather than skipping it.
        resumable_source_manager.save_state(HyperspellResumeConfig(cursor=next_cursor, user_id=principal))
        cursor = next_cursor


def _channel_integration_ids(
    session: requests.Session, base_url: str, api_key: str, logger: FilteringBoundLogger
) -> set[str]:
    url = _build_url(base_url, HYPERSPELL_ENDPOINTS["integrations"].path, {})
    integrations = _fetch_page(session, url, _get_headers(api_key), logger).get("integrations") or []
    return {
        integration["id"]
        for integration in integrations
        if integration.get("supports_channel_selection") or integration.get("requires_channel_selection")
    }


def _get_channel_rows(
    session: requests.Session,
    base_url: str,
    config: HyperspellEndpointConfig,
    headers: dict[str, str],
    principal: str | None,
    channel_integration_ids: set[str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HyperspellResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    connections_url = _build_url(base_url, HYPERSPELL_ENDPOINTS["connections"].path, {})
    connections = _fetch_page(session, connections_url, headers, logger).get("connections") or []

    for connection in connections:
        integration_id = connection.get("integration_id")
        if integration_id not in channel_integration_ids:
            continue

        path = config.path.format(integration_id=quote(integration_id, safe=""))
        url = _build_url(base_url, path, {"connection_id": connection["id"]})
        data = _fetch_page(session, url, headers, logger)

        if data.get("pending"):
            # The provider's channel list is still being walked; `channels` is empty, not real state.
            logger.warning(f"Hyperspell: channel list pending for connection {connection['id']}, skipping")
            resumable_source_manager.safe_point()
            continue
        if data.get("truncated"):
            logger.warning(f"Hyperspell: channel list truncated for connection {connection['id']}")

        channels = data.get(config.data_key) or []
        if not channels:
            resumable_source_manager.safe_point()
            continue

        selected = set(data.get("selected") or [])
        yield [
            {
                **_normalize_row(config, channel, principal),
                "connection_id": connection["id"],
                "integration_id": integration_id,
                "selected": channel.get("id") in selected,
            }
            for channel in channels
        ]


def get_rows(
    api_key: str,
    region: str | None,
    user_ids: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HyperspellResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = HYPERSPELL_ENDPOINTS[endpoint]
    base_url = get_base_url(region)
    # One session reused across every page (and every user) so urllib3 keeps the connection
    # alive instead of re-handshaking per request. capture=False keeps user-authored imported
    # content (memories, entities, context docs) out of HTTP sample storage — the name-based
    # scrubbers can't recognise it, and it lives outside the warehouse tables' access controls.
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False, capture=False)

    # Memories/connections are per-user, so user-scoped endpoints fan out over the configured
    # user IDs via X-As-User. With no user IDs configured (or for app-level endpoints) we make
    # a single pass as the app (principal None).
    principals: list[str | None] = [None]
    if config.user_scoped:
        configured = parse_user_ids(user_ids)
        if configured:
            principals = list(configured)

    # Resolve the saved user-ID bookmark to the slice of principals still to process. If the
    # bookmarked user was removed from the config between runs, start over from the first
    # principal. `resume_cursor` is consumed by the first principal only.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = principals
    resume_cursor: str | None = None
    if resume is not None and resume.user_id in principals:
        remaining = principals[principals.index(resume.user_id) :]
        resume_cursor = resume.cursor
        logger.debug(f"Hyperspell: resuming {endpoint} from user_id={resume.user_id}, cursor={resume_cursor}")

    channel_integration_ids = (
        _channel_integration_ids(session, base_url, api_key, logger) if endpoint == "integration_channels" else set()
    )

    for index, principal in enumerate(remaining):
        headers = _get_headers(api_key, principal)
        cursor = resume_cursor
        resume_cursor = None  # only the resumed-into principal uses the saved cursor

        if endpoint == "integration_channels":
            yield from _get_channel_rows(
                session,
                base_url,
                config,
                headers,
                principal,
                channel_integration_ids,
                logger,
                resumable_source_manager,
            )
        else:
            yield from _get_list_rows(
                session, base_url, config, headers, principal, cursor, logger, resumable_source_manager
            )

        # Advance the bookmark to the next user so a crash between users resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(HyperspellResumeConfig(cursor=None, user_id=remaining[index + 1]))


def hyperspell_source(
    api_key: str,
    region: str | None,
    user_ids: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HyperspellResumeConfig],
) -> SourceResponse:
    config = HYPERSPELL_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            region=region,
            user_ids=user_ids,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        # Hyperspell's list endpoints expose no sort parameter and pagination is driven by an
        # opaque cursor, so row ordering is undefined — never declare "asc" for undefined order.
        sort_mode="desc",
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
