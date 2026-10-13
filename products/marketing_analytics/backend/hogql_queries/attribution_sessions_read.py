"""Share session dimensions and current event identities across attribution calculations.

Stored person IDs can outlive a merge, so identity always comes from events.
"""

import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Optional

import structlog

from posthog.schema import MarketingAnalyticsAttributionBreakdown, SessionTableVersion

from posthog.hogql import ast
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.transforms.preaggregated_table_transformation import is_integer_timezone
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.access_control.backend.facade.api import team_has_property_access_rules

from .attribution_base import MAX_CONVERSIONS_PER_PERSON, MAX_TOUCHPOINTS_PER_PERSON, PERSON_CONVERSION_COUNT
from .attribution_session_dimensions import SEARCH_SESSION_COLUMNS, session_dimensions
from .constants import UNKNOWN_CHANNEL
from .session_breakdown_base import UNATTRIBUTED_SESSION_VALUES

if TYPE_CHECKING:
    from posthog.schema import HogQLQueryModifiers

    from posthog.models.team import Team

    from .attribution_base import AttributionQueryRunnerBase

logger = structlog.get_logger(__name__)

_SESSIONS_CTE = "resolved_cached_sessions"
_CONVERSIONS_CTE = "cached_session_conversions"
MAX_DISPLAY_DAYS = int(os.getenv("MARKETING_SESSIONS_PRECOMPUTE_WINDOW_DAYS", "90"))

BREAKDOWN_COLUMNS: dict[MarketingAnalyticsAttributionBreakdown, str] = {
    MarketingAnalyticsAttributionBreakdown.CHANNEL: "channel_type",
    MarketingAnalyticsAttributionBreakdown.SOURCE: "utm_source",
    MarketingAnalyticsAttributionBreakdown.CAMPAIGN: "utm_campaign",
    MarketingAnalyticsAttributionBreakdown.MEDIUM: "utm_medium",
    MarketingAnalyticsAttributionBreakdown.CONTENT: "utm_content",
    MarketingAnalyticsAttributionBreakdown.TERM: "utm_term",
    MarketingAnalyticsAttributionBreakdown.REFERRING_DOMAIN: "referring_domain",
    MarketingAnalyticsAttributionBreakdown.LANDING_PAGE: "entry_pathname",
}


def _field(name: str) -> ast.Expr:
    return ast.Field(chain=[name])


def _session_table_version(modifiers: "HogQLQueryModifiers") -> SessionTableVersion:
    version = modifiers.sessionTableVersion
    return SessionTableVersion.V2 if version is None or version == SessionTableVersion.AUTO else version


def _session_modifiers_reason(runner: "AttributionQueryRunnerBase") -> Optional[str]:
    default_modifiers = create_default_modifiers_for_team(runner.team)
    modifiers = runner.modifiers or default_modifiers
    if (modifiers.customChannelTypeRules or []) != (default_modifiers.customChannelTypeRules or []):
        return "custom_channel_rules_mismatch"
    if modifiers.convertToProjectTimezone is False:
        return "project_timezone_disabled"
    version = _session_table_version(modifiers)
    if version == SessionTableVersion.V1 or version != _session_table_version(default_modifiers):
        return "session_table_version_mismatch"
    if version == SessionTableVersion.V2 and modifiers.sessionsV2JoinMode != default_modifiers.sessionsV2JoinMode:
        return "session_join_mode_mismatch"
    return None


class _SessionConversionVisitor(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.depends_on_sessions = False

    def visit_field(self, node: ast.Field) -> None:
        if any(part in {"session", "sessions", "raw_sessions", "raw_sessions_v3"} for part in node.chain):
            self.depends_on_sessions = True
        super().visit_field(node)

    def visit_call(self, node: ast.Call) -> None:
        # matchesAction expands after this eligibility check and can introduce session filters.
        if node.name == "matchesAction":
            self.depends_on_sessions = True
        super().visit_call(node)


def earliest_session_start(team: "Team", end: datetime) -> datetime:
    # Relative display ranges start at local midnight; attribution lookback uses elapsed UTC seconds.
    display_start = end.astimezone(team.timezone_info).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=MAX_DISPLAY_DAYS
    )
    return display_start.astimezone(UTC) - timedelta(days=team.marketing_analytics_config.attribution_window_days)


def ineligible_reason(runner: "AttributionQueryRunnerBase", date_range: QueryDateRange) -> Optional[str]:
    """Why this query cannot use shared live session resolution, or None if it can.

    A reason string rather than a bool, so the caller can label the fallback counter: these carry very
    different weight, and an unlabeled counter would blur permanent and transient apart.
    """
    if reason := _session_modifiers_reason(runner):
        return reason

    conversion = _SessionConversionVisitor()
    conversion.visit(runner.conversion_condition)
    if conversion.depends_on_sessions:
        # The separate conversion scan has narrower session-ID bounds than the legacy combined scan.
        return "session_filtered_conversion_goal"

    if not is_integer_timezone(runner.team.timezone):
        # `period_bucket` is an hourly UTC bucket, so a half-hour-offset team's midnight lands
        # mid-bucket and moves sessions across each edge.
        return "non_integer_timezone"

    # Live date filters omit the UTC offset, so repeated local hours can resolve to another instant.
    if any(
        bound.replace(fold=0).utcoffset() != bound.replace(fold=1).utcoffset()
        for bound in (date_range.date_from(), date_range.date_to())
    ):
        return "ambiguous_date_boundary"

    if team_has_property_access_rules(team_id=runner.team.id):
        # Shared session dimensions cannot honor per-user property restrictions.
        return "property_access_controlled"

    if runner._test_account_conditions():
        return "test_account_filters"

    read = window(runner, date_range)
    if read.start < earliest_session_start(runner.team, read.end):
        return "window_over_max"

    return None


@frozen
class ReadWindow:
    """The span of session activity a query reads: its display range extended back by the attribution
    window, in UTC. Bounds include whole seconds to match conversion date filters."""

    start: datetime
    end: datetime


def window(runner: "AttributionQueryRunnerBase", date_range: QueryDateRange) -> ReadWindow:
    """Converted before subtracting: subtracting from a team-local aware datetime is wall-clock
    arithmetic, which lands an hour away from the credit side across a DST transition.
    """
    return ReadWindow(
        start=date_range.date_from().astimezone(UTC).replace(microsecond=0)
        - timedelta(seconds=runner.attribution_window_seconds),
        end=date_range.date_to().astimezone(UTC).replace(microsecond=999999),
    )


def _eligible(runner: "AttributionQueryRunnerBase", date_range: QueryDateRange) -> bool:
    # Reach and credit must share a source so their conversion-rate denominator stays consistent.
    if runner._live_session_resolution_eligible is None:
        try:
            reason = ineligible_reason(runner, date_range)
            runner._live_session_resolution_eligible = reason is None
            if reason is not None:
                logger.info("attribution_live_session_resolution_ineligible", team_id=runner.team.pk, reason=reason)
        except Exception:
            logger.exception("attribution_live_session_resolution_failed", team_id=runner.team.pk)
            runner._live_session_resolution_eligible = False
    return runner._live_session_resolution_eligible


def _session_identities(start: datetime, end: datetime) -> ast.SelectQuery:
    query = parse_select(
        """
            SELECT events.$session_id_uuid AS session_id_v7, events.person_id AS person_id,
                min(events.timestamp) AS min_event_timestamp,
                max(events.timestamp) AS max_event_timestamp,
                count() AS pageview_count
            FROM events
            WHERE events.event = '$pageview'
                AND events.timestamp >= {start} AND events.timestamp <= {end}
            GROUP BY session_id_v7, person_id
        """,
        placeholders={"start": ast.Constant(value=start), "end": ast.Constant(value=end)},
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _read_sessions(dimensions: ast.SelectQuery, columns: set[str]) -> ast.SelectQuery:
    query = parse_select(
        """
        WITH dimensions AS (SELECT * FROM {dimensions}), identities AS ({identities})
        SELECT i.session_id_v7, i.person_id, i.min_event_timestamp, i.max_event_timestamp, i.pageview_count,
            d.latest.1 AS period_bucket, d.latest.2 AS start_timestamp, d.latest.3 AS channel_type,
            d.latest.4 AS utm_source, d.latest.5 AS utm_medium, d.latest.6 AS utm_campaign,
            d.latest.7 AS utm_term, d.latest.8 AS utm_content, d.latest.9 AS referring_domain,
            d.latest.10 AS entry_pathname, d.computed_at
        FROM identities AS i
        INNER JOIN dimensions AS d ON i.session_id_v7 = d.session_id_v7
        """,
        placeholders={
            "dimensions": dimensions,
            "identities": parse_select("SELECT * FROM attribution_session_identities"),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    for index, column in enumerate((column for column in SEARCH_SESSION_COLUMNS if column in columns), start=11):
        query.select.append(
            ast.Alias(alias=column, expr=ast.TupleAccess(tuple=ast.Field(chain=["d", "latest"]), index=index))
        )
    return query


def _scope(read: ReadWindow) -> list[ast.Expr]:
    """Scope to the window by event time.

    The live path keeps a session whose events fall in the window and then reports its start as the
    touchpoint time, so a session that opened before the window still counts. Bounding by
    `start_timestamp` dropped exactly those, which moved first-touch credit and shrank the reach
    denominator.
    """
    return [
        ast.CompareOperation(
            left=_field("max_event_timestamp"), op=ast.CompareOperationOp.GtEq, right=ast.Constant(value=read.start)
        ),
        ast.CompareOperation(
            left=_field("min_event_timestamp"), op=ast.CompareOperationOp.LtEq, right=ast.Constant(value=read.end)
        ),
    ]


_EXCLUDED_CHANNEL = "excl_channel_type"
_EXCLUDED_BREAKDOWN = "excl_breakdown"


def _exclusion_columns(runner: "AttributionQueryRunnerBase") -> list[ast.Expr]:
    """Exclusions use the dimensions already resolved by the shared sessions CTE."""
    columns: list[ast.Expr] = []
    if runner.query.excludeDirectTraffic:
        columns.append(
            ast.Alias(
                alias=_EXCLUDED_CHANNEL,
                expr=_field("channel_type"),
            )
        )
    if runner.query.excludeUnattributed:
        columns.append(
            ast.Alias(
                alias=_EXCLUDED_BREAKDOWN,
                expr=_field(BREAKDOWN_COLUMNS[runner.breakdown]),
            )
        )
    return columns


def _exclusions(runner: "AttributionQueryRunnerBase", table_alias: Optional[str] = None) -> list[ast.Expr]:
    """Mirror of the exclusion half of `_touchpoint_condition`, against the collapsed columns."""

    def resolved(alias: str) -> ast.Field:
        return ast.Field(chain=[table_alias, alias] if table_alias else [alias])

    conditions: list[ast.Expr] = []
    if runner.query.excludeDirectTraffic:
        conditions.append(
            ast.CompareOperation(
                left=resolved(_EXCLUDED_CHANNEL),
                op=ast.CompareOperationOp.NotEq,
                right=ast.Constant(value="Direct"),
            )
        )
    if runner.query.excludeUnattributed:
        # Judged on the raw column rather than the display expression, so a friendly fallback label
        # cannot smuggle an empty value back in.
        field = resolved(_EXCLUDED_BREAKDOWN)
        conditions.append(
            ast.Call(name="notEmpty", args=[ast.Call(name="ifNull", args=[field, ast.Constant(value="")])])
        )
        for sentinel in UNATTRIBUTED_SESSION_VALUES.get(runner.breakdown, ()):
            conditions.append(
                ast.CompareOperation(left=field, op=ast.CompareOperationOp.NotEq, right=ast.Constant(value=sentinel))
            )
    return conditions


def _breakdown_expr(runner: "AttributionQueryRunnerBase") -> ast.Expr:
    resolved = runner.resolved_breakdown_expr()
    if resolved is not None:
        return resolved
    column = _field(BREAKDOWN_COLUMNS[runner.breakdown])
    if runner.breakdown == MarketingAnalyticsAttributionBreakdown.CHANNEL:
        return runner._non_empty_or(column, UNKNOWN_CHANNEL)
    if runner.breakdown == MarketingAnalyticsAttributionBreakdown.SOURCE:
        return runner._normalized_source_expr(column)
    if runner.breakdown == MarketingAnalyticsAttributionBreakdown.CAMPAIGN:
        return runner._normalized_campaign_expr(column, source_field=_field("utm_source"))
    return ast.Call(name="toString", args=[ast.Call(name="ifNull", args=[column, ast.Constant(value="")])])


def build_reach(runner: "AttributionQueryRunnerBase", date_range: QueryDateRange) -> Optional[ast.SelectQuery]:
    if not _eligible(runner, date_range):
        return None
    read = window(runner, date_range)
    per_session = ast.SelectQuery(
        select=[
            ast.Alias(alias="person_id", expr=_field("person_id")),
            ast.Alias(
                alias="breakdown_value",
                expr=_breakdown_expr(runner),
            ),
            *_exclusion_columns(runner),
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=[_SESSIONS_CTE]), alias="cached_sessions"),
        where=ast.And(exprs=_scope(read)),
    )
    exclusions = _exclusions(runner, table_alias="s")
    return ast.SelectQuery(
        select=[
            ast.Field(chain=["s", "breakdown_value"]),
            ast.Alias(alias="visitors", expr=ast.Call(name="uniq", args=[ast.Field(chain=["s", "person_id"])])),
        ],
        select_from=ast.JoinExpr(table=per_session, alias="s"),
        where=ast.And(exprs=exclusions) if exclusions else None,
        group_by=[ast.Field(chain=["s", "breakdown_value"])],
    )


def _conversions_per_person(runner: "AttributionQueryRunnerBase", date_range: QueryDateRange) -> ast.SelectQuery:
    """Conversions per converting person, straight off events. Conversions are events, not sessions,
    so this side stays on `events` while the touchpoint side resolves session dimensions."""
    conversions: ast.Expr = ast.Call(
        name="groupArray",
        args=[
            ast.Tuple(
                exprs=[
                    ast.Call(name="toUnixTimestamp", args=[ast.Field(chain=["events", "timestamp"])]),
                    runner._conversion_value_expr(),
                ]
            )
        ],
    )
    # Counted before the array is capped: the footer reports "N of M" exactly, so a conversion the cap
    # drops has to show up as unattributed rather than vanish from M.
    conversion_count: ast.Expr = ast.Call(name="count", args=[])
    if not runner.allows_multiple_conversions_per_visitor:
        conversions = ast.Call(
            name="arraySlice",
            args=[ast.Call(name="arraySort", args=[conversions]), ast.Constant(value=1), ast.Constant(value=1)],
        )
        conversion_count = ast.Constant(value=1)
    else:
        # The same ceiling the legacy path applies; otherwise the downstream ARRAY JOINs multiply without bound.
        conversions = ast.Call(
            name="arraySlice",
            args=[
                ast.Call(name="arraySort", args=[conversions]),
                ast.Constant(value=-MAX_CONVERSIONS_PER_PERSON),
            ],
        )

    def bound(fn: str) -> ast.Expr:
        return ast.Call(
            name=fn, args=[ast.Call(name="toUnixTimestamp", args=[ast.Field(chain=["events", "timestamp"])])]
        )

    return ast.SelectQuery(
        select=[
            ast.Alias(alias="conv_person_id", expr=ast.Field(chain=["events", "person_id"])),
            ast.Alias(alias="conversions", expr=conversions),
            ast.Alias(alias=PERSON_CONVERSION_COUNT, expr=conversion_count),
            ast.Alias(alias="first_conversion", expr=bound("min")),
            ast.Alias(alias="last_conversion", expr=bound("max")),
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=ast.And(
            exprs=[
                runner.conversion_condition,
                *runner._event_date_conditions(date_range),
            ]
        ),
        group_by=[ast.Field(chain=["events", "person_id"])],
    )


def session_ctes(runner: "AttributionQueryRunnerBase", date_range: QueryDateRange) -> dict[str, ast.CTE]:
    if not runner.config.live_session_resolution_enabled:
        return {}
    if not _eligible(runner, date_range):
        return {}
    read = window(runner, date_range)
    columns = {BREAKDOWN_COLUMNS[runner.breakdown]} | runner.additional_session_columns()
    if runner.breakdown == MarketingAnalyticsAttributionBreakdown.CAMPAIGN:
        columns.add("utm_source")
    if runner.query.excludeDirectTraffic:
        columns.add("channel_type")
    dimensions = session_dimensions(
        runner.modifiers or create_default_modifiers_for_team(runner.team),
        columns,
        read.start,
        read.end,
    )
    sessions = _read_sessions(dimensions, columns)
    ctes: dict[str, ast.CTE] = {}
    ctes["attribution_session_identities"] = ast.CTE(
        name="attribution_session_identities",
        expr=_session_identities(read.start, read.end),
        cte_type="subquery",
        materialized=True,
    )
    # Reach and credit share the event scan; conversion bounds share the revenue aggregation.
    ctes[_SESSIONS_CTE] = ast.CTE(
        name=_SESSIONS_CTE,
        expr=sessions,
        cte_type="subquery",
        materialized=True,
    )
    ctes[_CONVERSIONS_CTE] = ast.CTE(
        name=_CONVERSIONS_CTE,
        expr=_conversions_per_person(runner, date_range),
        cte_type="subquery",
        materialized=True,
    )
    return ctes


def build_person_arrays(runner: "AttributionQueryRunnerBase", date_range: QueryDateRange) -> Optional[ast.SelectQuery]:
    """One row per converting person, with touchpoints from the shared session resolution."""
    if not _eligible(runner, date_range):
        return None
    read = window(runner, date_range)

    conv = parse_select("SELECT * FROM cached_session_conversions")
    converters = parse_select(
        "SELECT conv_person_id, first_conversion, last_conversion FROM cached_session_conversions"
    )
    session_start = ast.Call(name="toUnixTimestamp", args=[_field("start_timestamp")])
    # A touchpoint outside [first conversion - window, last conversion] cannot be credited by any of
    # this person's conversions. In single-conversion mode only the first one is kept, so nothing
    # after it is creditable either.
    upper = "last_conversion" if runner.allows_multiple_conversions_per_visitor else "first_conversion"

    conditions = _scope(read)
    # Event and session replicas can lag independently; credit still requires a pageview in the person's window.
    conditions.append(
        ast.CompareOperation(
            left=ast.Call(name="toUnixTimestamp", args=[_field("max_event_timestamp")]),
            op=ast.CompareOperationOp.GtEq,
            right=ast.ArithmeticOperation(
                left=ast.Field(chain=["conv", "first_conversion"]),
                op=ast.ArithmeticOperationOp.Sub,
                right=ast.Constant(value=runner.attribution_window_seconds),
            ),
        )
    )

    # One conversion-bounds row per person preserves the CTE's unique session/person pairs.
    per_session = ast.SelectQuery(
        select=[
            ast.Alias(alias="person_id", expr=ast.Field(chain=["conv", "conv_person_id"])),
            ast.Alias(alias="session_ts", expr=session_start),
            ast.Alias(
                alias="session_dim",
                expr=_breakdown_expr(runner),
            ),
            ast.Alias(
                alias="first_conversion",
                expr=ast.Field(chain=["conv", "first_conversion"]),
            ),
            ast.Alias(alias="upper_bound", expr=ast.Field(chain=["conv", upper])),
            *_exclusion_columns(runner),
        ],
        select_from=ast.JoinExpr(
            table=ast.Field(chain=[_SESSIONS_CTE]),
            alias="cached_sessions",
            next_join=ast.JoinExpr(
                join_type="INNER JOIN",
                table=converters,
                alias="conv",
                constraint=ast.JoinConstraint(
                    expr=ast.CompareOperation(
                        left=_field("person_id"),
                        op=ast.CompareOperationOp.Eq,
                        right=ast.Field(chain=["conv", "conv_person_id"]),
                    ),
                    constraint_type="ON",
                ),
            ),
        ),
        where=ast.And(exprs=conditions),
    )

    # Creditability is judged on the collapsed start, so a superseded row cannot decide it.
    touchpoints = ast.SelectQuery(
        select=[
            ast.Alias(alias="person_id", expr=ast.Field(chain=["d", "person_id"])),
            ast.Alias(
                alias="touchpoints",
                expr=ast.Call(
                    name="arraySlice",
                    args=[
                        ast.Call(
                            name="arraySort",
                            args=[
                                ast.Call(
                                    name="groupUniqArray",
                                    args=[
                                        ast.Tuple(
                                            exprs=[
                                                ast.Field(chain=["d", "session_ts"]),
                                                ast.Field(chain=["d", "session_dim"]),
                                            ]
                                        )
                                    ],
                                )
                            ],
                        ),
                        ast.Constant(value=-MAX_TOUCHPOINTS_PER_PERSON),
                    ],
                ),
            ),
        ],
        select_from=ast.JoinExpr(table=per_session, alias="d"),
        where=ast.And(
            exprs=[
                ast.CompareOperation(
                    left=ast.Field(chain=["d", "session_ts"]),
                    op=ast.CompareOperationOp.GtEq,
                    right=ast.ArithmeticOperation(
                        left=ast.Field(chain=["d", "first_conversion"]),
                        op=ast.ArithmeticOperationOp.Sub,
                        right=ast.Constant(value=runner.attribution_window_seconds),
                    ),
                ),
                ast.CompareOperation(
                    left=ast.Field(chain=["d", "session_ts"]),
                    op=ast.CompareOperationOp.LtEq,
                    right=ast.Field(chain=["d", "upper_bound"]),
                ),
                *_exclusions(runner, table_alias="d"),
            ]
        ),
        group_by=[ast.Field(chain=["d", "person_id"])],
    )

    return ast.SelectQuery(
        select=[
            ast.Alias(alias="person_id", expr=ast.Field(chain=["c", "conv_person_id"])),
            ast.Field(chain=["c", "conversions"]),
            ast.Field(chain=["c", PERSON_CONVERSION_COUNT]),
            ast.Alias(alias="touchpoints", expr=ast.Field(chain=["t", "touchpoints"])),
        ],
        select_from=ast.JoinExpr(
            table=conv,
            alias="c",
            next_join=ast.JoinExpr(
                join_type="LEFT JOIN",
                table=touchpoints,
                alias="t",
                constraint=ast.JoinConstraint(
                    expr=ast.CompareOperation(
                        left=ast.Field(chain=["c", "conv_person_id"]),
                        op=ast.CompareOperationOp.Eq,
                        right=ast.Field(chain=["t", "person_id"]),
                    ),
                    constraint_type="ON",
                ),
            ),
        ),
        where=ast.CompareOperation(
            left=ast.Call(name="length", args=[ast.Field(chain=["c", "conversions"])]),
            op=ast.CompareOperationOp.Gt,
            right=ast.Constant(value=0),
        ),
    )
