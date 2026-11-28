from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.sources.monday.settings import MONDAY_ENDPOINTS
from products.warehouse_sources.sources.sdk import (
    SourceResponse,
    make_tracked_session,
    reach_safe_point,
    retry_with_deadline,
)

MONDAY_API_URL = "https://api.monday.com/v2"
# Framework version labels. monday releases a dated version every quarter and selects it with the
# `API-Version` header; "v2" predates dated labels and keeps sending the header it shipped with.
MONDAY_VERSION_V2 = "v2"
MONDAY_VERSION_2026_07 = "2026-07"
MONDAY_VERSION_2026_10 = "2026-10"
MONDAY_API_VERSION_HEADERS: dict[str, str] = {
    MONDAY_VERSION_V2: "2024-10",
    MONDAY_VERSION_2026_07: "2026-07",
    MONDAY_VERSION_2026_10: "2026-10",
}
# 2024-10 serves column settings as `settings_str`; 2026-07 documents only the `settings` JSON field.
MONDAY_COLUMN_SETTINGS_FIELDS: dict[str, str] = {
    MONDAY_VERSION_V2: "settings_str",
    MONDAY_VERSION_2026_07: "settings",
    MONDAY_VERSION_2026_10: "settings",
}
# Boards/users/folders page size; items_page caps at 500.
PAGE_SIZE = 100
ITEMS_PAGE_SIZE = 500
# monday caps the root `updates` query at 100 per page.
UPDATES_PAGE_SIZE = 100
# Membership lists are nested per board, so a smaller board page keeps each query's complexity low.
BOARD_SUBSCRIBERS_PAGE_SIZE = 25
# team_owners/team_subscribers page with their own limit; 25 is monday's default for both.
BOARD_TEAMS_PAGE_SIZE = 25
# Stops a board whose team list never ends a page short from looping; 1,000 teams per board is far past real use.
BOARD_TEAMS_MAX_PAGES = 40
# activity_logs accepts up to 10,000 per request; a smaller page keeps each query's complexity low.
ACTIVITY_LOGS_PAGE_SIZE = 1000
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
    board_folder_id
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

# 2026-10 removes the `enabled`/`is_admin`/`is_guest`/`is_pending` booleans; `status` and `kind` replace them.
_USERS_QUERY_2026_10 = """
query ($limit: Int!, $page: Int!) {
  users (limit: $limit, page: $page) {
    id
    name
    email
    kind
    status
    title
    location
    created_at
    last_activity
  }
}
"""

MONDAY_USERS_QUERIES: dict[str, str] = {
    MONDAY_VERSION_V2: _USERS_QUERY,
    MONDAY_VERSION_2026_07: _USERS_QUERY,
    MONDAY_VERSION_2026_10: _USERS_QUERY_2026_10,
}

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

_FOLDERS_QUERY = """
query ($limit: Int!, $page: Int!, $workspaceIds: [ID]) {
  folders (limit: $limit, page: $page, workspace_ids: $workspaceIds) {
    id
    name
    color
    created_at
    owner_id
    parent { id }
    workspace { id }
  }
}
"""

_BOARD_GROUPS_QUERY = """
query ($limit: Int!, $page: Int!) {
  boards (limit: $limit, page: $page) {
    id
    groups { id title color position archived deleted }
  }
}
"""

_UPDATES_QUERY = """
query ($limit: Int!, $page: Int!) {
  updates (limit: $limit, page: $page) {
    id
    item_id
    creator_id
    body
    text_body
    created_at
    updated_at
    edited_at
    replies { id kind creator_id body text_body created_at updated_at edited_at }
  }
}
"""

_TEAMS_QUERY = """
query {
  teams {
    id
    name
    picture_url
    is_guest
    owners { id }
    users { id }
  }
}
"""

# `Team.created_at` arrives in 2026-07; 2024-10 rejects the field.
_TEAMS_QUERY_WITH_CREATED_AT = """
query {
  teams {
    id
    name
    picture_url
    is_guest
    created_at
    owners { id }
    users { id }
  }
}
"""

MONDAY_TEAMS_QUERIES: dict[str, str] = {
    MONDAY_VERSION_V2: _TEAMS_QUERY,
    MONDAY_VERSION_2026_07: _TEAMS_QUERY_WITH_CREATED_AT,
    MONDAY_VERSION_2026_10: _TEAMS_QUERY_WITH_CREATED_AT,
}

_TAGS_QUERY = """
query {
  tags { id name color }
}
"""

_BOARD_TAGS_QUERY = """
query ($limit: Int!, $page: Int!) {
  boards (limit: $limit, page: $page) {
    id
    tags { id name color }
  }
}
"""

_BOARD_SUBSCRIBERS_QUERY = """
query ($limit: Int!, $page: Int!, $teamLimit: Int!) {
  boards (limit: $limit, page: $page) {
    id
    owners { id }
    subscribers { id }
    team_owners (limit: $teamLimit) { id }
    team_subscribers (limit: $teamLimit) { id }
  }
}
"""


def _board_team_page_query(team_field: str) -> str:
    return f"""
query ($boardId: [ID!], $limit: Int!, $page: Int!) {{
  boards (ids: $boardId) {{
    {team_field} (limit: $limit, page: $page) {{ id }}
  }}
}}
"""


_BOARD_ACTIVITY_LOGS_QUERY = """
query ($boardId: [ID!], $limit: Int!, $page: Int!, $from: ISO8601DateTime) {
  boards (ids: $boardId) {
    activity_logs (limit: $limit, page: $page, from: $from) {
      id
      event
      entity
      data
      user_id
      account_id
      created_at
    }
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


def _board_columns_query(api_version: str) -> str:
    return f"""
query ($limit: Int!, $page: Int!) {{
  boards (limit: $limit, page: $page) {{
    id
    columns {{ id title type description archived width {MONDAY_COLUMN_SETTINGS_FIELDS[api_version]} }}
  }}
}}
"""


def _format_from(value: Any) -> str:
    # Truncating to whole seconds keeps the inclusive `from` bound at or before the watermark.
    if isinstance(value, datetime):
        utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return f"{value.isoformat()}T00:00:00Z"
    return str(value)


def _parse_activity_log_created_at(value: Any) -> Any:
    # Activity log timestamps are 17-digit Unix time (100-nanosecond units) serialized as a string.
    try:
        return datetime.fromtimestamp(int(value) / 10_000_000, tz=UTC)
    except (TypeError, ValueError):
        return value


def _ids(entities: list[dict[str, Any] | None] | None) -> list[str]:
    return [entity["id"] for entity in (entities or []) if entity is not None]


def _team_row(team: dict[str, Any]) -> dict[str, Any]:
    row = {key: value for key, value in team.items() if key not in ("owners", "users")}
    return {**row, "owner_ids": _ids(team.get("owners")), "user_ids": _ids(team.get("users"))}


def _board_subscriber_rows(
    board_id: str,
    owner_ids: list[str],
    subscriber_ids: list[str],
    team_owner_ids: list[str],
    team_subscriber_ids: list[str],
) -> list[dict[str, Any]]:
    # Owners are listed apart from subscribers; one row per member keeps the role as a flag.
    rows: list[dict[str, Any]] = []
    for subscriber_type, owners, subscribers in (
        ("user", owner_ids, subscriber_ids),
        ("team", team_owner_ids, team_subscriber_ids),
    ):
        owner_set = set(owners)
        for member_id in dict.fromkeys([*subscribers, *owners]):
            rows.append(
                {
                    "_board_id": board_id,
                    "subscriber_type": subscriber_type,
                    "id": member_id,
                    "is_owner": member_id in owner_set,
                }
            )
    return rows


class MondayRetryableError(Exception):
    pass


class MondayGraphQLError(Exception):
    pass


def _api_version_header(api_version: str) -> str:
    # An unmapped label must not fall through to a request without the header: monday then serves
    # whatever version is current, which moves under a pinned source.
    try:
        return MONDAY_API_VERSION_HEADERS[api_version]
    except KeyError:
        raise ValueError(
            f"Unsupported monday.com API version {api_version!r}; supported: {tuple(MONDAY_API_VERSION_HEADERS)}"
        )


def _get_session(api_token: str, api_version: str) -> requests.Session:
    return make_tracked_session(
        headers={"Authorization": api_token, "API-Version": _api_version_header(api_version)},
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

    # MONDAY_API_URL is a fixed constant, never derived from customer input, so a 404 on it can't
    # mean "this resource doesn't exist" — it's the edge/gateway dropping the request before it
    # reaches the GraphQL engine (monday.com's own docs don't list 404 as a GraphQL response code).
    # Treat it like the other transport-layer blips (429/5xx) instead of failing the sync outright.
    if response.status_code in (404, 429) or response.status_code >= 500:
        raise MondayRetryableError(f"monday.com API error (retryable): status={response.status_code}")

    if not response.ok:
        logger.error(f"monday.com API error: status={response.status_code}, body={response.text}")
        response.raise_for_status()

    body = response.json()
    errors = body.get("errors")
    if errors:
        message = "; ".join(str(error.get("message", error)) for error in errors)
        message_lower = message.lower()
        # Complexity-budget exhaustion and transient backend failures both come back
        # as a 200 with a GraphQL error, not a 429/5xx status.
        if "complexity" in message_lower:
            raise MondayRetryableError(f"monday.com complexity budget exhausted: {message}")
        if "internal server error" in message_lower:
            raise MondayRetryableError(f"monday.com internal server error (retryable): {message}")
        raise MondayGraphQLError(f"monday.com GraphQL error: {message}")

    return body.get("data") or {}


class _NoopLogger:
    def error(self, *args: Any, **kwargs: Any) -> None:
        return None

    def debug(self, *args: Any, **kwargs: Any) -> None:
        return None


def validate_credentials(api_token: str, api_version: str) -> bool:
    """Confirm the API token is valid with a cheap `me` query."""
    try:
        session = _get_session(api_token, api_version)
        data = _execute(session, "query { me { id } }", {}, _NoopLogger())  # type: ignore[arg-type]
        return bool((data.get("me") or {}).get("id"))
    except Exception:
        return False


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    api_version: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> Iterator[list[dict[str, Any]]]:
    session = _get_session(api_token, api_version)

    @retry_with_deadline(
        retry=retry_if_exception_type((MondayRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=5, max=120),
        reraise=True,
    )
    def execute(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        return _execute(session, query, variables, logger)

    def iterate_paged(
        query: str,
        data_key: str,
        extra_variables: Optional[dict[str, Any]] = None,
        page_size: int = PAGE_SIZE,
    ) -> Iterator[list[dict[str, Any]]]:
        page = 1
        while True:
            data = execute(query, {"limit": page_size, "page": page, **(extra_variables or {})})
            items = data.get(data_key) or []
            if items:
                yield items
            if len(items) < page_size:
                return
            page += 1

    def board_team_ids(board_id: str, team_field: str, first_page: list[str]) -> list[str]:
        ids = list(first_page)
        page = 1
        last_page_size = len(first_page)
        while last_page_size >= BOARD_TEAMS_PAGE_SIZE:
            if page >= BOARD_TEAMS_MAX_PAGES:
                logger.warning(
                    "monday.com board team list hit the page cap",
                    endpoint=endpoint,
                    board_id=board_id,
                    team_field=team_field,
                    max_pages=BOARD_TEAMS_MAX_PAGES,
                )
                break
            reach_safe_point()
            page += 1
            data = execute(
                _board_team_page_query(team_field),
                {"boardId": [board_id], "limit": BOARD_TEAMS_PAGE_SIZE, "page": page},
            )
            boards = data.get("boards") or []
            page_ids = _ids(boards[0].get(team_field) if boards else None)
            ids.extend(page_ids)
            last_page_size = len(page_ids)
        return ids

    def iterate_board_children(query: str, child_key: str) -> Iterator[list[dict[str, Any]]]:
        for boards in iterate_paged(query, "boards"):
            rows = [
                {**child, "_board_id": board["id"]}
                for board in boards
                for child in (board.get(child_key) or [])
                if child is not None
            ]
            if rows:
                yield rows

    def board_ids() -> list[str]:
        return [board["id"] for page in iterate_paged(_BOARD_IDS_QUERY, "boards") for board in page]

    if endpoint == "boards":
        yield from iterate_paged(_BOARDS_QUERY, "boards")
        return

    if endpoint == "users":
        yield from iterate_paged(MONDAY_USERS_QUERIES[api_version], "users")
        return

    if endpoint == "workspaces":
        yield from iterate_paged(_WORKSPACES_QUERY, "workspaces")
        return

    if endpoint == "updates":
        # Updates come newest first, so a comment posted mid-walk pushes the previous page's last rows onto
        # the next page. Deletions mid-walk can still skip a row until the next refresh.
        previous_page_ids: set[str] = set()
        for updates_page in iterate_paged(_UPDATES_QUERY, "updates", page_size=UPDATES_PAGE_SIZE):
            updates = [update for update in updates_page if update is not None]
            page_ids = {update["id"] for update in updates}
            fresh_updates = [update for update in updates if update["id"] not in previous_page_ids]
            previous_page_ids = page_ids
            if fresh_updates:
                yield fresh_updates
            else:
                reach_safe_point()
        return

    if endpoint == "teams":
        data = execute(MONDAY_TEAMS_QUERIES[api_version], {})
        teams = [_team_row(team) for team in (data.get("teams") or []) if team is not None]
        if teams:
            yield teams
        return

    if endpoint == "tags":
        # The root query returns only public tags; private and shareable boards keep their tags on the board.
        seen_tag_ids: set[str] = set()

        def new_tags(tags: list[Any]) -> list[dict[str, Any]]:
            fresh = list({tag["id"]: tag for tag in tags if tag is not None and tag["id"] not in seen_tag_ids}.values())
            seen_tag_ids.update(tag["id"] for tag in fresh)
            return fresh

        public_tags = new_tags(execute(_TAGS_QUERY, {}).get("tags") or [])
        if public_tags:
            yield public_tags
        for boards in iterate_paged(_BOARD_TAGS_QUERY, "boards"):
            board_tags = new_tags([tag for board in boards for tag in (board.get("tags") or [])])
            if board_tags:
                yield board_tags
            else:
                reach_safe_point()
        return

    if endpoint == "board_subscribers":
        for boards in iterate_paged(
            _BOARD_SUBSCRIBERS_QUERY,
            "boards",
            {"teamLimit": BOARD_TEAMS_PAGE_SIZE},
            page_size=BOARD_SUBSCRIBERS_PAGE_SIZE,
        ):
            yielded = False
            for board in boards:
                rows = _board_subscriber_rows(
                    board["id"],
                    owner_ids=_ids(board.get("owners")),
                    subscriber_ids=_ids(board.get("subscribers")),
                    team_owner_ids=board_team_ids(board["id"], "team_owners", _ids(board.get("team_owners"))),
                    team_subscriber_ids=board_team_ids(
                        board["id"], "team_subscribers", _ids(board.get("team_subscribers"))
                    ),
                )
                if rows:
                    yielded = True
                    yield rows
            if not yielded:
                reach_safe_point()
        return

    if endpoint == "board_columns":
        yield from iterate_board_children(_board_columns_query(api_version), "columns")
        return

    if endpoint == "board_groups":
        yield from iterate_board_children(_BOARD_GROUPS_QUERY, "groups")
        return

    if endpoint == "folders":
        # monday documents `workspace_ids: [null]` as the way to reach the main workspace, so walk it
        # and then each workspace explicitly instead of relying on the unfiltered query.
        workspace_ids = [ws["id"] for page in iterate_paged(_WORKSPACES_QUERY, "workspaces") for ws in page]
        seen_folder_ids: set[str] = set()
        for workspace_id in [None, *workspace_ids]:
            for folders in iterate_paged(_FOLDERS_QUERY, "folders", {"workspaceIds": [workspace_id]}):
                new_folders = [f for f in folders if f["id"] not in seen_folder_ids]
                seen_folder_ids.update(f["id"] for f in new_folders)
                if new_folders:
                    yield new_folders
        return

    if endpoint == "board_activity_logs":
        variables: dict[str, Any] = {"limit": ACTIVITY_LOGS_PAGE_SIZE}
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            variables["from"] = _format_from(db_incremental_field_last_value)

        for board_id in board_ids():
            page = 1
            while True:
                data = execute(_BOARD_ACTIVITY_LOGS_QUERY, {**variables, "boardId": [board_id], "page": page})
                boards = data.get("boards") or []
                logs = (boards[0].get("activity_logs") if boards else None) or []
                rows = [
                    {**log, "created_at": _parse_activity_log_created_at(log.get("created_at")), "_board_id": board_id}
                    for log in logs
                    if log is not None
                ]
                if rows:
                    yield rows
                if len(logs) < ACTIVITY_LOGS_PAGE_SIZE:
                    break
                page += 1
        return

    # items: fan out over every board, then walk its items_page cursor chain.
    for board_id in board_ids():
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
    api_version: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = MONDAY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            api_version=api_version,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=config.sort_mode,
    )
