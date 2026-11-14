"""Typed queries over the intent topic rollups.

All four read ``mcp_intent_topic_daily`` (built nightly by the intent topics pipeline) and the
Postgres topic registry, plus ``mcp_intent_assignments`` for outliers and map points. None of them
scan the events table, so they stay fast at any call volume; the price is that only the tool and
the date range filter, not the shared property filters.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from functools import cached_property
from typing import TYPE_CHECKING, Any

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
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.mcp_analytics.backend.hogql_queries.base import mcp_query_date_range, validate_mcp_analytics_access
from products.mcp_analytics.backend.intent_topics.metrics import drift, focus_band, focus_score
from products.mcp_analytics.backend.models import MCPIntentTopic

if TYPE_CHECKING:
    from posthog.models.user import User

DEFAULT_TOPICS_LIMIT = 20
DEFAULT_PROFILE_LIMIT = 5
DEFAULT_SIMILAR_LIMIT = 10
DEFAULT_MAP_LIMIT = 2000
MAX_MAP_LIMIT = 5000
OUTLIERS_LIMIT = 10
TOP_TOOLS_PER_TOPIC = 5
UNASSIGNED = ""

# ReplacingMergeTree keeps duplicates until parts merge, so every read dedupes on the sort key first.
_DAILY_DEDUPED_SQL = """
SELECT day, tool, topic_id,
       argMax(calls, inserted_at) AS calls,
       argMax(sessions, inserted_at) AS sessions,
       argMax(outlier_calls, inserted_at) AS outlier_calls,
       argMax(intents, inserted_at) AS intents
FROM mcp_intent_topic_daily
WHERE day >= {day_from} AND day <= {day_to} {tool_filter}
GROUP BY day, tool, topic_id
"""


def _daily_source(day_from: datetime, day_to: datetime, tool: str | None) -> ast.SelectQuery:
    tool_filter = "AND tool = {tool}" if tool else ""
    return parse_select(
        _DAILY_DEDUPED_SQL.replace("{tool_filter}", tool_filter),
        placeholders={
            "day_from": ast.Constant(value=day_from.date()),
            "day_to": ast.Constant(value=day_to.date()),
            **({"tool": ast.Constant(value=tool)} if tool else {}),
        },
    )


def _pct(part: float, whole: float) -> float:
    return round(100.0 * part / whole, 2) if whole else 0.0


class _IntentTopicsBase:
    """Shared reads for the runners: per-topic sums for the window and the previous window."""

    team: Any
    query: Any
    timings: Any
    modifiers: Any
    limit_context: Any

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    @property
    def _window(self) -> tuple[datetime, datetime, datetime]:
        date_from = self.query_date_range.date_from()
        date_to = self.query_date_range.date_to()
        previous_from = date_from - (date_to - date_from) - timedelta(days=1)
        return previous_from, date_from, date_to

    def _execute(self, query: ast.SelectQuery, name: str) -> list[Any]:
        with tags_context(product=Product.MCP_ANALYTICS, feature=Feature.QUERY, team_id=self.team.id, name=name):
            response = execute_hogql_query(
                query=query,
                team=self.team,
                query_type=name,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )
        self._last_hogql = response.hogql
        return list(response.results or [])

    def _topic_sums(
        self, tool: str | None
    ) -> tuple[dict[str, dict[str, int]], dict[str, int], dict[str, dict[str, int]]]:
        """Returns (current per topic {calls, sessions, outlier_calls}, previous calls per topic, tool calls per topic)."""
        previous_from, date_from, date_to = self._window
        rows = self._execute(
            parse_select(
                """
                SELECT topic_id, tool,
                       sumIf(calls, day >= {date_from}) AS calls_now,
                       sumIf(sessions, day >= {date_from}) AS sessions_now,
                       sumIf(outlier_calls, day >= {date_from}) AS outlier_calls_now,
                       sumIf(calls, day < {date_from}) AS calls_before
                FROM {source}
                GROUP BY topic_id, tool
                """,
                placeholders={
                    "date_from": ast.Constant(value=date_from.date()),
                    "source": _daily_source(previous_from, date_to, tool),
                },
            ),
            "mcp_intent_topics_sums",
        )
        current: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "sessions": 0, "outlier_calls": 0})
        previous: dict[str, int] = defaultdict(int)
        tools: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for topic_id, tool_name, calls, sessions, outlier_calls, previous_calls in rows:
            topic_id = topic_id or UNASSIGNED
            if calls:
                current[topic_id]["calls"] += int(calls)
                current[topic_id]["sessions"] += int(sessions)
                current[topic_id]["outlier_calls"] += int(outlier_calls)
                tools[topic_id][tool_name] += int(calls)
            if previous_calls:
                previous[topic_id] += int(previous_calls)
        return current, previous, tools

    def _topics_by_id(self) -> dict[str, MCPIntentTopic]:
        return {str(t.pk): t for t in MCPIntentTopic.objects.unscoped().filter(team=self.team)}

    def _coverage(self, current: dict[str, dict[str, int]]) -> MCPIntentCoverage:
        with_intent = sum(v["calls"] for v in current.values())
        assigned = sum(v["calls"] for k, v in current.items() if k != UNASSIGNED)
        return MCPIntentCoverage(
            calls_with_intent=with_intent, calls_assigned=assigned, assigned_pct=_pct(assigned, with_intent)
        )

    def _topic_items(
        self,
        current: dict[str, dict[str, int]],
        previous: dict[str, int],
        tools: dict[str, dict[str, int]],
        limit: int,
    ) -> list[MCPIntentTopicItem]:
        registry = self._topics_by_id()
        total = sum(v["calls"] for v in current.values())
        previous_total = sum(previous.values())
        items = []
        for topic_id, sums in current.items():
            if topic_id == UNASSIGNED:
                continue
            topic = registry.get(topic_id)
            share = _pct(sums["calls"], total)
            previous_share = _pct(previous[topic_id], previous_total) if previous.get(topic_id) else None
            items.append(
                MCPIntentTopicItem(
                    topic_id=topic_id,
                    label=topic.label if topic else f"Topic {topic_id[:8]}",
                    summary=topic.summary if topic else "",
                    calls=sums["calls"],
                    sessions=sums["sessions"],
                    share_pct=share,
                    previous_share_pct=previous_share,
                    trend_pp=round(share - previous_share, 2) if previous_share is not None else None,
                    outlier_calls=sums["outlier_calls"],
                    top_tools=[
                        t for t, _ in sorted(tools[topic_id].items(), key=lambda kv: -kv[1])[:TOP_TOOLS_PER_TOPIC]
                    ],
                )
            )
        items.sort(key=lambda item: (-item.calls, item.topic_id))
        return items[:limit]


class MCPIntentTopicsQueryRunner(_IntentTopicsBase, AnalyticsQueryRunner[MCPIntentTopicsQueryResponse]):
    query: MCPIntentTopicsQuery
    cached_response: CachedMCPIntentTopicsQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        previous_from, _, date_to = self._window
        return _daily_source(previous_from, date_to, self.query.toolName)

    def _calculate(self) -> MCPIntentTopicsQueryResponse:
        current, previous, tools = self._topic_sums(self.query.toolName)
        items = self._topic_items(current, previous, tools, self.query.limit or DEFAULT_TOPICS_LIMIT)
        return MCPIntentTopicsQueryResponse(
            results=items, coverage=self._coverage(current), hogql=self._last_hogql, modifiers=self.modifiers
        )


class MCPToolIntentProfileQueryRunner(_IntentTopicsBase, AnalyticsQueryRunner[MCPToolIntentProfileQueryResponse]):
    query: MCPToolIntentProfileQuery
    cached_response: CachedMCPToolIntentProfileQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        previous_from, _, date_to = self._window
        return _daily_source(previous_from, date_to, self.query.toolName)

    def _sparklines(self, topic_ids: list[str]) -> dict[str, list[int]]:
        _, date_from, date_to = self._window
        days = [(date_from + timedelta(days=i)).date() for i in range((date_to.date() - date_from.date()).days + 1)]
        rows = self._execute(
            parse_select(
                "SELECT topic_id, day, sum(calls) FROM {source} WHERE topic_id IN {topic_ids} GROUP BY topic_id, day",
                placeholders={
                    "source": _daily_source(date_from, date_to, self.query.toolName),
                    "topic_ids": ast.Constant(value=topic_ids),
                },
            ),
            "mcp_tool_intent_profile_sparklines",
        )
        by_topic: dict[str, dict[Any, int]] = defaultdict(dict)
        for topic_id, day, calls in rows:
            by_topic[topic_id][day] = int(calls)
        return {topic_id: [by_topic[topic_id].get(day, 0) for day in days] for topic_id in topic_ids}

    def _outliers(self) -> list[MCPIntentOutlierItem]:
        _, date_from, date_to = self._window
        rows = self._execute(
            parse_select(
                """
                SELECT intent_hash, argMax(intent_text, timestamp) AS latest_text, argMax(calls_in_run, timestamp) AS latest_calls,
                       argMax(distance, timestamp) AS latest_distance, argMax(tool, timestamp) AS latest_tool
                FROM mcp_intent_assignments
                WHERE tool = {tool} AND timestamp >= {date_from} AND timestamp <= {date_to}
                GROUP BY intent_hash
                HAVING argMax(is_outlier, timestamp) = 1
                ORDER BY latest_calls DESC, latest_distance DESC
                LIMIT {limit}
                """,
                placeholders={
                    "tool": ast.Constant(value=self.query.toolName),
                    "date_from": ast.Constant(value=date_from),
                    "date_to": ast.Constant(value=date_to),
                    "limit": ast.Constant(value=OUTLIERS_LIMIT),
                },
            ),
            "mcp_tool_intent_profile_outliers",
        )
        return [
            MCPIntentOutlierItem(
                intent_hash=row[0],
                intent_text=row[1] or "",
                calls=int(row[2] or 0),
                distance=round(float(row[3] or 0), 4),
                tool=row[4] or "",
            )
            for row in rows
        ]

    def _calculate(self) -> MCPToolIntentProfileQueryResponse:
        current, previous, tools = self._topic_sums(self.query.toolName)
        limit = self.query.limit or DEFAULT_PROFILE_LIMIT
        items = self._topic_items(current, previous, tools, limit)
        sparklines = self._sparklines([item.topic_id for item in items]) if items else {}
        for item in items:
            item.sparkline = sparklines.get(item.topic_id, [])

        assigned_now = {k: v["calls"] for k, v in current.items() if k != UNASSIGNED}
        assigned_before = {k: v for k, v in previous.items() if k != UNASSIGNED}
        score = focus_score(assigned_now)
        moved = drift(assigned_now, assigned_before)
        registry = self._topics_by_id()
        total = sum(assigned_now.values())
        previous_total = sum(assigned_before.values())

        def ref(topic_id: str) -> MCPIntentTopicRef:
            topic = registry.get(topic_id)
            return MCPIntentTopicRef(
                topic_id=topic_id,
                label=topic.label if topic else f"Topic {topic_id[:8]}",
                calls=assigned_now.get(topic_id, 0),
                share_pct=_pct(assigned_now.get(topic_id, 0), total),
                previous_share_pct=_pct(assigned_before[topic_id], previous_total)
                if topic_id in assigned_before
                else None,
            )

        return MCPToolIntentProfileQueryResponse(
            results=items,
            focus=MCPIntentFocus(score=round(score, 4), band=focus_band(score)),
            drift=MCPIntentDrift(
                new=[ref(t) for t in moved.new],
                growing=[ref(t) for t in moved.growing],
                shrinking=[ref(t) for t in moved.shrinking],
                gone=[ref(t) for t in moved.gone],
            ),
            outliers=self._outliers(),
            coverage=self._coverage(current),
            hogql=self._last_hogql,
            modifiers=self.modifiers,
        )


class MCPSimilarToolsQueryRunner(_IntentTopicsBase, AnalyticsQueryRunner[MCPSimilarToolsQueryResponse]):
    query: MCPSimilarToolsQuery
    cached_response: CachedMCPSimilarToolsQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        _, date_from, date_to = self._window
        return parse_select(
            "SELECT tool, topic_id, sum(calls) AS total_calls FROM {source} WHERE topic_id != '' GROUP BY tool, topic_id",
            placeholders={"source": _daily_source(date_from, date_to, None)},
        )

    def _calculate(self) -> MCPSimilarToolsQueryResponse:
        rows = self._execute(self.to_query(), "mcp_similar_tools")
        shares: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for tool, topic_id, calls in rows:
            shares[tool][topic_id] += int(calls)
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
                    shared_topics=[
                        registry[t].label if t in registry else f"Topic {t[:8]}" for t in shared[:TOP_TOOLS_PER_TOPIC]
                    ],
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

    def _point_filters(self) -> tuple[str, dict[str, ast.Expr]]:
        _, date_from, date_to = self._window
        clauses = ["timestamp >= {date_from}", "timestamp <= {date_to}"]
        placeholders: dict[str, ast.Expr] = {
            "date_from": ast.Constant(value=date_from),
            "date_to": ast.Constant(value=date_to),
        }
        if self.query.toolName:
            clauses.append("tool = {tool}")
            placeholders["tool"] = ast.Constant(value=self.query.toolName)
        if self.query.topicId:
            clauses.append("topic_id = {topic_id}")
            placeholders["topic_id"] = ast.Constant(value=self.query.topicId)
        if self.query.bounds:
            clauses.append("x >= {x_min} AND x <= {x_max} AND y >= {y_min} AND y <= {y_max}")
            placeholders.update(
                {
                    "x_min": ast.Constant(value=self.query.bounds.x_min),
                    "x_max": ast.Constant(value=self.query.bounds.x_max),
                    "y_min": ast.Constant(value=self.query.bounds.y_min),
                    "y_max": ast.Constant(value=self.query.bounds.y_max),
                }
            )
        return " AND ".join(clauses), placeholders

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        where, placeholders = self._point_filters()
        limit = min(self.query.limit or DEFAULT_MAP_LIMIT, MAX_MAP_LIMIT)
        return parse_select(
            f"""
            SELECT intent_hash, argMax(intent_text, timestamp), argMax(x, timestamp), argMax(y, timestamp),
                   argMax(topic_id, timestamp), argMax(is_outlier, timestamp), argMax(calls_in_run, timestamp) AS latest_calls,
                   argMax(tool, timestamp)
            FROM mcp_intent_assignments
            WHERE {where}
            GROUP BY intent_hash
            ORDER BY latest_calls DESC, intent_hash
            LIMIT {{limit}}
            """,
            placeholders={**placeholders, "limit": ast.Constant(value=limit)},
        )

    def _calculate(self) -> MCPIntentMapQueryResponse:
        rows = self._execute(self.to_query(), "mcp_intent_map_points")
        points = [
            MCPIntentMapPoint(
                intent_hash=row[0],
                intent_text=row[1] or "",
                x=float(row[2]),
                y=float(row[3]),
                topic_id=row[4],
                is_outlier=bool(row[5]),
                calls=int(row[6] or 0),
                tool=row[7] or "",
            )
            for row in rows
        ]
        where, placeholders = self._point_filters()
        total_rows = self._execute(
            parse_select(
                f"SELECT uniqExact(intent_hash) FROM mcp_intent_assignments WHERE {where}", placeholders=placeholders
            ),
            "mcp_intent_map_total",
        )
        total_points = int(total_rows[0][0]) if total_rows else 0

        current, _, _ = self._topic_sums(self.query.toolName)
        total_calls = sum(v["calls"] for k, v in current.items() if k != UNASSIGNED)
        registry = self._topics_by_id()
        topics = [
            MCPIntentMapTopic(
                topic_id=topic_id,
                label=topic.label,
                summary=topic.summary,
                x=topic.centroid_x,
                y=topic.centroid_y,
                calls=current[topic_id]["calls"],
                share_pct=_pct(current[topic_id]["calls"], total_calls),
            )
            for topic_id, topic in registry.items()
            if topic.status == MCPIntentTopic.Status.ACTIVE
            and topic_id in current
            and (not self.query.topicId or topic_id == self.query.topicId)
        ]
        topics.sort(key=lambda t: -t.calls)
        return MCPIntentMapQueryResponse(
            results=points, topics=topics, total_points=total_points, hogql=self._last_hogql, modifiers=self.modifiers
        )
