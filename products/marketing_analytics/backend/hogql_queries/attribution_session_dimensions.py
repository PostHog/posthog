from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

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


def _cached_dimensions(
    modifiers: HogQLQueryModifiers, columns: set[str], job_ids: list[UUID], start: datetime, end: datetime
) -> ast.SelectQuery:
    dimensions: list[ast.Expr] = [ast.Field(chain=[column]) for column in ("period_bucket", "start_timestamp")]
    dimensions.extend(
        ast.Field(chain=[column]) if column in columns else ast.Constant(value="") for column in _DIMENSION_FIELDS
    )
    dimensions.extend(ast.Field(chain=[column]) for column in SEARCH_SESSION_COLUMNS if column in columns)
    table, timestamp = _raw_session_source(modifiers)
    # Entry properties can change after late events, including events outside the attribution window.
    updates = parse_select(
        """
        SELECT session_id_v7 AS candidate_id, max(max_inserted_at) AS last_inserted_at, min(min_timestamp) AS session_start
        FROM {table}
        WHERE {candidates} AND {timestamp} >= {start} AND {timestamp} <= {end}
        GROUP BY candidate_id
        """,
        placeholders={
            "table": ast.Field(chain=[table]),
            "candidates": ast.CompareOperation(
                left=ast.Field(chain=[table, "session_id_v7"]),
                op=ast.CompareOperationOp.GlobalIn,
                right=parse_select("SELECT session_id_v7 FROM attribution_session_identities"),
            ),
            "timestamp": timestamp,
            "start": ast.Constant(value=start - timedelta(days=SESSION_BUFFER_DAYS)),
            "end": ast.Constant(value=end + timedelta(days=SESSION_BUFFER_DAYS)),
        },
    )
    query = parse_select(
        """
        SELECT session_id_v7, argMax({dimensions}, cache.computed_at) AS latest, max(cache.computed_at) AS computed_at
        FROM posthog.web_sessions_dimensional_preaggregated AS cache
        INNER JOIN {updates} AS updates ON session_id_v7 = candidate_id
        WHERE job_id IN {jobs} AND expires_at > now()
        GROUP BY session_id_v7
        HAVING latest.2 > toDateTime(0) AND latest.2 = min(session_start)
            AND argMax(session_max_inserted_at, cache.computed_at) >= max(last_inserted_at)
        """,
        placeholders={
            "dimensions": ast.Tuple(exprs=dimensions),
            "jobs": ast.Tuple(exprs=[ast.Constant(value=str(job_id)) for job_id in job_ids]),
            "updates": updates,
        },
    )
    assert isinstance(query, ast.SelectQuery) and query.select_from is not None
    assert query.select_from.next_join is not None
    query.select_from.next_join.join_type = "GLOBAL INNER JOIN"
    return query


def session_dimensions(
    modifiers: HogQLQueryModifiers,
    columns: set[str],
    start: datetime,
    end: datetime,
    *,
    job_ids: list[UUID] | None = None,
) -> ast.SelectQuery:
    if not job_ids:
        query = parse_select(
            "SELECT session_id_v7, dimensions AS latest, computed_at FROM {live}",
            placeholders={"live": _live_dimensions(modifiers, columns, start, end)},
        )
    else:
        # New and exceptionally long sessions may be absent from a completed daily job.
        candidates = parse_select("SELECT DISTINCT session_id_v7 FROM attribution_session_identities")
        assert isinstance(candidates, ast.SelectQuery)
        candidates.where = ast.CompareOperation(
            left=ast.Field(chain=["session_id_v7"]),
            op=ast.CompareOperationOp.GlobalNotIn,
            right=parse_select("SELECT session_id_v7 FROM precomputed_search_sessions"),
        )
        query = parse_select(
            """
            WITH precomputed_search_sessions AS ({cached})
            SELECT * FROM (
                SELECT session_id_v7, latest, computed_at FROM precomputed_search_sessions
                UNION ALL
                SELECT session_id_v7, dimensions AS latest, computed_at FROM {live}
            )
            """,
            placeholders={
                "cached": _cached_dimensions(modifiers, columns, job_ids, start, end),
                "live": _raw_dimensions(modifiers, columns, start, end, candidates),
            },
        )
        assert isinstance(query, ast.SelectQuery) and query.ctes is not None
        query.ctes["precomputed_search_sessions"].materialized = True
    assert isinstance(query, ast.SelectQuery)
    return query
