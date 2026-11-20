from collections.abc import Sequence
from typing import TYPE_CHECKING, Optional

from posthog.schema import EventPropertyFilter, WebPageDirectoryMetric

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from products.web_analytics.backend.hogql_queries.pre_aggregated.properties import STATS_TABLE_SUPPORTED_FILTERS
from products.web_analytics.backend.hogql_queries.pre_aggregated.query_builder import (
    WebAnalyticsPreAggregatedQueryBuilder,
)
from products.web_analytics.backend.hogql_queries.web_dimensional_precompute import (
    WEB_BOUNCES_DIMENSIONAL_READ_TABLE,
    WEB_STATS_DIMENSIONAL_READ_TABLE,
    DimensionalJobIds,
)
from products.web_analytics.backend.hogql_queries.web_dimensional_read import DimensionalTablesMixin

if TYPE_CHECKING:
    from products.web_analytics.backend.hogql_queries.web_page_directory import WebPageDirectoryQueryRunner

METRIC_TABLES = {
    WebPageDirectoryMetric.VISITORS: WEB_STATS_DIMENSIONAL_READ_TABLE,
    WebPageDirectoryMetric.GOOGLE_SEARCH: WEB_STATS_DIMENSIONAL_READ_TABLE,
    WebPageDirectoryMetric.AI_REFERRALS: WEB_STATS_DIMENSIONAL_READ_TABLE,
    WebPageDirectoryMetric.BOUNCE_RATE: WEB_BOUNCES_DIMENSIONAL_READ_TABLE,
}
CHANNEL_CONDITIONS = {
    WebPageDirectoryMetric.GOOGLE_SEARCH: "channel_type = 'Organic Search' AND referring_domain ILIKE '%google%'",
    WebPageDirectoryMetric.AI_REFERRALS: "channel_type = 'AI'",
}
PER_PAGEVIEW_FILTER_KEYS = frozenset({"$pathname", "$host"})


def dimensional_tables_for(
    runner: "WebPageDirectoryQueryRunner", metrics: set[WebPageDirectoryMetric]
) -> frozenset[str]:
    tables = {METRIC_TABLES[metric] for metric in metrics if metric in METRIC_TABLES}
    if any(
        isinstance(prop, EventPropertyFilter) and prop.key in PER_PAGEVIEW_FILTER_KEYS
        for prop in runner.query.properties
    ):
        tables.discard(WEB_BOUNCES_DIMENSIONAL_READ_TABLE)
    if (
        tables
        and WebAnalyticsPreAggregatedQueryBuilder(runner, STATS_TABLE_SUPPORTED_FILTERS).can_use_preaggregated_tables()
    ):
        return frozenset(tables)
    return frozenset()


class DimensionalPageDirectoryQueryBuilder(DimensionalTablesMixin, WebAnalyticsPreAggregatedQueryBuilder):
    runner: "WebPageDirectoryQueryRunner"

    def __init__(self, runner: "WebPageDirectoryQueryRunner", job_ids: DimensionalJobIds) -> None:
        super().__init__(runner, STATS_TABLE_SUPPORTED_FILTERS)
        self.job_ids = job_ids

    def serves(self, metric: WebPageDirectoryMetric) -> bool:
        table = METRIC_TABLES.get(metric)
        return table is not None and self._job_ids_for(table) is not None

    def metric_select(
        self, metric: WebPageDirectoryMetric, grouped: bool, page_keys: Optional[list[str]]
    ) -> ast.SelectQuery:
        if metric == WebPageDirectoryMetric.BOUNCE_RATE:
            return self._bounce_rate_select(grouped, page_keys)
        return self._visitors_select(metric, grouped, page_keys)

    def _visitors_select(
        self, metric: WebPageDirectoryMetric, grouped: bool, page_keys: Optional[list[str]]
    ) -> ast.SelectQuery:
        table = self.stats_table
        periods = self.get_date_ranges(table)
        placeholders: dict[str, ast.Expr] = {"current": periods.current_period, "previous": periods.previous_period}
        if metric == WebPageDirectoryMetric.VISITORS:
            select = (
                "uniqMergeIf(persons_uniq_state, {current}) AS current, "
                "uniqMergeIf(persons_uniq_state, {previous}) AS previous, 0 AS extra"
            )
        else:
            placeholders["channel"] = parse_expr(CHANNEL_CONDITIONS[metric])
            select = (
                "uniqMergeIf(persons_uniq_state, and({current}, {channel})) AS current, "
                "uniqMergeIf(persons_uniq_state, and({previous}, {channel})) AS previous, "
                "uniqMergeIf(persons_uniq_state, {current}) AS extra"
            )
        return self._build(select, table, "pathname", grouped, page_keys, placeholders)

    def _bounce_rate_select(self, grouped: bool, page_keys: Optional[list[str]]) -> ast.SelectQuery:
        table = self.bounces_table
        periods = self.get_date_ranges(table)
        select = (
            "sumMerge(bounces_count_state) / nullIf(sumMerge(total_session_count_state), 0) AS current, "
            "sumMerge(total_session_count_state) AS previous, 0 AS extra"
        )
        return self._build(
            select,
            table,
            "entry_pathname",
            grouped,
            page_keys,
            {"current": periods.current_period},
            conditions=("{current}",),
        )

    def _build(
        self,
        select: str,
        table: str,
        path_column: str,
        grouped: bool,
        page_keys: Optional[list[str]],
        placeholders: dict[str, ast.Expr],
        *,
        conditions: Sequence[str] = (),
    ) -> ast.SelectQuery:
        path = ast.Field(chain=[table, path_column])
        page_key = self.runner._page_key(ast.Field(chain=[table, "host"]), path)
        placeholders = {
            **placeholders,
            "page_key": page_key,
            "filters": self._get_filters(table),
            "path_present": self.runner._path_present(path),
            "scope": self.runner._scope(page_key, page_keys, grouped),
        }
        where = ", ".join(["{filters}", "{path_present}", "{scope}", *conditions])
        return self.runner._build(select, table, where, grouped, placeholders)
