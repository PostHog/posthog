"""Typed queries over the intent topic rollups.

Topic totals, sparklines and similar tools read ``mcp_intent_topic_daily`` (rebuilt nightly by the intent
topics pipeline) and the Postgres topic registry. Map points and outliers read the intents called in the
window from ``mcp_intent_calls_hourly`` and their latest assignment. None of them scan the events table, so
they stay fast at any call volume; the price is that only the tool and the date range filter, not the
shared property filters.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cached_property
from typing import TYPE_CHECKING, Any, cast

import numpy as np

from posthog.schema import (
    CachedMCPIntentMapQueryResponse,
    CachedMCPIntentTopicsQueryResponse,
    CachedMCPSimilarToolsQueryResponse,
    CachedMCPToolIntentProfileQueryResponse,
    MCPIntentCoverage,
    MCPIntentDrift,
    MCPIntentFocus,
    MCPIntentMapPoint,
    MCPIntentMapQuery,
    MCPIntentMapQueryResponse,
    MCPIntentMapTopic,
    MCPIntentOutlierItem,
    MCPIntentTopicItem,
    MCPIntentTopicRef,
    MCPIntentTopicsQuery,
    MCPIntentTopicsQueryResponse,
    MCPSimilarToolItem,
    MCPSimilarToolsQuery,
    MCPSimilarToolsQueryResponse,
    MCPToolIntentProfileQuery,
    MCPToolIntentProfileQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.access_control.backend.facade.api import (
    get_restricted_properties_with_group_type_index_for_team,
    split_restricted_property_names,
)
from products.mcp_analytics.backend.hogql_queries.base import mcp_query_date_range, validate_mcp_analytics_access
from products.mcp_analytics.backend.intent_topics.metrics import drift, focus_band, focus_score
from products.mcp_analytics.backend.intent_topics.persist import latest_refit_started_at, project_team
from products.mcp_analytics.backend.intent_topics.rollups import hourly_calls_source, topic_daily_source
from products.mcp_analytics.backend.models import MCPIntentTopic

if TYPE_CHECKING:
    from posthog.models.user import User

DEFAULT_TOPICS_LIMIT = 20
DEFAULT_PROFILE_LIMIT = 5
DEFAULT_SIMILAR_LIMIT = 10
DEFAULT_MAP_LIMIT = 2000
OUTLIERS_LIMIT = 10
TOP_TOOLS_PER_TOPIC = 5
# Topics come from one clustering run per team, so a team never has this many; the limit only stops
# HogQL from applying its default of 100 rows.
MAX_TOPICS_READ = 10_000
UNASSIGNED = ""
INTENT_PROPERTY = "$mcp_intent"


def _order(name: str, direction: str = "ASC") -> ast.OrderExpr:
    return ast.OrderExpr(expr=ast.Field(chain=[name]), order="DESC" if direction == "DESC" else "ASC")


def _pct(part: float, whole: float) -> float:
    return round(100.0 * part / whole, 2) if whole else 0.0


@dataclass(frozen=True)
class QueryWindow:
    """The requested window and the window of the same number of calendar days just before it."""

    previous_from: datetime
    date_from: datetime
    date_to: datetime

    @property
    def days(self) -> list[datetime]:
        return [
            self.date_from + timedelta(days=i) for i in range((self.date_to.date() - self.date_from.date()).days + 1)
        ]


@dataclass(frozen=True)
class TopicTotals:
    calls: int
    sessions: int
    outlier_calls: int
    top_tools: list[str]


@dataclass(frozen=True)
class TopicSums:
    current: dict[str, TopicTotals]
    previous: dict[str, int]

    @property
    def calls_with_intent(self) -> int:
        return sum(totals.calls for totals in self.current.values())


@dataclass(frozen=True)
class IntentUsage:
    """One intent called in the window, with its latest assignment."""

    intent_hash: str
    intent_text: str
    x: float
    y: float
    topic_id: str
    is_outlier: bool
    distance: float
    calls: int
    tool: str


_TOPIC_SUMS_SQL = """
SELECT topic_id,
       sum(calls_now) AS calls,
       length(groupUniqArrayArray(conversations_now)) AS sessions,
       sum(outlier_calls_now) AS outlier_calls,
       sum(calls_before) AS previous_calls,
       arrayMap(t -> t.2, arraySlice(arraySort(t -> -t.1, groupArrayIf((calls_now, tool), calls_now > 0)), 1, {top_tools})) AS top_tools
FROM (
    SELECT topic_id, tool,
           sumIf(calls, day >= {date_from}) AS calls_now,
           groupUniqArrayArrayIf(conversation_hashes, day >= {date_from}) AS conversations_now,
           sumIf(outlier_calls, day >= {date_from}) AS outlier_calls_now,
           sumIf(calls, day < {date_from}) AS calls_before
    FROM {source}
    GROUP BY topic_id, tool
)
GROUP BY topic_id
LIMIT {limit}
"""

# Intents called in the window (from the hourly rollup) joined to their latest assignment. Filters on the
# assignment apply after the latest row is chosen, so an older assignment never resurfaces.
_INTENT_USAGE_SQL = """
SELECT u.intent_hash AS intent_hash, a.intent_text AS intent_text, a.x AS x, a.y AS y, a.topic_id AS topic_id,
       a.is_outlier AS is_outlier, a.distance AS distance, u.calls AS calls, u.tool AS tool
FROM (
    SELECT intent_hash, sum(tool_calls) AS calls, argMax(tool, tool_calls) AS tool
    FROM (SELECT intent_hash, tool, sum(calls) AS tool_calls FROM {usage} GROUP BY intent_hash, tool)
    GROUP BY intent_hash
) AS u
INNER JOIN (
    SELECT intent_hash,
           argMax(intent_text, timestamp) AS intent_text,
           argMax(x, timestamp) AS x,
           argMax(y, timestamp) AS y,
           argMax(ifNull(topic_id, ''), timestamp) AS topic_id,
           argMax(is_outlier, timestamp) AS is_outlier,
           argMax(distance, timestamp) AS distance,
           max(timestamp) AS assigned_at
    FROM posthog.raw_mcp_intent_assignments
    WHERE intent_hash IN (SELECT intent_hash FROM {called})
    GROUP BY intent_hash
) AS a ON u.intent_hash = a.intent_hash
WHERE {filters}
"""


class _IntentTopicsBase:
    """Shared reads for the runners: per-topic sums for the window and the previous window."""

    team: Any
    user: Any
    query: Any
    timings: Any
    modifiers: Any
    limit_context: Any

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    @cached_property
    def window(self) -> QueryWindow:
        date_from = self.query_date_range.date_from()
        date_to = self.query_date_range.date_to()
        days = (date_to.date() - date_from.date()).days + 1
        return QueryWindow(previous_from=date_from - timedelta(days=days), date_from=date_from, date_to=date_to)

    def _execute(self, query: ast.SelectQuery, name: str) -> list[Any]:
        with tags_context(product=Product.MCP_ANALYTICS, feature=Feature.QUERY, team_id=self.team.id, name=name):
            response = execute_hogql_query(
                query=query,
                team=self.team,
                user=self.user,
                context=cast(AnalyticsQueryRunner, self).build_hogql_context(),
                query_type=name,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )
        self._last_hogql = response.hogql
        return list(response.results or [])

    def _topic_sums_query(self, tool: str | None) -> ast.SelectQuery:
        return cast(
            ast.SelectQuery,
            parse_select(
                _TOPIC_SUMS_SQL,
                placeholders={
                    "date_from": ast.Constant(value=self.window.date_from.date()),
                    "source": topic_daily_source(
                        day_from=self.window.previous_from, day_to=self.window.date_to, tool=tool
                    ),
                    "top_tools": ast.Constant(value=TOP_TOOLS_PER_TOPIC),
                    "limit": ast.Constant(value=MAX_TOPICS_READ),
                },
            ),
        )

    def _topic_sums(self, tool: str | None) -> TopicSums:
        rows = self._execute(self._topic_sums_query(tool), "mcp_intent_topics_sums")
        current: dict[str, TopicTotals] = {}
        previous: dict[str, int] = {}
        for topic_id, calls, sessions, outlier_calls, previous_calls, top_tools in rows:
            topic_id = topic_id or UNASSIGNED
            if calls:
                current[topic_id] = TopicTotals(
                    calls=int(calls),
                    sessions=int(sessions),
                    outlier_calls=int(outlier_calls),
                    top_tools=list(top_tools),
                )
            if previous_calls:
                previous[topic_id] = int(previous_calls)
        return TopicSums(current=current, previous=previous)

    def _topics_by_id(self) -> dict[str, MCPIntentTopic]:
        return {str(t.pk): t for t in MCPIntentTopic.objects.unscoped().filter(team=project_team(self.team))}

    @cached_property
    def _intent_text_restricted(self) -> bool:
        # Topic labels and summaries are written from intent texts, so they follow the same restriction.
        restrictions = get_restricted_properties_with_group_type_index_for_team(user=self.user, team_id=self.team.pk)
        return INTENT_PROPERTY in split_restricted_property_names(restrictions).event

    def _label(self, topic_id: str, topic: MCPIntentTopic | None) -> str:
        if topic is None or self._intent_text_restricted:
            return f"Topic {topic_id[:8]}"
        return topic.label

    def _summary(self, topic: MCPIntentTopic | None) -> str:
        return "" if topic is None or self._intent_text_restricted else topic.summary

    def _coverage(self, sums: TopicSums) -> MCPIntentCoverage:
        with_intent = sums.calls_with_intent
        assigned = sum(totals.calls for topic_id, totals in sums.current.items() if topic_id != UNASSIGNED)
        return MCPIntentCoverage(
            calls_with_intent=with_intent, calls_assigned=assigned, assigned_pct=_pct(assigned, with_intent)
        )

    def _topic_items(self, sums: TopicSums, limit: int) -> list[MCPIntentTopicItem]:
        registry = self._topics_by_id()
        total = sums.calls_with_intent
        previous_total = sum(sums.previous.values())
        items = []
        for topic_id, totals in sums.current.items():
            if topic_id == UNASSIGNED:
                continue
            topic = registry.get(topic_id)
            share = _pct(totals.calls, total)
            previous_share = _pct(sums.previous[topic_id], previous_total) if sums.previous.get(topic_id) else None
            items.append(
                MCPIntentTopicItem(
                    topic_id=topic_id,
                    label=self._label(topic_id, topic),
                    summary=self._summary(topic),
                    calls=totals.calls,
                    sessions=totals.sessions,
                    share_pct=share,
                    previous_share_pct=previous_share,
                    trend_pp=round(share - previous_share, 2) if previous_share is not None else None,
                    outlier_calls=totals.outlier_calls,
                    top_tools=totals.top_tools,
                )
            )
        items.sort(key=lambda item: (-item.calls, item.topic_id))
        return items[:limit]

    def _intent_usage(
        self, *, tool: str | None, filters: list[ast.Expr], order_by: list[ast.OrderExpr], limit: int
    ) -> list[IntentUsage]:
        query = self._intent_usage_query(tool=tool, filters=filters)
        query.order_by = order_by
        query.limit = ast.Constant(value=limit)
        rows = self._execute(query, "mcp_intent_usage")
        return [
            IntentUsage(
                intent_hash=row[0],
                intent_text=row[1] or "",
                x=float(row[2]),
                y=float(row[3]),
                topic_id=row[4] or UNASSIGNED,
                is_outlier=bool(row[5]),
                distance=float(row[6] or 0),
                calls=int(row[7] or 0),
                tool=row[8] or "",
            )
            for row in rows
        ]

    def _intent_usage_query(self, *, tool: str | None, filters: list[ast.Expr]) -> ast.SelectQuery:
        since, until = self.window.date_from, self.window.date_to
        return cast(
            ast.SelectQuery,
            parse_select(
                _INTENT_USAGE_SQL,
                placeholders={
                    "usage": hourly_calls_source(since=since, until=until, tool=tool),
                    "called": hourly_calls_source(since=since, until=until, tool=tool),
                    "filters": ast.And(exprs=filters) if filters else ast.Constant(value=True),
                },
            ),
        )


class MCPIntentTopicsQueryRunner(_IntentTopicsBase, AnalyticsQueryRunner[MCPIntentTopicsQueryResponse]):
    query: MCPIntentTopicsQuery
    cached_response: CachedMCPIntentTopicsQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return self._topic_sums_query(self.query.toolName)

    def _calculate(self) -> MCPIntentTopicsQueryResponse:
        sums = self._topic_sums(self.query.toolName)
        items = self._topic_items(sums, self.query.limit or DEFAULT_TOPICS_LIMIT)
        return MCPIntentTopicsQueryResponse(
            results=items, coverage=self._coverage(sums), hogql=self._last_hogql, modifiers=self.modifiers
        )


class MCPToolIntentProfileQueryRunner(_IntentTopicsBase, AnalyticsQueryRunner[MCPToolIntentProfileQueryResponse]):
    query: MCPToolIntentProfileQuery
    cached_response: CachedMCPToolIntentProfileQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return self._topic_sums_query(self.query.toolName)

    def _sparklines(self, topic_ids: list[str]) -> dict[str, list[int]]:
        days = [day.date() for day in self.window.days]
        rows = self._execute(
            cast(
                ast.SelectQuery,
                parse_select(
                    """
                    SELECT topic_id, day, sum(calls) FROM {source}
                    WHERE topic_id IN {topic_ids}
                    GROUP BY topic_id, day
                    LIMIT {limit}
                    """,
                    placeholders={
                        "source": topic_daily_source(
                            day_from=self.window.date_from, day_to=self.window.date_to, tool=self.query.toolName
                        ),
                        "topic_ids": ast.Constant(value=topic_ids),
                        "limit": ast.Constant(value=len(topic_ids) * len(days)),
                    },
                ),
            ),
            "mcp_tool_intent_profile_sparklines",
        )
        by_topic: dict[str, dict[Any, int]] = defaultdict(dict)
        for topic_id, day, calls in rows:
            by_topic[topic_id][day] = int(calls)
        return {topic_id: [by_topic[topic_id].get(day, 0) for day in days] for topic_id in topic_ids}

    def _outliers(self) -> list[MCPIntentOutlierItem]:
        usage = self._intent_usage(
            tool=self.query.toolName,
            filters=[parse_expr("a.is_outlier = 1")],
            order_by=[_order("calls", "DESC"), _order("distance", "DESC"), _order("intent_hash")],
            limit=OUTLIERS_LIMIT,
        )
        return [
            MCPIntentOutlierItem(
                intent_hash=item.intent_hash,
                intent_text=item.intent_text,
                calls=item.calls,
                distance=round(item.distance, 4),
                tool=item.tool,
            )
            for item in usage
        ]

    def _calculate(self) -> MCPToolIntentProfileQueryResponse:
        sums = self._topic_sums(self.query.toolName)
        items = self._topic_items(sums, self.query.limit or DEFAULT_PROFILE_LIMIT)
        sparklines = self._sparklines([item.topic_id for item in items]) if items else {}
        for item in items:
            item.sparkline = sparklines.get(item.topic_id, [])

        calls_now = {k: v.calls for k, v in sums.current.items()}
        score = focus_score({k: v for k, v in calls_now.items() if k != UNASSIGNED})
        # Shares count every call with an intent, as the topic list does; the unassigned bucket is never listed.
        moved = drift(calls_now, sums.previous)
        registry = self._topics_by_id()
        total = sum(calls_now.values())
        previous_total = sum(sums.previous.values())

        def ref(topic_id: str) -> MCPIntentTopicRef:
            return MCPIntentTopicRef(
                topic_id=topic_id,
                label=self._label(topic_id, registry.get(topic_id)),
                calls=calls_now.get(topic_id, 0),
                share_pct=_pct(calls_now.get(topic_id, 0), total),
                previous_share_pct=_pct(sums.previous[topic_id], previous_total) if topic_id in sums.previous else None,
            )

        def refs(topic_ids: list[str]) -> list[MCPIntentTopicRef]:
            return [ref(t) for t in topic_ids if t != UNASSIGNED]

        return MCPToolIntentProfileQueryResponse(
            results=items,
            focus=MCPIntentFocus(score=round(score, 4), band=focus_band(score)),
            drift=MCPIntentDrift(
                new=refs(moved.new),
                growing=refs(moved.growing),
                shrinking=refs(moved.shrinking),
                gone=refs(moved.gone),
            ),
            outliers=self._outliers(),
            coverage=self._coverage(sums),
            hogql=self._last_hogql,
            modifiers=self.modifiers,
        )


class MCPSimilarToolsQueryRunner(_IntentTopicsBase, AnalyticsQueryRunner[MCPSimilarToolsQueryResponse]):
    query: MCPSimilarToolsQuery
    cached_response: CachedMCPSimilarToolsQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        # One row per tool, most called first, so a server with more tools than the limit drops the least used.
        return parse_select(
            """
            SELECT tool, groupArray(topic_id), groupArray(calls)
            FROM (
                SELECT tool, topic_id, sum(calls) AS calls FROM {source}
                WHERE topic_id != ''
                GROUP BY tool, topic_id
            )
            GROUP BY tool
            ORDER BY sum(calls) DESC, tool
            LIMIT {limit}
            """,
            placeholders={
                "source": topic_daily_source(day_from=self.window.date_from, day_to=self.window.date_to),
                "limit": ast.Constant(value=MAX_SELECT_RETURNED_ROWS),
            },
        )

    def _calculate(self) -> MCPSimilarToolsQueryResponse:
        rows = self._execute(cast(ast.SelectQuery, self.to_query()), "mcp_similar_tools")
        shares: dict[str, dict[str, int]] = {
            tool: {topic_id: int(calls) for topic_id, calls in zip(topic_ids, calls_per_topic)}
            for tool, topic_ids, calls_per_topic in rows
        }
        target = shares.get(self.query.toolName)
        if not target:
            return MCPSimilarToolsQueryResponse(results=[], hogql=self._last_hogql, modifiers=self.modifiers)

        topic_index = {topic_id: i for i, topic_id in enumerate({t for per_tool in shares.values() for t in per_tool})}

        def vector(per_tool: dict[str, int]) -> np.ndarray:
            v = np.zeros(len(topic_index))
            total = sum(per_tool.values())
            for topic_id, calls in per_tool.items():
                v[topic_index[topic_id]] = calls / total
            return v

        target_vector = vector(target)
        registry = self._topics_by_id()
        results = []
        for tool, per_tool in shares.items():
            if tool == self.query.toolName:
                continue
            other = vector(per_tool)
            denominator = float(np.linalg.norm(target_vector) * np.linalg.norm(other))
            similarity = float(target_vector @ other) / denominator if denominator else 0.0
            if similarity <= 0:
                continue
            shared = sorted(
                (topic_id for topic_id in per_tool if topic_id in target),
                key=lambda topic_id: -min(target_vector[topic_index[topic_id]], other[topic_index[topic_id]]),
            )
            results.append(
                MCPSimilarToolItem(
                    tool=tool,
                    similarity=round(similarity, 4),
                    calls=sum(per_tool.values()),
                    shared_topics=[self._label(t, registry.get(t)) for t in shared[:TOP_TOOLS_PER_TOPIC]],
                )
            )
        results.sort(key=lambda item: (-item.similarity, -item.calls, item.tool))
        return MCPSimilarToolsQueryResponse(
            results=results[: self.query.limit or DEFAULT_SIMILAR_LIMIT],
            hogql=self._last_hogql,
            modifiers=self.modifiers,
        )


class MCPIntentMapQueryRunner(_IntentTopicsBase, AnalyticsQueryRunner[MCPIntentMapQueryResponse]):
    query: MCPIntentMapQuery
    cached_response: CachedMCPIntentMapQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    def _point_filters(self) -> list[ast.Expr]:
        filters: list[ast.Expr] = []
        # Each refit fits a new 2D basis and re-assigns only recent vectors; older positions use an older basis.
        basis_since = latest_refit_started_at(self.team)
        if basis_since is not None:
            filters.append(
                parse_expr("a.assigned_at >= {basis_since}", {"basis_since": ast.Constant(value=basis_since)})
            )
        if self.query.topicId:
            filters.append(parse_expr("a.topic_id = {topic_id}", {"topic_id": ast.Constant(value=self.query.topicId)}))
        if self.query.bounds:
            bounds = self.query.bounds
            filters.append(
                parse_expr(
                    "a.x >= {x_min} AND a.x <= {x_max} AND a.y >= {y_min} AND a.y <= {y_max}",
                    {
                        "x_min": ast.Constant(value=bounds.x_min),
                        "x_max": ast.Constant(value=bounds.x_max),
                        "y_min": ast.Constant(value=bounds.y_min),
                        "y_max": ast.Constant(value=bounds.y_max),
                    },
                )
            )
        return filters

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return self._intent_usage_query(tool=self.query.toolName, filters=self._point_filters())

    def _calculate(self) -> MCPIntentMapQueryResponse:
        usage = self._intent_usage(
            tool=self.query.toolName,
            filters=self._point_filters(),
            order_by=[_order("calls", "DESC"), _order("intent_hash")],
            limit=self.query.limit or DEFAULT_MAP_LIMIT,
        )
        points = [
            MCPIntentMapPoint(
                intent_hash=item.intent_hash,
                intent_text=item.intent_text,
                x=item.x,
                y=item.y,
                topic_id=item.topic_id or None,
                is_outlier=item.is_outlier,
                calls=item.calls,
                tool=item.tool,
            )
            for item in usage
        ]
        total_rows = self._execute(
            cast(
                ast.SelectQuery,
                parse_select("SELECT count() FROM {points}", placeholders={"points": self.to_query()}),
            ),
            "mcp_intent_map_total",
        )
        total_points = int(total_rows[0][0]) if total_rows else 0

        sums = self._topic_sums(self.query.toolName)
        total_calls = sums.calls_with_intent
        registry = self._topics_by_id()
        topics = [
            MCPIntentMapTopic(
                topic_id=topic_id,
                label=self._label(topic_id, topic),
                summary=self._summary(topic),
                x=topic.centroid_x,
                y=topic.centroid_y,
                calls=sums.current[topic_id].calls,
                share_pct=_pct(sums.current[topic_id].calls, total_calls),
            )
            for topic_id, topic in registry.items()
            if topic_id in sums.current and (not self.query.topicId or topic_id == self.query.topicId)
        ]
        topics.sort(key=lambda t: -t.calls)
        return MCPIntentMapQueryResponse(
            results=points, topics=topics, total_points=total_points, hogql=self._last_hogql, modifiers=self.modifiers
        )
