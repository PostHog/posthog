from typing import TYPE_CHECKING, Any, Optional, cast

from posthog.schema import HogQLQueryModifiers, PropertyOperator, SessionPropertyFilter, WebStatsBreakdown

from posthog.hogql import ast
from posthog.hogql.database.schema.channel_type import ChannelTypeExprs, create_channel_type_expr
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import _expr_to_compare_op, property_to_expr
from posthog.hogql.timings import HogQLTimings

from posthog.models.property import Property, ValueT

from products.web_analytics.backend.hogql_queries.first_pageview_flag import (
    SESSION_PROPERTY_TO_FIRST_PAGEVIEW,
    rewritable_session_filters,
)

if TYPE_CHECKING:
    from posthog.hogql_queries.utils.query_date_range import QueryDateRange
    from posthog.models import Team

# Flag-on, these Initial* breakdowns transparently compute first-pageview
# attribution instead of session-entry values. Filters on the session properties
# those rows produce are rewritten to match; see SESSION_PROPERTY_TO_FIRST_PAGEVIEW.
# The coverage is deliberately partial: the INITIAL_REFERRING_URL /
# INITIAL_PAGE breakdowns, the weekly digest, and every surface outside web
# analytics (saved insights, experiments, replay filters) keep entry semantics.
# The durable cross-surface fix is the raw_sessions v3 rollout.
# Note the flag only gates the remap: the FirstPageview* enum values are
# permanently live API surface and can be requested directly at 0% rollout.
INITIAL_TO_FIRST_PAGEVIEW = {
    WebStatsBreakdown.INITIAL_UTM_SOURCE: WebStatsBreakdown.FIRST_PAGEVIEW_UTM_SOURCE,
    WebStatsBreakdown.INITIAL_UTM_CAMPAIGN: WebStatsBreakdown.FIRST_PAGEVIEW_UTM_CAMPAIGN,
    WebStatsBreakdown.INITIAL_UTM_MEDIUM: WebStatsBreakdown.FIRST_PAGEVIEW_UTM_MEDIUM,
    WebStatsBreakdown.INITIAL_UTM_TERM: WebStatsBreakdown.FIRST_PAGEVIEW_UTM_TERM,
    WebStatsBreakdown.INITIAL_UTM_CONTENT: WebStatsBreakdown.FIRST_PAGEVIEW_UTM_CONTENT,
    WebStatsBreakdown.INITIAL_REFERRING_DOMAIN: WebStatsBreakdown.FIRST_PAGEVIEW_REFERRING_DOMAIN,
    WebStatsBreakdown.INITIAL_UTM_SOURCE_MEDIUM_CAMPAIGN: WebStatsBreakdown.FIRST_PAGEVIEW_UTM_SOURCE_MEDIUM_CAMPAIGN,
    WebStatsBreakdown.INITIAL_CHANNEL_TYPE: WebStatsBreakdown.FIRST_PAGEVIEW_CHANNEL_TYPE,
}

# Ordered property keys each FirstPageview* breakdown reads from the session's
# first pageview; the order defines the tuple element indexes used by
# first_pageview_prop.
FIRST_PAGEVIEW_BREAKDOWN_PROPERTIES: dict[WebStatsBreakdown, tuple[str, ...]] = {
    WebStatsBreakdown.FIRST_PAGEVIEW_UTM_SOURCE: ("utm_source",),
    WebStatsBreakdown.FIRST_PAGEVIEW_UTM_CAMPAIGN: ("utm_campaign",),
    WebStatsBreakdown.FIRST_PAGEVIEW_UTM_MEDIUM: ("utm_medium",),
    WebStatsBreakdown.FIRST_PAGEVIEW_UTM_TERM: ("utm_term",),
    WebStatsBreakdown.FIRST_PAGEVIEW_UTM_CONTENT: ("utm_content",),
    WebStatsBreakdown.FIRST_PAGEVIEW_REFERRING_DOMAIN: ("$referring_domain",),
    WebStatsBreakdown.FIRST_PAGEVIEW_UTM_SOURCE_MEDIUM_CAMPAIGN: (
        "utm_source",
        "$referring_domain",
        "utm_medium",
        "utm_campaign",
    ),
    WebStatsBreakdown.FIRST_PAGEVIEW_CHANNEL_TYPE: (
        "utm_campaign",
        "utm_medium",
        "utm_source",
        "$current_url",
        "$referring_domain",
        "gclid",
        "fbclid",
        "gad_source",
    ),
}

FIRST_PAGEVIEW_BREAKDOWNS = frozenset(FIRST_PAGEVIEW_BREAKDOWN_PROPERTIES)

PAGEVIEW_EVENTS_EXPR = "events.event IN ('$pageview', '$screen')"


def first_pageview_property_keys(breakdown: WebStatsBreakdown) -> tuple[str, ...]:
    return FIRST_PAGEVIEW_BREAKDOWN_PROPERTIES[breakdown]


def first_pageview_properties_expr(breakdown: WebStatsBreakdown) -> ast.Expr:
    """One argMinIf over a tuple: every property comes from the session's
    earliest in-range $pageview/$screen. The event filter keeps
    conversion-goal events (which share the scan) from winning the argMin,
    and the single anchor event prevents per-property NULL-skip from
    stitching values of different pageviews together."""
    return ast.Call(
        name="argMinIf",
        args=[
            ast.Tuple(
                exprs=[
                    ast.Field(chain=["events", "properties", key]) for key in first_pageview_property_keys(breakdown)
                ]
            ),
            ast.Field(chain=["events", "timestamp"]),
            parse_expr(PAGEVIEW_EVENTS_EXPR),
        ],
    )


def first_pageview_prop(breakdown: WebStatsBreakdown, key: str) -> ast.Expr:
    index = first_pageview_property_keys(breakdown).index(key) + 1
    return ast.Call(
        name="nullIf",
        args=[
            ast.Call(
                name="tupleElement",
                args=[ast.Field(chain=["first_pageview_properties"]), ast.Constant(value=index)],
            ),
            ast.Constant(value=""),
        ],
    )


def first_pageview_channel_type_expr(
    modifiers: Optional[HogQLQueryModifiers] = None,
    timings: Optional[HogQLTimings] = None,
) -> ast.Expr:
    breakdown = WebStatsBreakdown.FIRST_PAGEVIEW_CHANNEL_TYPE
    url = first_pageview_prop(breakdown, "$current_url")
    return create_channel_type_expr(
        modifiers.customChannelTypeRules if modifiers else None,
        ChannelTypeExprs(
            campaign=first_pageview_prop(breakdown, "utm_campaign"),
            medium=first_pageview_prop(breakdown, "utm_medium"),
            source=first_pageview_prop(breakdown, "utm_source"),
            url=url,
            hostname=ast.Call(name="domain", args=[url]),
            pathname=ast.Call(name="path", args=[url]),
            referring_domain=first_pageview_prop(breakdown, "$referring_domain"),
            has_gclid=ast.Call(name="isNotNull", args=[first_pageview_prop(breakdown, "gclid")]),
            has_fbclid=ast.Call(name="isNotNull", args=[first_pageview_prop(breakdown, "fbclid")]),
            gad_source=first_pageview_prop(breakdown, "gad_source"),
        ),
        timings=timings,
    )


def first_pageview_filter_value_expr(
    breakdown: WebStatsBreakdown,
    modifiers: Optional[HogQLQueryModifiers] = None,
    timings: Optional[HogQLTimings] = None,
) -> ast.Expr:
    """Value expression a rewritten session-property filter compares against.

    Must stay identical to the breakdown's own value expression, because a filter
    built from a different expression silently selects a different set of sessions
    than the row the user clicked.
    """
    if breakdown == WebStatsBreakdown.FIRST_PAGEVIEW_CHANNEL_TYPE:
        return first_pageview_channel_type_expr(modifiers=modifiers, timings=timings)

    keys = first_pageview_property_keys(breakdown)
    if len(keys) != 1:
        raise ValueError(f"{breakdown} has no single-property filter equivalent")
    return first_pageview_prop(breakdown, keys[0])


def first_pageview_session_filter_expr(
    prop: SessionPropertyFilter,
    *,
    team: "Team",
    inside_periods: ast.Expr,
    event_where: Optional[ast.Expr] = None,
    session_id_present: Optional[ast.Expr] = None,
    outer_session_id: Optional[ast.Expr] = None,
    modifiers: Optional[HogQLQueryModifiers] = None,
    timings: Optional[HogQLTimings] = None,
) -> ast.Expr:
    """Match sessions whose *first pageview* carries the filtered value.

    The stored `$entry_*` / `$channel_type` session fields come from raw_sessions
    v2, which attributes a session to its earliest event of any kind, so a
    non-pageview fired before the first pageview blanks them. A breakdown row
    computed from the first pageview therefore has no stored property that
    reproduces it, and every surface applying the row-click filter has to
    recompute the same value here.

    ClickHouse turns the plain `IN` into a `GLOBAL IN` under
    `distributed_product_mode=global`, so the id set is collected once on the
    initiator rather than re-derived per shard.
    """
    breakdown = SESSION_PROPERTY_TO_FIRST_PAGEVIEW[prop.key]
    matching_sessions = parse_select(
        """
SELECT session_id
FROM (
    SELECT
        events.$session_id AS session_id,
        {first_pageview_properties} AS first_pageview_properties
    FROM events
    WHERE and({inside_periods}, {event_where}, {session_id_present})
    GROUP BY session_id
)
WHERE {match}
        """,
        placeholders={
            "first_pageview_properties": first_pageview_properties_expr(breakdown),
            "inside_periods": inside_periods,
            "event_where": event_where if event_where is not None else parse_expr(PAGEVIEW_EVENTS_EXPR),
            # Sessionless events cannot hold a session's first pageview, and
            # letting them group under a NULL session id would build one bogus
            # bucket out of every unrelated event.
            "session_id_present": (
                session_id_present
                if session_id_present is not None
                else parse_expr("events.$session_id_uuid IS NOT NULL")
            ),
            "match": _expr_to_compare_op(
                expr=first_pageview_filter_value_expr(breakdown, modifiers=modifiers, timings=timings),
                value=cast(ValueT, prop.value),
                operator=prop.operator or PropertyOperator.EXACT,
                property=Property(
                    key=prop.key,
                    value=cast(ValueT, prop.value),
                    operator=cast(Any, prop.operator),
                    type="session",
                ),
                is_json_field=False,
                team=team,
            ),
        },
    )
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        # Unqualified by default because callers apply this against differently
        # aliased events tables (trends aliases it `e`), and the alias is not
        # knowable here. Callers whose scope has more than one table carrying a
        # session id must pass the qualified field.
        left=outer_session_id if outer_session_id is not None else ast.Field(chain=["$session_id"]),
        right=matching_sessions,
    )


def first_pageview_aware_properties_to_expr(
    properties: Any,
    *,
    team: "Team",
    modifiers: Optional[HogQLQueryModifiers],
    date_range: "QueryDateRange",
    timings: Optional[HogQLTimings] = None,
) -> ast.Expr:
    """`property_to_expr`, with session-entry attribution filters rewritten.

    Trends-backed web analytics tiles (the visitors graph, the graph view of a
    breakdown tile, web vitals) share the scene's filter list with the tiles the
    web analytics runners serve. Without this they resolve `$channel_type` and
    friends against raw_sessions v2 and select a different population than the
    row that was clicked, so one drilled-down scene shows two different totals.

    Off unless the `webAnalyticsFirstPageviewFilters` modifier is set; see
    `resolve_first_pageview_filters_modifier`.
    """
    rewritable = rewritable_session_filters(properties)
    if not (modifiers and modifiers.webAnalyticsFirstPageviewFilters) or not rewritable:
        return property_to_expr(properties, team)

    inside_periods = parse_expr(
        "timestamp >= {date_from} AND timestamp <= {date_to}",
        placeholders={"date_from": date_range.date_from_as_hogql(), "date_to": date_range.date_to_as_hogql()},
    )
    # The rewritten filters are dropped from the list rather than swapped in place
    # because callers route filters by `get_property_type`, which a raw expression
    # has no answer for; leaving them in would also apply the stored entry
    # attribution.
    rewritten_ids = {id(p) for p in rewritable}
    return property_to_expr(
        [
            *(p for p in properties if id(p) not in rewritten_ids),
            *(
                first_pageview_session_filter_expr(
                    p, team=team, inside_periods=inside_periods, modifiers=modifiers, timings=timings
                )
                for p in rewritable
            ),
        ],
        team,
    )
