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

from .marketing_sessions_precompute import MAX_PRECOMPUTED_SESSION_SECONDS, SESSION_READ_REACHBACK_DAYS

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


def _exceptional_dimensions(
    modifiers: HogQLQueryModifiers, columns: set[str], start: datetime, end: datetime
) -> ast.SelectQuery:
    is_v3 = modifiers.sessionTableVersion == SessionTableVersion.V3
    table = "raw_sessions_v3" if is_v3 else "raw_sessions"
    timestamp = (
        ast.Field(chain=[table, "session_timestamp"])
        if is_v3
        else uuid_uint128_expr_to_timestamp_expr_v2(ast.Field(chain=[table, "session_id_v7"]))
    )
    # Use the live join's ID timestamp window so both paths count the same sessions.
    bounds: dict[str, ast.Expr] = {
        "start": ast.Constant(value=start),
        "end": ast.Constant(value=end),
        "reachback": ast.Constant(value=start - timedelta(days=SESSION_READ_REACHBACK_DAYS)),
        "max_seconds": ast.Constant(value=MAX_PRECOMPUTED_SESSION_SECONDS),
    }
    # Split the duration budget around the ID timestamp to keep long sessions even when IDs and first events disagree.
    # An earlier start either has an older ID with overlapping activity or crosses the earlier limit.
    candidates = parse_select(
        """
        SELECT DISTINCT session_id_v7 FROM {table}
        WHERE {timestamp} >= {lower} AND {timestamp} <= {upper}
            AND ((max_timestamp >= {start} AND {timestamp} < {start})
                OR min_timestamp < {timestamp} - toIntervalDay({reachback_days})
                OR max_timestamp > {timestamp} + toIntervalSecond({remaining_budget}))
        """,
        placeholders={
            "table": ast.Field(chain=[table]),
            "timestamp": timestamp,
            "lower": ast.Constant(value=start - timedelta(days=SESSION_BUFFER_DAYS)),
            "upper": ast.Constant(value=end + timedelta(days=SESSION_BUFFER_DAYS)),
            "start": bounds["start"],
            "reachback_days": ast.Constant(value=SESSION_READ_REACHBACK_DAYS),
            "remaining_budget": ast.Constant(
                value=MAX_PRECOMPUTED_SESSION_SECONDS - int(timedelta(days=SESSION_READ_REACHBACK_DAYS).total_seconds())
            ),
        },
    )
    fields = [
        "$start_timestamp",
        "$end_timestamp",
        *[field for column, field in _DIMENSION_FIELDS.items() if column in columns],
    ]
    context = HogQLContext(modifiers=modifiers)
    select_sessions = select_from_sessions_table_v3 if is_v3 else select_from_sessions_table_v2
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
    source.having = parse_expr(
        """
        $end_timestamp >= {start} AND $start_timestamp <= {end}
        AND ($start_timestamp < {reachback}
            OR $end_timestamp > $start_timestamp + toIntervalSecond({max_seconds}))
        """,
        placeholders=bounds,
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
    query = parse_select(
        """
        SELECT session_id_v7, {dimensions} AS dimensions, now() AS computed_at, 1 AS source_priority
        FROM {source}
        """,
        placeholders={"source": source, "dimensions": ast.Tuple(exprs=dimensions)},
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def session_dimensions(
    modifiers: HogQLQueryModifiers, columns: set[str], job_ids: list[str], start: datetime, end: datetime
) -> ast.SelectQuery:
    # A cached session can grow after materialization, so live exceptions must replace its old dimensions.
    query = parse_select(
        """
        SELECT d.session_id_v7,
            argMax(d.dimensions, tuple(d.source_priority, d.computed_at)) AS latest,
            max(d.computed_at) AS computed_at
        FROM (
            SELECT session_id_v7,
                {cached_dimensions} AS dimensions,
                computed_at, 0 AS source_priority
            FROM posthog.web_sessions_dimensional_preaggregated
            WHERE job_id IN {jobs}
            UNION ALL
            SELECT * FROM {live}
        ) AS d
        GROUP BY d.session_id_v7
        """,
        placeholders={
            "jobs": ast.Tuple(exprs=[ast.Constant(value=job) for job in job_ids]),
            "cached_dimensions": ast.Tuple(
                exprs=[
                    ast.Field(chain=["period_bucket"]),
                    ast.Field(chain=["start_timestamp"]),
                    *[
                        ast.Field(chain=[column]) if column in columns else ast.Constant(value="")
                        for column in _DIMENSION_FIELDS
                    ],
                ]
            ),
            "live": _exceptional_dimensions(modifiers, columns, start, end),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query
