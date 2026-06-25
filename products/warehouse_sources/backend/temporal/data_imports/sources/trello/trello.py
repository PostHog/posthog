import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.trello.settings import (
    TRELLO_ENDPOINTS,
    TrelloEndpointConfig,
)

TRELLO_BASE_URL = "https://api.trello.com/1"


class TrelloRetryableError(Exception):
    pass


@dataclasses.dataclass
class TrelloResumeConfig:
    # Number of boards fully synced; board-scoped endpoints resume past these.
    board_index: int = 0
    # Oldest action id of the last fetched page within the in-progress board
    # (actions only) — used as the ``before`` cursor to re-enter pagination.
    before_cursor: str | None = None


def _get_headers(api_key: str, api_token: str) -> dict[str, str]:
    # Header auth keeps the secret token out of request URLs (and therefore out of
    # our tracked-session request logs), unlike Trello's ?key=&token= query params.
    return {"Authorization": f'OAuth oauth_consumer_key="{api_key}", oauth_token="{api_token}"'}


def _id_to_created_at(obj_id: Any) -> str | None:
    """Derive a creation timestamp from a Trello ObjectID.

    Trello IDs are MongoDB ObjectIDs whose first 8 hex chars encode the Unix
    creation time. Most Trello objects expose no creation timestamp of their own,
    so we surface this as a stable ``created_at`` for partitioning.
    """
    if not isinstance(obj_id, str) or len(obj_id) < 8:
        return None
    try:
        timestamp = int(obj_id[:8], 16)
    except ValueError:
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()


def _add_created_at(item: dict[str, Any]) -> dict[str, Any]:
    if "created_at" not in item:
        created_at = _id_to_created_at(item.get("id"))
        if created_at is not None:
            item["created_at"] = created_at
    return item


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor value as an ISO 8601 string for Trello's ``since`` filter."""
    if isinstance(value, datetime):
        utc_value = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return utc_value.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


@retry(
    retry=retry_if_exception_type((TrelloRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch(url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> requests.Response:
    response = make_tracked_session().get(url, headers=headers, timeout=60)

    # Trello rate-limits aggressively (300 req/10s per key, 100 req/10s per token)
    # and returns 429 when exceeded; retry those plus transient 5xx with backoff.
    if response.status_code == 429 or response.status_code >= 500:
        raise TrelloRetryableError(f"Trello API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Trello API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response


def validate_credentials(api_key: str, api_token: str) -> tuple[bool, str | None]:
    url = f"{TRELLO_BASE_URL}/members/me"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key, api_token), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None

    # Trello answers a missing/invalid token with 400 ("invalid token") and an
    # invalid key with 401 ("invalid key"); both mean the credentials are bad.
    if response.status_code in (400, 401):
        return False, "Invalid Trello API key or token"
    if response.status_code == 403:
        return False, "Your Trello token does not have the required permissions"

    return False, response.text or f"Trello API returned status {response.status_code}"


def _fetch_board_ids(headers: dict[str, str], logger: FilteringBoundLogger) -> list[str]:
    url = f"{TRELLO_BASE_URL}/members/me/boards?{urlencode({'fields': 'id'})}"
    data = _fetch(url, headers, logger).json()
    if not isinstance(data, list):
        return []
    return [board["id"] for board in data if isinstance(board, dict) and board.get("id")]


def _sync_member_endpoint(
    config: TrelloEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
) -> Iterator[Any]:
    url = f"{TRELLO_BASE_URL}{config.path}?{urlencode({'limit': config.page_size})}"
    data = _fetch(url, headers, logger).json()
    if not isinstance(data, list):
        return

    if len(data) >= config.page_size:
        logger.warning(
            f"Trello {config.name} returned {len(data)} rows at the {config.page_size} page cap; "
            "results may be truncated."
        )

    for item in data:
        if not isinstance(item, dict):
            continue
        batcher.batch(_add_created_at(item))
        if batcher.should_yield():
            yield batcher.get_table()


def _sync_board_simple(
    board_id: str,
    index: int,
    config: TrelloEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    manager: ResumableSourceManager[TrelloResumeConfig],
) -> Iterator[Any]:
    url = f"{TRELLO_BASE_URL}/boards/{board_id}/{config.path}?{urlencode({'limit': config.page_size})}"
    data = _fetch(url, headers, logger).json()

    if isinstance(data, list):
        if len(data) >= config.page_size:
            logger.warning(
                f"Trello {config.name} for board {board_id} returned {len(data)} rows at the "
                f"{config.page_size} page cap; results may be truncated."
            )
        for item in data:
            if not isinstance(item, dict):
                continue
            batcher.batch(_add_created_at(item))
            if batcher.should_yield():
                yield batcher.get_table()
                manager.save_state(TrelloResumeConfig(board_index=index, before_cursor=None))

    # Board complete: the next resume starts at the following board.
    manager.save_state(TrelloResumeConfig(board_index=index + 1, before_cursor=None))


def _sync_board_actions(
    board_id: str,
    index: int,
    config: TrelloEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    manager: ResumableSourceManager[TrelloResumeConfig],
    since: str | None,
    before: str | None,
) -> Iterator[Any]:
    # Actions come back newest-first. We page backwards with ``before`` (the oldest
    # id of the previous page) and bound the lower edge with ``since`` for
    # incremental syncs. Both filters can be combined, so a single run only fetches
    # actions newer than the watermark.
    while True:
        params: dict[str, Any] = {"limit": config.page_size}
        if since:
            params["since"] = since
        if before:
            params["before"] = before

        url = f"{TRELLO_BASE_URL}/boards/{board_id}/actions?{urlencode(params)}"
        data = _fetch(url, headers, logger).json()
        if not isinstance(data, list) or not data:
            break

        oldest_id = data[-1]["id"] if isinstance(data[-1], dict) else None

        for item in data:
            if not isinstance(item, dict):
                continue
            batcher.batch(_add_created_at(item))
            if batcher.should_yield():
                yield batcher.get_table()
                # Checkpoint the cursor that fetched the current page; on resume we
                # re-fetch it and rely on primary-key merge semantics to dedupe.
                manager.save_state(TrelloResumeConfig(board_index=index, before_cursor=before))

        if len(data) < config.page_size or not oldest_id:
            break

        before = oldest_id
        manager.save_state(TrelloResumeConfig(board_index=index, before_cursor=before))

    manager.save_state(TrelloResumeConfig(board_index=index + 1, before_cursor=None))


def _sync_board_endpoint(
    config: TrelloEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    manager: ResumableSourceManager[TrelloResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[Any]:
    board_ids = _fetch_board_ids(headers, logger)

    resume = manager.load_state() if manager.can_resume() else None
    start_index = resume.board_index if resume else 0
    resume_before = resume.before_cursor if resume else None
    if resume is not None:
        logger.debug(f"Trello: resuming {config.name} from board index {start_index}")

    since: str | None = None
    if config.paginated and should_use_incremental_field and db_incremental_field_last_value:
        since = _format_incremental_value(db_incremental_field_last_value)

    for index in range(start_index, len(board_ids)):
        board_id = board_ids[index]
        if config.paginated:
            # Only the board we resumed into carries an in-progress before cursor.
            before = resume_before if index == start_index else None
            yield from _sync_board_actions(board_id, index, config, headers, logger, batcher, manager, since, before)
        else:
            yield from _sync_board_simple(board_id, index, config, headers, logger, batcher, manager)


def get_rows(
    api_key: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TrelloResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = TRELLO_ENDPOINTS[endpoint]
    headers = _get_headers(api_key, api_token)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    if config.scope == "member":
        yield from _sync_member_endpoint(config, headers, logger, batcher)
    else:
        yield from _sync_board_endpoint(
            config,
            headers,
            logger,
            batcher,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def trello_source(
    api_key: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TrelloResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = TRELLO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[endpoint_config.primary_key],
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
