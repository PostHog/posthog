from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.core.cache import cache

from posthog.schema import (
    CachedRevenueAnalyticsTopCustomersQueryResponse,
    DatabaseSchemaManagedViewTableKind,
    ProductKey,
    ResolvedDateRangeResponse,
    RevenueAnalyticsTopCustomersQuery,
    RevenueAnalyticsTopCustomersQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.database.models import UnknownDatabaseField
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, get_query_tags, tags_context
from posthog.utils import get_safe_cache

from products.revenue_analytics.backend.views import (
    RevenueAnalyticsBaseView,
    RevenueAnalyticsCustomerView,
    RevenueAnalyticsRevenueItemView,
)
from products.revenue_analytics.backend.views.schemas import SCHEMAS as VIEW_SCHEMAS

from .revenue_analytics_query_runner import EARLIEST_TIMESTAMP, RevenueAnalyticsQueryRunner

# How long we trust a resolved earliest-revenue timestamp before recomputing it. Matches the
# runner's default result-cache horizon, so the bound is never staler than a cached tile.
EARLIEST_TIMESTAMP_CACHE_TTL = int(timedelta(hours=6).total_seconds())


class RevenueAnalyticsTopCustomersQueryRunner(RevenueAnalyticsQueryRunner[RevenueAnalyticsTopCustomersQueryResponse]):
    query: RevenueAnalyticsTopCustomersQuery
    cached_response: CachedRevenueAnalyticsTopCustomersQueryResponse

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        subqueries = list(
            RevenueAnalyticsQueryRunner.revenue_subqueries(
                VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM],
                self.database,
            )
        )
        if not subqueries:
            columns = ["customer_id", "name", "amount", "month"]
            return ast.SelectQuery.empty(columns={key: UnknownDatabaseField(name=key) for key in columns})

        queries = [self._to_query_from(subquery) for subquery in subqueries]
        return ast.SelectSetQuery.create_from_queries(queries, set_operator="UNION ALL")

    def _to_query_from(self, view: RevenueAnalyticsBaseView) -> ast.SelectQuery:
        is_monthly_grouping = self.query.groupBy == "month"

        with self.timings.measure("inner_query"):
            inner_query = self.inner_query(view)

        query = ast.SelectQuery(
            select=[
                ast.Alias(alias="customer_id", expr=ast.Field(chain=["inner", "customer_id"])),
                ast.Alias(alias="name", expr=ast.Field(chain=["customer_id"])),
                # If grouping all months together, we'll use the sum of the amount
                # Otherwise, we'll use the amount for the specific month
                ast.Alias(
                    alias="amount",
                    expr=ast.Field(chain=["inner", "amount"])
                    if is_monthly_grouping
                    else ast.Call(name="sum", args=[ast.Field(chain=["inner", "amount"])]),
                ),
                ast.Alias(
                    alias="month",
                    expr=ast.Field(chain=["inner", "month"]) if is_monthly_grouping else ast.Constant(value="all"),
                ),
            ],
            select_from=ast.JoinExpr(table=inner_query, alias="inner"),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["amount"]), order="DESC")],
            # Only need to group if we're grouping all months together
            group_by=[
                ast.Field(chain=["customer_id"]),
                ast.Field(chain=["name"]),
            ]
            if not is_monthly_grouping
            else [],
            # Limit by month again to limit too many rows if we're spanning more than one month
            # but still grouping them because we're using the sum of the amount
            limit_by=ast.LimitByExpr(n=ast.Constant(value=20), exprs=[ast.Field(chain=["month"])]),
        )

        customer_views = RevenueAnalyticsQueryRunner.revenue_subqueries(
            VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER],
            self.database,
        )
        customer_view = next(
            (customer_view for customer_view in customer_views if customer_view.prefix == view.prefix), None
        )
        if customer_view is not None and query.select_from is not None:
            query.select_from.next_join = ast.JoinExpr(
                alias=RevenueAnalyticsCustomerView.get_generic_view_alias(),
                table=ast.Field(chain=[customer_view.name]),
                join_type="LEFT JOIN",
                constraint=ast.JoinConstraint(
                    constraint_type="ON",
                    expr=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["inner", "customer_id"]),
                        right=ast.Field(chain=[RevenueAnalyticsCustomerView.get_generic_view_alias(), "id"]),
                    ),
                ),
            )

            if len(query.select) >= 2 and isinstance(query.select[1], ast.Alias) and query.select[1].alias == "name":
                query.select[1] = ast.Alias(
                    alias="name", expr=ast.Field(chain=[RevenueAnalyticsCustomerView.get_generic_view_alias(), "name"])
                )
            else:
                raise ValueError("Name field not found in second position of query select")

        return query

    def inner_query(self, view: RevenueAnalyticsBaseView) -> ast.SelectQuery:
        query = ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="customer_id",
                    expr=ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "customer_id"]),
                ),
                ast.Alias(
                    alias="month",
                    expr=ast.Call(
                        name="toStartOfMonth",
                        args=[ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "timestamp"])],
                    ),
                ),
                ast.Alias(
                    alias="amount",
                    expr=ast.Call(
                        name="sum",
                        args=[ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "amount"])],
                    ),
                ),
            ],
            select_from=self._with_where_property_joins(
                ast.JoinExpr(
                    alias=RevenueAnalyticsRevenueItemView.get_generic_view_alias(),
                    table=ast.Field(chain=[view.name]),
                ),
                view,
            ),
            where=ast.And(
                exprs=[
                    self.timestamp_where_clause(
                        [
                            RevenueAnalyticsRevenueItemView.get_generic_view_alias(),
                            "timestamp",
                        ]
                    ),
                    *self.where_property_exprs(view),
                ]
            ),
            group_by=[ast.Field(chain=["customer_id"]), ast.Field(chain=["month"])],
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["amount"]), order="DESC")],
            # Top 20 by month only to avoid too many rows
            limit_by=ast.LimitByExpr(n=ast.Constant(value=20), exprs=[ast.Field(chain=["month"])]),
        )

        return query

    def _earliest_timestamp_fallback(self) -> datetime:
        # Only "all time" ranges read the fallback; for explicit ranges QueryDateRange uses
        # its own date_from, so skip the extra min(timestamp) lookup entirely.
        date_range = self.query.dateRange
        if date_range is None or date_range.date_from != "all":
            return EARLIEST_TIMESTAMP

        return self._resolve_earliest_revenue_timestamp()

    def _resolve_earliest_revenue_timestamp(self) -> datetime:
        """Resolve the team's real earliest revenue-item timestamp for "all time" ranges.

        The static EARLIEST_TIMESTAMP fallback (2015) forces "all time" to scan a decade of
        empty partitions before the team's first revenue row, which can push the UNION ALL /
        per-customer aggregation past ClickHouse's execution ceiling on large datasets.
        Bounding the window to the real minimum keeps the scan tight. Cached, floored at
        EARLIEST_TIMESTAMP, and defensive: any failure keeps the previous 2015 behavior
        rather than breaking the tile.
        """
        cache_key = f"revenue_analytics_earliest_timestamp_{self.team.pk}"
        cached = get_safe_cache(cache_key)
        if cached is not None:
            return cached

        try:
            earliest = self._query_earliest_revenue_timestamp()
        except Exception:
            return EARLIEST_TIMESTAMP

        cache.set(cache_key, earliest, timeout=EARLIEST_TIMESTAMP_CACHE_TTL)
        return earliest

    def _query_earliest_revenue_timestamp(self) -> datetime:
        revenue_item_views = list(
            RevenueAnalyticsQueryRunner.revenue_subqueries(
                VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM],
                self.database,
            )
        )
        if not revenue_item_views:
            return EARLIEST_TIMESTAMP

        # One cheap single-column min per source; take the overall minimum in Python so that
        # sources with no rows are simply skipped.
        queries = [
            ast.SelectQuery(
                select=[ast.Call(name="min", args=[ast.Field(chain=["timestamp"])])],
                select_from=ast.JoinExpr(table=ast.Field(chain=[view.name])),
            )
            for view in revenue_item_views
        ]
        query = ast.SelectSetQuery.create_from_queries(queries, set_operator="UNION ALL")

        with self._earliest_timestamp_query_tags():
            response = execute_hogql_query(
                query_type="revenue_analytics_earliest_timestamp_query",
                query=query,
                team=self.team,
                user=self.user,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        # Only keep real timestamps strictly after the 2015 floor. An empty revenue-item view
        # (e.g. an events source with no matching events, whose skeleton branch is `WHERE 0`)
        # comes back as ClickHouse's `1970-01-01` epoch default for min() over an empty set,
        # not NULL, so it must be discarded rather than allowed to pin the window back at 2015.
        timestamps = [ts for ts in (self._coerce_timestamp(row) for row in response.results) if ts is not None]
        if not timestamps:
            return EARLIEST_TIMESTAMP

        return min(timestamps)

    @staticmethod
    def _coerce_timestamp(row: list) -> datetime | None:
        if not row or row[0] is None or not isinstance(row[0], datetime):
            return None

        value = row[0]
        if value.tzinfo is None:
            value = value.replace(tzinfo=ZoneInfo("UTC"))

        # Discard the epoch sentinel / any pre-2015 (corrupt or floored) value.
        return value if value > EARLIEST_TIMESTAMP else None

    @staticmethod
    def _earliest_timestamp_query_tags() -> AbstractContextManager[None]:
        # Resolving the fallback can run during cache-staleness checks, before the main query
        # tags this execution. An untagged ClickHouse query raises in local dev, so fill in
        # product/feature when the caller has not already tagged them.
        current = get_query_tags()
        overrides = {}
        if current.product is None:
            overrides["product"] = ProductKey.REVENUE_ANALYTICS
        if current.feature is None:
            overrides["feature"] = Feature.QUERY
        return tags_context(**overrides)

    def _calculate(self):
        with self.timings.measure("to_query"):
            query = self.to_query()

        with self.timings.measure("execute_hogql_query"):
            response = execute_hogql_query(
                query_type="revenue_analytics_top_customers_query",
                query=query,
                team=self.team,
                user=self.user,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        return RevenueAnalyticsTopCustomersQueryResponse(
            results=response.results,
            columns=response.columns,
            modifiers=self.modifiers,
            resolved_date_range=ResolvedDateRangeResponse(
                date_from=self.query_date_range.date_from(),
                date_to=self.query_date_range.date_to(),
            ),
        )
