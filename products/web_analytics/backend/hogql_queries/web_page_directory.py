from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Optional

from posthog.schema import (
    CachedWebPageDirectoryQueryResponse,
    EventPropertyFilter,
    WebPageDirectoryMetric,
    WebPageDirectoryQuery,
    WebPageDirectoryQueryResponse,
    WebPageDirectoryRow,
    WebPageDirectorySiteTotals,
    WebPageDirectorySortBy,
    WebPageDirectoryValue,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import get_property_key, property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings

from posthog.hogql_queries.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.utils.caller_context import map_in_caller_context

from products.web_analytics.backend.hogql_queries.agent_analytics_definitions import (
    AGENT_CATEGORIES_WITH_CRAWLERS,
    AGENT_NAVIGATION_EVENTS,
)
from products.web_analytics.backend.hogql_queries.web_analytics_query_runner import WebAnalyticsQueryRunner
from products.web_analytics.backend.hogql_queries.web_bots import BOT_ANALYTICS_EVENTS

DEFAULT_LIMIT = 25
MAX_PAGE_KEYS = 100
MAX_CRAWLER_NAMES = 4
MIN_SESSIONS_FOR_RATE_SORT = 10
STATIC_ASSET_PATTERN = r"(?i)\.(png|jpe?g|gif|svg|ico|webp|avif|bmp|css|js|mjs|map|woff2?|ttf|otf|eot)$"
DEFAULT_METRICS = (
    WebPageDirectoryMetric.VISITORS,
    WebPageDirectoryMetric.GOOGLE_SEARCH,
    WebPageDirectoryMetric.AI_REFERRALS,
    WebPageDirectoryMetric.AI_CRAWLS,
    WebPageDirectoryMetric.CONVERSIONS,
    WebPageDirectoryMetric.TIME_ON_PAGE,
)
SORT_METRIC: dict[WebPageDirectorySortBy, WebPageDirectoryMetric] = {
    WebPageDirectorySortBy.PAGE: WebPageDirectoryMetric.VISITORS,
    WebPageDirectorySortBy.VISITORS: WebPageDirectoryMetric.VISITORS,
    WebPageDirectorySortBy.GOOGLE_SEARCH: WebPageDirectoryMetric.GOOGLE_SEARCH,
    WebPageDirectorySortBy.AI_REFERRALS: WebPageDirectoryMetric.AI_REFERRALS,
    WebPageDirectorySortBy.AI_CRAWLS: WebPageDirectoryMetric.AI_CRAWLS,
    WebPageDirectorySortBy.CONVERSIONS: WebPageDirectoryMetric.CONVERSIONS,
    WebPageDirectorySortBy.TIME_ON_PAGE: WebPageDirectoryMetric.TIME_ON_PAGE,
    WebPageDirectorySortBy.BOUNCE_RATE: WebPageDirectoryMetric.BOUNCE_RATE,
}
COUNT_FIELDS: dict[WebPageDirectoryMetric, str] = {
    WebPageDirectoryMetric.VISITORS: "visitors",
    WebPageDirectoryMetric.GOOGLE_SEARCH: "googleSearch",
    WebPageDirectoryMetric.AI_REFERRALS: "aiReferrals",
    WebPageDirectoryMetric.AI_CRAWLS: "aiCrawls",
    WebPageDirectoryMetric.CONVERSIONS: "conversions",
}
RATE_FIELDS: dict[WebPageDirectoryMetric, str] = {
    WebPageDirectoryMetric.TIME_ON_PAGE: "timeOnPageP90",
    WebPageDirectoryMetric.BOUNCE_RATE: "bounceRate",
}


@dataclass(frozen=True)
class MetricValues:
    current: Optional[float]
    previous: Optional[float] = None
    extra: Optional[float] = None
    names: tuple[str, ...] = ()


def _metric_values(row: Sequence[Any]) -> MetricValues:
    names = tuple(str(name) for name in row[3]) if len(row) > 3 and isinstance(row[3], list | tuple) else ()
    return MetricValues(current=row[0], previous=row[1], extra=row[2], names=names)


class WebPageDirectoryQueryRunner(WebAnalyticsQueryRunner[WebPageDirectoryQueryResponse]):
    query: WebPageDirectoryQuery
    cached_response: CachedWebPageDirectoryQueryResponse
    paginator: HogQLHasMorePaginator

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit or DEFAULT_LIMIT,
            offset=self.query.offset or 0,
        )

    @property
    def sort_by(self) -> WebPageDirectorySortBy:
        sort_by = self.query.sortBy or WebPageDirectorySortBy.VISITORS
        if sort_by == WebPageDirectorySortBy.CONVERSIONS and self.conversion_goal_expr is None:
            return WebPageDirectorySortBy.VISITORS
        return sort_by

    @property
    def sort_direction(self) -> Literal["ASC", "DESC"]:
        return "ASC" if self.query.sortDirection == "ASC" else "DESC"

    @property
    def requested_metrics(self) -> list[WebPageDirectoryMetric]:
        metrics = list(self.query.metrics) if self.query.metrics is not None else list(DEFAULT_METRICS)
        return [
            metric
            for metric in dict.fromkeys(metrics)
            if metric != WebPageDirectoryMetric.CONVERSIONS or self.conversion_goal_expr is not None
        ]

    def _page_key(self, host: ast.Expr, path: ast.Expr) -> ast.Expr:
        return ast.Call(
            name="concat",
            args=[ast.Call(name="coalesce", args=[host, ast.Constant(value="")]), self._apply_path_cleaning(path)],
        )

    def _event_page_key(self, path_property: str = "$pathname") -> ast.Expr:
        return self._page_key(
            ast.Field(chain=["events", "properties", "$host"]),
            ast.Field(chain=["events", "properties", path_property]),
        )

    def _session_page_key(self) -> ast.Expr:
        return self._page_key(
            ast.Field(chain=["sessions", "$entry_hostname"]),
            ast.Field(chain=["sessions", "$entry_pathname"]),
        )

    def _path_present(self, path: ast.Expr) -> ast.Expr:
        exprs: list[ast.Expr] = [
            ast.Call(name="isNotNull", args=[path]),
            ast.CompareOperation(op=ast.CompareOperationOp.NotEq, left=path, right=ast.Constant(value="")),
        ]
        if self.query.excludeStaticAssets:
            exprs.append(
                ast.Call(
                    name="not", args=[ast.Call(name="match", args=[path, ast.Constant(value=STATIC_ASSET_PATTERN)])]
                )
            )
        return ast.And(exprs=exprs)

    def _scope(self, page_key: ast.Expr, page_keys: Optional[list[str]], grouped: bool) -> ast.Expr:
        exprs: list[ast.Expr] = []
        if page_keys is not None:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=page_key,
                    right=ast.Tuple(exprs=[ast.Constant(value=key) for key in page_keys]),
                )
            )
        if grouped and self.query.search:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Gt,
                    left=ast.Call(
                        name="positionCaseInsensitive", args=[page_key, ast.Constant(value=self.query.search)]
                    ),
                    right=ast.Constant(value=0),
                )
            )
        return ast.And(exprs=exprs) if exprs else ast.Constant(value=True)

    def _session_window(self) -> ast.Expr:
        date_ranges = [self.query_date_range]
        if self.query_compare_to_date_range:
            date_ranges.append(self.query_compare_to_date_range)
        return ast.Or(
            exprs=[
                parse_expr(
                    "sessions.$start_timestamp >= minus({date_from}, toIntervalDay(1)) AND sessions.$start_timestamp <= {date_to}",
                    placeholders={
                        "date_from": date_range.date_from_as_hogql(),
                        "date_to": date_range.date_to_as_hogql(),
                    },
                )
                for date_range in date_ranges
            ]
        )

    @property
    def _has_filters(self) -> bool:
        return bool(self.effective_query_properties or self.first_pageview_filter_exprs or self._test_account_filters)

    def _previous_page_properties(self) -> ast.Expr:
        properties = [
            prop.model_copy(update={"key": "$prev_pageview_pathname"})
            if isinstance(prop, EventPropertyFilter) and get_property_key(prop) == "$pathname"
            else prop
            for prop in self.effective_query_properties
        ]
        return property_to_expr(
            [*properties, *self.first_pageview_filter_exprs, *self._test_account_filters], team=self.team
        )

    def _channel_sessions(self, channel_condition: str) -> ast.SelectQuery:
        query = parse_select(
            "SELECT session_id FROM sessions WHERE and({window}, {channel})",
            placeholders={"window": self._session_window(), "channel": parse_expr(channel_condition)},
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _metric_select(
        self, metric: WebPageDirectoryMetric, grouped: bool, page_keys: Optional[list[str]]
    ) -> Optional[ast.SelectQuery]:
        current = self._current_period_expression("timestamp")
        previous = self._previous_period_expression("timestamp")
        periods = self._periods_expression("timestamp")
        properties = self.all_properties()
        event_path = ast.Field(chain=["events", "properties", "$pathname"])
        page_key = self._event_page_key()
        placeholders: dict[str, ast.Expr] = {
            "current": current,
            "previous": previous,
            "periods": periods,
            "properties": properties,
            "path_present": self._path_present(event_path),
            "page_key": page_key,
            "scope": self._scope(page_key, page_keys, grouped),
            "human_events": ast.Tuple(exprs=[ast.Constant(value=event) for event in AGENT_NAVIGATION_EVENTS]),
        }

        if metric in (
            WebPageDirectoryMetric.VISITORS,
            WebPageDirectoryMetric.GOOGLE_SEARCH,
            WebPageDirectoryMetric.AI_REFERRALS,
        ):
            where = "event IN {human_events}, {path_present}, {periods}, {properties}, {scope}"
            if metric == WebPageDirectoryMetric.VISITORS:
                select = (
                    "uniqIf(person_id, {current}) AS current, uniqIf(person_id, {previous}) AS previous, 0 AS extra"
                )
            else:
                channel = (
                    "$channel_type = 'Organic Search' AND $entry_referring_domain ILIKE '%google%'"
                    if metric == WebPageDirectoryMetric.GOOGLE_SEARCH
                    else "$channel_type = 'AI'"
                )
                placeholders["channel_sessions"] = self._channel_sessions(channel)
                select = (
                    "uniqIf(person_id, and({current}, events.$session_id IN {channel_sessions})) AS current, "
                    "uniqIf(person_id, and({previous}, events.$session_id IN {channel_sessions})) AS previous, "
                    "uniqIf(person_id, {current}) AS extra"
                )
            return self._build(select, "events", where, grouped, placeholders)

        if metric == WebPageDirectoryMetric.AI_CRAWLS:
            placeholders["crawler_events"] = ast.Tuple(
                exprs=[ast.Constant(value=event) for event in BOT_ANALYTICS_EVENTS]
            )
            placeholders["crawler_categories"] = ast.Tuple(
                exprs=[ast.Constant(value=category) for category in AGENT_CATEGORIES_WITH_CRAWLERS]
            )
            select = (
                "countIf({current}) AS current, countIf({previous}) AS previous, "
                "uniqIf(`$virt_bot_name`, {current}) AS extra, "
                f"arraySlice(arraySort(groupUniqArrayIf(`$virt_bot_name`, {{current}})), 1, {MAX_CRAWLER_NAMES}) AS names"
            )
            where = (
                "event IN {crawler_events}, {path_present}, `$virt_is_bot` = true, `$virt_bot_name` != '', "
                "`$virt_traffic_category` IN {crawler_categories}, {periods}, {properties}, {scope}"
            )
            return self._build(select, "events", where, grouped, placeholders)

        if metric == WebPageDirectoryMetric.CONVERSIONS:
            goal = self.conversion_goal_expr
            if goal is None:
                return None
            placeholders["goal"] = goal
            select = "countIf({current}) AS current, countIf({previous}) AS previous, 0 AS extra"
            where = "{goal}, {path_present}, {periods}, {properties}, {scope}"
            return self._build(select, "events", where, grouped, placeholders)

        if metric == WebPageDirectoryMetric.TIME_ON_PAGE:
            previous_path = ast.Field(chain=["events", "properties", "$prev_pageview_pathname"])
            previous_page_key = self._event_page_key("$prev_pageview_pathname")
            placeholders["page_key"] = previous_page_key
            placeholders["scope"] = self._scope(previous_page_key, page_keys, grouped)
            placeholders["path_present"] = self._path_present(previous_path)
            placeholders["duration_events"] = ast.Tuple(
                exprs=[ast.Constant(value=event) for event in (*AGENT_NAVIGATION_EVENTS, "$pageleave")]
            )
            select = (
                "quantile(0.9)(least(toFloat(properties.$prev_pageview_duration), 86400)) AS current, "
                "count() AS previous, 0 AS extra"
            )
            placeholders["properties"] = self._previous_page_properties()
            where = (
                "event IN {duration_events}, {path_present}, isNotNull(properties.$prev_pageview_duration), "
                "{current}, {properties}, {scope}"
            )
            return self._build(select, "events", where, grouped, placeholders)

        if metric == WebPageDirectoryMetric.BOUNCE_RATE:
            session_path = ast.Field(chain=["sessions", "$entry_pathname"])
            session_page_key = self._session_page_key()
            placeholders["page_key"] = session_page_key
            placeholders["scope"] = self._scope(session_page_key, page_keys, grouped)
            placeholders["path_present"] = self._path_present(session_path)
            placeholders["session_current"] = self._current_period_expression("$start_timestamp")
            select = "avg(toFloat(sessions.$is_bounce)) AS current, count() AS previous, 0 AS extra"
            where = "{path_present}, {session_current}, {scope}"
            if self._has_filters:
                placeholders["filtered_sessions"] = self._filtered_sessions()
                where += ", sessions.session_id IN {filtered_sessions}"
            return self._build(select, "sessions", where, grouped, placeholders)

        return None

    def _filtered_sessions(self) -> ast.SelectQuery:
        query = parse_select(
            "SELECT DISTINCT events.$session_id FROM events WHERE and(event IN {human_events}, {current}, {properties})",
            placeholders={
                "human_events": ast.Tuple(exprs=[ast.Constant(value=event) for event in AGENT_NAVIGATION_EVENTS]),
                "current": self._current_period_expression("timestamp"),
                "properties": self.all_properties(),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _build(
        self, select: str, table: str, where: str, grouped: bool, placeholders: dict[str, ast.Expr]
    ) -> ast.SelectQuery:
        if grouped:
            template = f"SELECT {{page_key}} AS page_key, {select} FROM {table} WHERE and({where}) GROUP BY page_key"
        else:
            template = f"SELECT {select} FROM {table} WHERE and({where})"
        query = parse_select(template, placeholders=placeholders, timings=self.timings)
        assert isinstance(query, ast.SelectQuery)
        return query

    def _driver_query(self) -> ast.SelectQuery:
        metric = SORT_METRIC[self.sort_by]
        query = self._metric_select(metric, grouped=True, page_keys=None)
        assert query is not None
        direction = self.sort_direction
        if self.sort_by == WebPageDirectorySortBy.PAGE:
            query.order_by = [ast.OrderExpr(expr=ast.Field(chain=["page_key"]), order=direction)]
        else:
            query.order_by = [
                ast.OrderExpr(expr=ast.Field(chain=["current"]), order=direction),
                ast.OrderExpr(expr=ast.Field(chain=["page_key"]), order="ASC"),
            ]
        if metric in (WebPageDirectoryMetric.TIME_ON_PAGE, WebPageDirectoryMetric.BOUNCE_RATE):
            query.having = parse_expr(
                "previous >= {min_sessions}",
                placeholders={"min_sessions": ast.Constant(value=MIN_SESSIONS_FOR_RATE_SORT)},
            )
        elif metric in (WebPageDirectoryMetric.GOOGLE_SEARCH, WebPageDirectoryMetric.AI_REFERRALS):
            query.having = parse_expr("extra > 0")
        else:
            query.having = parse_expr("current > 0")
        return query

    def to_query(self) -> ast.SelectQuery:
        if self.query.pageKeys is not None:
            metric = SORT_METRIC[self.sort_by]
            query = self._metric_select(metric, grouped=True, page_keys=self._page_keys())
            assert query is not None
            return query
        return self._driver_query()

    def _page_keys(self) -> list[str]:
        return list(dict.fromkeys(self.query.pageKeys or []))[:MAX_PAGE_KEYS]

    def _run(self, query_type: str, query: ast.SelectQuery, timings: HogQLTimings, context: HogQLContext) -> list[Any]:
        response = execute_hogql_query(
            query_type=query_type,
            query=query,
            team=self.team,
            user=self.user,
            context=context,
            timings=timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )
        return list(response.results or [])

    def _run_concurrently(self, queries: dict[str, ast.SelectQuery]) -> dict[str, list[Any]]:
        jobs = [
            (query_type, query, self.timings.clone_for_subquery(index), self.build_hogql_context())
            for index, (query_type, query) in enumerate(queries.items())
        ]
        results = map_in_caller_context(lambda job: self._run(*job), jobs, thread_name_prefix="web_page_directory")
        for _, _, timings, _ in jobs:
            self.timings.timings.update(timings.timings)
        return dict(zip(queries, results))

    def _server_log_query(self) -> ast.SelectQuery:
        query = parse_select(
            "SELECT count() FROM events WHERE and(event = '$http_log', {current}, {properties})",
            placeholders={
                "current": self._current_period_expression("timestamp"),
                "properties": self.all_properties(),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _value(self, values: Optional[MetricValues]) -> Optional[WebPageDirectoryValue]:
        if values is None or values.current is None:
            return None
        previous = values.previous if self.query_compare_to_date_range else None
        return WebPageDirectoryValue(current=float(values.current), previous=previous)

    def _apply(self, target: dict[str, Any], metric: WebPageDirectoryMetric, values: Optional[MetricValues]) -> None:
        if metric in COUNT_FIELDS:
            target[COUNT_FIELDS[metric]] = self._value(values) or WebPageDirectoryValue(current=0)
        elif metric in RATE_FIELDS:
            target[RATE_FIELDS[metric]] = float(values.current) if values and values.current is not None else None
        if metric == WebPageDirectoryMetric.AI_CRAWLS:
            target["aiCrawlers"] = int(values.extra or 0) if values else 0
            target["aiCrawlerNames"] = list(values.names) if values else []

    def _calculate(self) -> WebPageDirectoryQueryResponse:
        sort_metric = SORT_METRIC[self.sort_by]
        pagination: dict[str, Any] = {}
        by_metric: dict[WebPageDirectoryMetric, dict[str, MetricValues]] = {}

        if self.query.pageKeys is not None:
            page_keys = self._page_keys()
        else:
            self.paginator.execute_hogql_query(
                query_type="web_page_directory_query",
                query=self._driver_query(),
                team=self.team,
                user=self.user,
                context=self.build_hogql_context(),
                timings=self.timings,
                modifiers=self.modifiers,
            )
            rows = self.paginator.results or []
            page_keys = [row[0] for row in rows]
            by_metric[sort_metric] = {row[0]: _metric_values(row[1:]) for row in rows}
            pagination = self.paginator.response_params()

        page_metrics = [metric for metric in self.requested_metrics if metric not in by_metric] if page_keys else []
        site_metrics = (
            list(dict.fromkeys([*self.requested_metrics, sort_metric])) if self.query.includeSiteTotals else []
        )
        queries: dict[str, ast.SelectQuery] = {}
        for metric in page_metrics:
            if query := self._metric_select(metric, grouped=True, page_keys=page_keys):
                query.limit = ast.Constant(value=len(page_keys))
                queries[f"web_page_directory_{metric.value}"] = query
        for metric in site_metrics:
            if query := self._metric_select(metric, grouped=False, page_keys=None):
                queries[f"web_page_directory_site_{metric.value}"] = query
        if self.query.includeSiteTotals:
            queries["web_page_directory_server_logs"] = self._server_log_query()
        query_results = self._run_concurrently(queries)

        for metric in page_metrics:
            by_metric[metric] = {
                row[0]: _metric_values(row[1:]) for row in query_results.get(f"web_page_directory_{metric.value}", [])
            }

        results: list[WebPageDirectoryRow] = []
        for page_key in page_keys:
            row: dict[str, Any] = {"page": page_key}
            for metric, values_by_page in by_metric.items():
                self._apply(row, metric, values_by_page.get(page_key))
            results.append(WebPageDirectoryRow(**row))

        site_totals: Optional[WebPageDirectorySiteTotals] = None
        if self.query.includeSiteTotals:
            server_logs = query_results["web_page_directory_server_logs"]
            totals: dict[str, Any] = {"serverLogs": int(server_logs[0][0]) if server_logs else 0}
            for metric in site_metrics:
                site_rows = query_results.get(f"web_page_directory_site_{metric.value}")
                self._apply(totals, metric, _metric_values(site_rows[0]) if site_rows else None)
            site_totals = WebPageDirectorySiteTotals(**totals)

        return WebPageDirectoryQueryResponse(
            results=results,
            siteTotals=site_totals,
            timings=self.timings.to_list(),
            modifiers=self.modifiers,
            **pagination,
        )
