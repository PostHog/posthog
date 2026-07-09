from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.monday.settings import MONDAY_ENDPOINTS

MONDAY_API_URL = "https://api.monday.com/v2"
# Pinned GA API version (monday releases quarterly versions).
MONDAY_API_VERSION = "2024-10"
# Boards/users page size; items_page caps at 500.
PAGE_SIZE = 100
ITEMS_PAGE_SIZE = 500
REQUEST_TIMEOUT_SECONDS = 120
# Rate limiting is complexity-budget based (5-10M points/min by tier) and
# surfaces as a GraphQL error (not a 429); exponential backoff rides out the minute window.
MAX_RETRY_ATTEMPTS = 5

_BOARDS_QUERY = """
query ($limit: Int!, $page: Int!) {
  boards (limit: $limit, page: $page) {
    id
    name
    board_kind
    state
    description
    workspace_id
    item_terminology
    items_count
    permissions
    updated_at
  }
}
"""

_USERS_QUERY = """
query ($limit: Int!, $page: Int!) {
  users (limit: $limit, page: $page) {
    id
    name
    email
    enabled
    is_admin
    is_guest
    is_pending
    title
    location
    created_at
    last_activity
  }
}
"""

_WORKSPACES_QUERY = """
query ($limit: Int!, $page: Int!) {
  workspaces (limit: $limit, page: $page) {
    id
    name
    kind
    description
    state
    created_at
  }
}
"""

_ITEM_FIELDS = """
      id
      name
      state
      created_at
      updated_at
      group { id title }
      creator_id
      column_values { id type text value }
"""

_BOARD_IDS_QUERY = """
query ($limit: Int!, $page: Int!) {
  boards (limit: $limit, page: $page) { id }
}
"""

_ITEMS_PAGE_QUERY = f"""
query ($boardId: [ID!], $limit: Int!) {{
  boards (ids: $boardId) {{
    items_page (limit: $limit) {{
      cursor
      items {{
{_ITEM_FIELDS}
      }}
    }}
  }}
}}
"""

_NEXT_ITEMS_PAGE_QUERY = f"""
query ($cursor: String!, $limit: Int!) {{
  next_items_page (cursor: $cursor, limit: $limit) {{
    cursor
    items {{
{_ITEM_FIELDS}
    }}
  }}
}}
"""


class MondayRetryableError(Exception):
    pass


class MondayGraphQLError(Exception):
    pass


def _get_session(api_token: str) -> requests.Session:
    return make_tracked_session(
        headers={"Authorization": api_token, "API-Version": MONDAY_API_VERSION},
        redact_values=(api_token,),
    )


def _execute(
    session: requests.Session,
    query: str,
    variables: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.post(
        MONDAY_API_URL,
        json={"query": query, "variables": variables},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise MondayRetryableError(f"monday.com API error (retryable): status={response.status_code}")

    if not response.ok:
        logger.error(f"monday.com API error: status={response.status_code}, body={response.text}")
        response.raise_for_status()

    body = response.json()
    errors = body.get("errors")
    if errors:
        message = "; ".join(str(error.get("message", error)) for error in errors)
        # Complexity-budget exhaustion comes back as a GraphQL error, not a 429.
        if "complexity" in message.lower():
            raise MondayRetryableError(f"monday.com complexity budget exhausted: {message}")
        raise MondayGraphQLError(f"monday.com GraphQL error: {message}")

    return body.get("data") or {}


class _NoopLogger:
    def error(self, *args: Any, **kwargs: Any) -> None:
        return None

    def debug(self, *args: Any, **kwargs: Any) -> None:
        return None


def validate_credentials(api_token: str) -> bool:
    """Confirm the API token is valid with a cheap `me` query."""
    try:
        session = _get_session(api_token)
        data = _execute(session, "query { me { id } }", {}, _NoopLogger())  # type: ignore[arg-type]
        return bool((data.get("me") or {}).get("id"))
    except Exception:
        return False


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    session = _get_session(api_token)

    @retry(
        retry=retry_if_exception_type((MondayRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=5, max=120),
        reraise=True,
    )
    def execute(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        return _execute(session, query, variables, logger)

    def iterate_paged(query: str, data_key: str) -> Iterator[list[dict[str, Any]]]:
        page = 1
        while True:
            data = execute(query, {"limit": PAGE_SIZE, "page": page})
            items = data.get(data_key) or []
            if items:
                yield items
            if len(items) < PAGE_SIZE:
                return
            page += 1

    if endpoint == "boards":
        yield from iterate_paged(_BOARDS_QUERY, "boards")
        return

    if endpoint == "users":
        yield from iterate_paged(_USERS_QUERY, "users")
        return

    if endpoint == "workspaces":
        yield from iterate_paged(_WORKSPACES_QUERY, "workspaces")
        return

    # items: fan out over every board, then walk its items_page cursor chain.
    board_ids = [board["id"] for page in iterate_paged(_BOARD_IDS_QUERY, "boards") for board in page]

    for board_id in board_ids:
        data = execute(_ITEMS_PAGE_QUERY, {"boardId": [board_id], "limit": ITEMS_PAGE_SIZE})
        boards = data.get("boards") or []
        items_page = (boards[0].get("items_page") if boards else None) or {}

        while True:
            items = [{**item, "_board_id": board_id} for item in (items_page.get("items") or [])]
            if items:
                yield items

            cursor: Optional[str] = items_page.get("cursor")
            if not cursor or not items:
                break

            data = execute(_NEXT_ITEMS_PAGE_QUERY, {"cursor": cursor, "limit": ITEMS_PAGE_SIZE})
            items_page = data.get("next_items_page") or {}


def monday_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = MONDAY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )
