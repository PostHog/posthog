from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from posthog.schema import SessionTableVersion

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.sessions_v2 import select_from_sessions_table_v2
from posthog.hogql.database.schema.sessions_v3 import select_from_sessions_table_v3
from posthog.hogql.database.schema.util.uuid import uuid_uint128_expr_to_timestamp_expr_v2
from posthog.hogql.database.schema.util.where_clause_extractor import SESSION_BUFFER_DAYS
from posthog.hogql.parser import parse_expr, parse_select

if TYPE_CHECKING:
    from posthog.schema import HogQLQueryModifiers


_DIMENSION_FIELDS = {
    "channel_type": "$channel_type",
    "utm_source": "$entry_utm_source",
    "utm_medium": "$entry_utm_medium",
    "utm_campaign": "$entry_utm_campaign",
    "utm_term": "$entry_utm_term",
    "utm_content": "$entry_utm_content",
    "referring_domain": "$entry_referring_domain",
    "entry_pathname": "$entry_pathname",
}


SEARCH_SESSION_COLUMNS = ("entry_url", "has_gclid", "has_msclkid")


def _raw_session_source(modifiers: HogQLQueryModifiers) -> tuple[str, ast.Expr]:
    is_v3 = modifiers.sessionTableVersion == SessionTableVersion.V3
    table = "raw_sessions_v3" if is_v3 else "raw_sessions"
    timestamp = (
        ast.Field(chain=[table, "session_timestamp"])
        if is_v3
        else uuid_uint128_expr_to_timestamp_expr_v2(ast.Field(chain=[table, "session_id_v7"]))
    )
    return table, timestamp


def _raw_dimensions(
    modifiers: HogQLQueryModifiers,
    columns: set[str],
    start: datetime,
    end: datetime,
    candidates: ast.SelectQuery,
) -> ast.SelectQuery:
    table, timestamp = _raw_session_source(modifiers)
    fields = [
        "$start_timestamp",
        "$end_timestamp",
        *[field for column, field in _DIMENSION_FIELDS.items() if column in columns],
    ]
    if "entry_url" in columns or "has_msclkid" in columns:
        fields.append("$entry_current_url")
    if "has_gclid" in columns:
        fields.append("$entry_gclid")
    if "has_msclkid" in columns:
        fields.append("$entry_msclkid")
    context = HogQLContext(modifiers=modifiers)
    select_sessions = (
        select_from_sessions_table_v3
        if modifiers.sessionTableVersion == SessionTableVersion.V3
        else select_from_sessions_table_v2
    )
    source = select_sessions(
        {field: [field] for field in fields}, ast.SelectQuery(select=[ast.Constant(value=1)]), context
    )
    assert isinstance(source, ast.SelectQuery)
    # Filter IDs before merging entry properties; a HAVING alone classifies every session in the range.
    # GLOBAL IN sends the complete set to each shard without depending on session sharding.
    source.where = ast.And(
        exprs=[
            ast.CompareOperation(
                left=ast.Field(chain=[table, "session_id_v7"]), op=ast.CompareOperationOp.GlobalIn, right=candidates
            ),
            ast.CompareOperation(
                left=timestamp,
                op=ast.CompareOperationOp.GtEq,
                right=ast.Constant(value=start - timedelta(days=SESSION_BUFFER_DAYS)),
            ),
            ast.CompareOperation(
                left=timestamp,
                op=ast.CompareOperationOp.LtEq,
                right=ast.Constant(value=end + timedelta(days=SESSION_BUFFER_DAYS)),
            ),
        ]
    )
    # Empty slots preserve tuple positions without reading unused entry properties.
    dimensions: list[ast.Expr] = [
        parse_expr("toStartOfHour(toTimeZone($start_timestamp, 'UTC'))"),
        ast.Field(chain=["$start_timestamp"]),
    ]
    for column, field in _DIMENSION_FIELDS.items():
        if column not in columns:
            dimensions.append(ast.Constant(value=""))
        elif column == "channel_type":
            dimensions.append(parse_expr("if(notEmpty(ifNull($channel_type, '')), $channel_type, 'Unknown')"))
        else:
            dimensions.append(
                parse_expr("toString(ifNull({field}, ''))", placeholders={"field": ast.Field(chain=[field])})
            )
    search_dimensions = {
        "entry_url": parse_expr("cutQueryStringAndFragment(ifNull($entry_current_url, ''))"),
        "has_gclid": parse_expr("notEmpty(ifNull($entry_gclid, ''))"),
        "has_msclkid": parse_expr(
            "notEmpty(ifNull($entry_msclkid, '')) OR notEmpty(extractURLParameter(ifNull($entry_current_url, ''), 'msclkid'))"
        ),
    }
    dimensions.extend(search_dimensions[column] for column in SEARCH_SESSION_COLUMNS if column in columns)
    query = parse_select(
        """
        SELECT session_id_v7, {dimensions} AS dimensions, now() AS computed_at, 1 AS source_priority
        FROM {source}
        """,
        placeholders={"source": source, "dimensions": ast.Tuple(exprs=dimensions)},
    )
    assert isinstance(query, ast.SelectQuery)
    query.where = parse_expr("toUnixTimestamp($start_timestamp) > 0")
    return query


def _live_dimensions(
    modifiers: HogQLQueryModifiers, columns: set[str], start: datetime, end: datetime
) -> ast.SelectQuery:
    candidates = parse_select("SELECT DISTINCT session_id_v7 FROM attribution_session_identities")
    assert isinstance(candidates, ast.SelectQuery)
    return _raw_dimensions(modifiers, columns, start, end, candidates)


def session_dimensions(
    modifiers: HogQLQueryModifiers,
    columns: set[str],
    start: datetime,
    end: datetime,
) -> ast.SelectQuery:
    query = parse_select(
        "SELECT session_id_v7, dimensions AS latest, computed_at FROM {live}",
        placeholders={"live": _live_dimensions(modifiers, columns, start, end)},
    )
    assert isinstance(query, ast.SelectQuery)
    return query
