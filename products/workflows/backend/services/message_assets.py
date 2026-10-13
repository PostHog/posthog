from datetime import UTC, datetime
from typing import Any, Optional, cast

from posthog.clickhouse.client.execute import sync_execute

from products.workflows.backend.facade.contracts import MessageAsset

# `latest_` prefix on the argMax aliases prevents collision with the raw column
# names in any outer WHERE - ClickHouse resolves the bare name to the aggregate
# and errors otherwise.
_COLLAPSED_AGGREGATES = """
    invocation_id,
    action_id,
    argMax(function_id, version) AS latest_function_id,
    argMax(parent_run_id, version) AS latest_parent_run_id,
    argMax(kind, version) AS latest_kind,
    argMax(distinct_id, version) AS latest_distinct_id,
    argMax(person_id, version) AS latest_person_id,
    argMax(recipient, version) AS latest_recipient,
    argMax(subject, version) AS latest_subject,
    argMax(status, version) AS latest_status,
    argMax(sent_at, version) AS latest_sent_at,
    argMax(is_deleted, version) AS latest_is_deleted
""".strip()

_OUTER_COLUMNS = """
    invocation_id,
    action_id,
    latest_function_id,
    latest_parent_run_id,
    latest_kind,
    latest_distinct_id,
    latest_person_id,
    latest_recipient,
    latest_subject,
    latest_status,
    latest_sent_at
""".strip()


def _build_asset(row: tuple) -> MessageAsset:
    return MessageAsset(
        invocation_id=row[0],
        action_id=row[1],
        function_id=row[2],
        parent_run_id=row[3],
        kind=row[4],
        distinct_id=row[5],
        person_id=row[6],
        recipient=row[7],
        subject=row[8],
        status=row[9],
        sent_at=row[10],
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def fetch_message_assets(
    team_id: int,
    function_kind: str,
    function_id: str,
    limit: int,
    offset: int = 0,
    parent_run_id: Optional[str] = None,
    action_id: Optional[str] = None,
    invocation_id: Optional[str] = None,
    distinct_id: Optional[str] = None,
    search: Optional[str] = None,
    after: Optional[datetime] = None,
    before: Optional[datetime] = None,
) -> list[MessageAsset]:
    where = [
        "team_id = %(team_id)s",
        "function_kind = %(function_kind)s",
        "function_id = %(function_id)s",
    ]
    kwargs: dict[str, Any] = {
        "team_id": team_id,
        "function_kind": function_kind,
        "function_id": function_id,
        "limit": limit,
        "offset": offset,
    }

    # Filter stable-across-versions fields pre-aggregation to hit the bloom-filter
    # skip indexes. `is_deleted` flips per version, so it's filtered post-collapse.
    if parent_run_id is not None:
        where.append("parent_run_id = %(parent_run_id)s")
        kwargs["parent_run_id"] = parent_run_id
    if action_id:
        where.append("action_id = %(action_id)s")
        kwargs["action_id"] = action_id
    if invocation_id:
        where.append("invocation_id = %(invocation_id)s")
        kwargs["invocation_id"] = invocation_id
    if distinct_id:
        where.append("distinct_id = %(distinct_id)s")
        kwargs["distinct_id"] = distinct_id
    if search:
        where.append("(recipient ILIKE %(search)s OR subject ILIKE %(search)s)")
        kwargs["search"] = f"%{_escape_like(search)}%"
    if after:
        where.append("sent_at >= toDateTime64(%(after)s, 6)")
        kwargs["after"] = after.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    if before:
        where.append("sent_at <= toDateTime64(%(before)s, 6)")
        kwargs["before"] = before.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")

    # Sends can share a sent_at down to the millisecond. The (invocation_id, action_id) tiebreak gives
    # them a stable order, so offset pages neither repeat a send nor skip one at a page boundary.
    query = f"""
        SELECT {_OUTER_COLUMNS}
        FROM (
            SELECT {_COLLAPSED_AGGREGATES}
            FROM message_assets
            WHERE {" AND ".join(where)}
            GROUP BY invocation_id, action_id
        )
        WHERE latest_is_deleted = 0
        ORDER BY latest_sent_at DESC, invocation_id, action_id
        LIMIT %(limit)s OFFSET %(offset)s
    """

    results = cast(list, sync_execute(query, kwargs))
    return [_build_asset(row) for row in results]


def fetch_message_assets_for_person(
    team_id: int,
    person_id: str,
    limit: int,
    offset: int = 0,
    after: Optional[datetime] = None,
    before: Optional[datetime] = None,
    kind: str = "email",
) -> list[MessageAsset]:
    where = [
        "team_id = %(team_id)s",
        "person_id = %(person_id)s",
        # Standalone hog_function email destinations aren't surfaced anywhere yet,
        # so this endpoint only returns workflow-step rows.
        "function_kind = 'hog_flow'",
        # One channel per call. The person view shows email and push in separate tabs, each with
        # columns shaped for its channel, so returning both from one call would misrepresent whichever
        # tab it landed in.
        "kind = %(kind)s",
    ]
    kwargs: dict[str, Any] = {
        "team_id": team_id,
        "person_id": person_id,
        "kind": kind,
        "limit": limit,
        "offset": offset,
    }
    if after:
        where.append("sent_at >= toDateTime64(%(after)s, 6)")
        kwargs["after"] = after.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    if before:
        where.append("sent_at <= toDateTime64(%(before)s, 6)")
        kwargs["before"] = before.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")

    query = f"""
        SELECT {_OUTER_COLUMNS}
        FROM (
            SELECT {_COLLAPSED_AGGREGATES}
            FROM message_assets
            WHERE {" AND ".join(where)}
            GROUP BY invocation_id, action_id
        )
        WHERE latest_is_deleted = 0
        ORDER BY latest_sent_at DESC
        LIMIT %(limit)s OFFSET %(offset)s
    """

    results = cast(list, sync_execute(query, kwargs))
    return [_build_asset(row) for row in results]


def fetch_message_asset_html(
    team_id: int,
    function_kind: str,
    function_id: str,
    invocation_id: str,
    action_id: str,
) -> Optional[str]:
    kwargs = {
        "team_id": team_id,
        "function_kind": function_kind,
        "function_id": function_id,
        "invocation_id": invocation_id,
        "action_id": action_id,
    }
    # GROUP BY so a no-match query returns zero rows - a bare aggregate would
    # return one default-valued row and the action would serve HTTP 200 + empty.
    query = """
        SELECT latest_html
        FROM (
            SELECT
                argMax(html, version) AS latest_html,
                argMax(is_deleted, version) AS latest_is_deleted
            FROM message_assets
            WHERE team_id = %(team_id)s
              AND function_kind = %(function_kind)s
              AND function_id = %(function_id)s
              AND invocation_id = %(invocation_id)s
              AND action_id = %(action_id)s
            GROUP BY invocation_id, action_id
        )
        WHERE latest_is_deleted = 0
    """

    results = cast(list, sync_execute(query, kwargs))
    if not results:
        return None
    return results[0][0]
