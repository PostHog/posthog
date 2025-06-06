from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.schema import (
    CachedRevenueAnalyticsInsightsQueryResponse,
    RevenueAnalyticsInsightsQueryResponse,
    RevenueAnalyticsInsightsQuery,
)
from posthog.utils import format_label_date

from .revenue_analytics_query_runner import (
    RevenueAnalyticsQueryRunner,
)
from products.revenue_analytics.backend.views.revenue_analytics_customer_view import RevenueAnalyticsCustomerView
from products.revenue_analytics.backend.views.revenue_analytics_product_view import RevenueAnalyticsProductView
from products.revenue_analytics.backend.views.revenue_analytics_invoice_item_view import RevenueAnalyticsInvoiceItemView

NO_BREAKDOWN_PLACEHOLDER = "<none>"


class RevenueAnalyticsInsightsQueryRunner(RevenueAnalyticsQueryRunner):
    query: RevenueAnalyticsInsightsQuery
    response: RevenueAnalyticsInsightsQueryResponse
    cached_response: CachedRevenueAnalyticsInsightsQueryResponse

    def to_query(self) -> ast.SelectQuery:
        subquery = self._get_subquery()
        if subquery is None:
            return ast.SelectQuery.empty()

        return ast.SelectQuery(
            select=[
                ast.Alias(alias="value", expr=ast.Call(name="sum", args=[ast.Field(chain=["amount"])])),
                ast.Alias(alias="day_start", expr=ast.Field(chain=["day_start"])),
                ast.Alias(alias="breakdown_by", expr=ast.Field(chain=["breakdown_by"])),
            ],
            select_from=ast.JoinExpr(table=subquery),
            group_by=[ast.Field(chain=["day_start"]), ast.Field(chain=["breakdown_by"])],
            # Return sorted by day_start, and then for each individual day we put the maximum first
            # This will allow us to return the list sorted according to the numbers in the last day
            # Finally sort by breakdown_by for the rare cases where they tie (usually at 0 revenue)
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=["day_start"]), order="DESC"),
                ast.OrderExpr(expr=ast.Field(chain=["value"]), order="DESC"),
                ast.OrderExpr(expr=ast.Field(chain=["breakdown_by"]), order="ASC"),
            ],
            # Need a huge limit because we need (dates x breakdown)-many rows to be returned
            limit=ast.Constant(value=10000),
        )

    def _get_subquery(self) -> ast.SelectQuery | None:
        if self.query.groupBy == "all":
            return self._get_subquery_by_all()
        elif self.query.groupBy == "product":
            return self._get_subquery_by_product()
        elif self.query.groupBy == "cohort":
            return self._get_subquery_by_cohort()

        raise ValueError(f"Invalid group by: {self.query.groupBy}")

    def _get_subquery_by_all(self) -> ast.SelectQuery | None:
        _, _, invoice_item_subquery, _ = self.revenue_subqueries
        if invoice_item_subquery is None:
            return None

        return ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="breakdown_by",
                    expr=ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "source_label"]),
                ),
                ast.Alias(alias="amount", expr=ast.Field(chain=["amount"])),
                ast.Alias(
                    alias="day_start",
                    expr=ast.Call(
                        name=f"toStartOf{self.query_date_range.interval_name.title()}",
                        args=[ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "timestamp"])],
                    ),
                ),
            ],
            select_from=self.append_joins(
                ast.JoinExpr(
                    alias=RevenueAnalyticsInvoiceItemView.get_generic_view_alias(),
                    table=invoice_item_subquery,
                ),
                self.joins_for_properties,
            ),
            where=ast.And(
                exprs=[
                    self.timestamp_where_clause(
                        chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "timestamp"]
                    ),
                    *self.where_property_exprs,
                ]
            ),
        )

    def _get_subquery_by_product(self) -> ast.SelectQuery | None:
        _, _, invoice_item_subquery, product_subquery = self.revenue_subqueries
        if invoice_item_subquery is None:
            return None

        query = ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="breakdown_by",
                    expr=ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "source_label"]),
                ),
                ast.Alias(alias="amount", expr=ast.Field(chain=["amount"])),
                ast.Alias(
                    alias="day_start",
                    expr=ast.Call(
                        name=f"toStartOf{self.query_date_range.interval_name.title()}",
                        args=[ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "timestamp"])],
                    ),
                ),
            ],
            select_from=self.append_joins(
                ast.JoinExpr(
                    alias=RevenueAnalyticsInvoiceItemView.get_generic_view_alias(),
                    table=invoice_item_subquery,
                ),
                self.joins_for_properties,
            ),
            where=ast.And(
                exprs=[
                    self.timestamp_where_clause(
                        chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "timestamp"]
                    ),
                    *self.where_property_exprs,
                ]
            ),
        )

        # Join with product to get access to the `product_name`
        # and also change the `breakdown_by` to include that
        if product_subquery is not None:
            # This `if` is required to make mypy happy
            if (
                query.select
                and query.select[0]
                and isinstance(query.select[0], ast.Alias)
                and query.select[0].alias == "breakdown_by"
            ):
                query.select[0].expr = ast.Call(
                    name="concat",
                    args=[
                        ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "source_label"]),
                        ast.Constant(value=" - "),
                        ast.Call(
                            name="coalesce",
                            args=[
                                ast.Field(chain=[RevenueAnalyticsProductView.get_generic_view_alias(), "name"]),
                                ast.Constant(value=NO_BREAKDOWN_PLACEHOLDER),
                            ],
                        ),
                    ],
                )

            # We wanna include a join with the product table to get the product name
            # and also change the `breakdown_by` to include that
            # However, because we're already likely joining with the product because
            # we might be filtering on item, we need to be extra safe here and guarantee
            # there's no join with the product table before adding this one
            if query.select_from is not None:
                has_product_join = False
                current_join: ast.JoinExpr | None = query.select_from
                while current_join is not None:
                    if current_join.alias == RevenueAnalyticsProductView.get_generic_view_alias():
                        has_product_join = True
                        break
                    current_join = current_join.next_join

                if not has_product_join:
                    query.select_from = self.append_joins(
                        query.select_from,
                        [self.create_product_join(product_subquery)],
                    )

        return query

    def _get_subquery_by_cohort(self) -> ast.SelectQuery | None:
        _, customer_subquery, invoice_item_subquery, _ = self.revenue_subqueries
        if invoice_item_subquery is None:
            return None

        query = ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="breakdown_by",
                    expr=ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "source_label"]),
                ),
                ast.Alias(alias="amount", expr=ast.Field(chain=["amount"])),
                ast.Alias(
                    alias="day_start",
                    expr=ast.Call(
                        name=f"toStartOf{self.query_date_range.interval_name.title()}",
                        args=[ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "timestamp"])],
                    ),
                ),
            ],
            select_from=self.append_joins(
                ast.JoinExpr(
                    alias=RevenueAnalyticsInvoiceItemView.get_generic_view_alias(),
                    table=invoice_item_subquery,
                ),
                self.joins_for_properties,
            ),
            where=ast.And(
                exprs=[
                    self.timestamp_where_clause(
                        chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "timestamp"]
                    ),
                    *self.where_property_exprs,
                ]
            ),
        )

        # Join with product to get access to the `product_name`
        # and also change the `breakdown_by` to include that
        if customer_subquery is not None:
            # This `if` is required to make mypy happy
            if (
                query.select
                and query.select[0]
                and isinstance(query.select[0], ast.Alias)
                and query.select[0].alias == "breakdown_by"
            ):
                query.select[0].expr = ast.Call(
                    name="concat",
                    args=[
                        ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "source_label"]),
                        ast.Constant(value=" - "),
                        ast.Call(
                            name="coalesce",
                            args=[
                                ast.Field(chain=[RevenueAnalyticsCustomerView.get_generic_view_alias(), "cohort"]),
                                ast.Constant(value=NO_BREAKDOWN_PLACEHOLDER),
                            ],
                        ),
                    ],
                )

            # We wanna include a join with the product table to get the product name
            # and also change the `breakdown_by` to include that
            # However, because we're already likely joining with the product because
            # we might be filtering on item, we need to be extra safe here and guarantee
            # there's no join with the product table before adding this one
            if query.select_from is not None:
                has_product_join = False
                current_join: ast.JoinExpr | None = query.select_from
                while current_join is not None:
                    if current_join.alias == RevenueAnalyticsProductView.get_generic_view_alias():
                        has_product_join = True
                        break
                    current_join = current_join.next_join

                if not has_product_join:
                    query.select_from = self.append_joins(
                        query.select_from,
                        [self.create_customer_join(customer_subquery)],
                    )

        return query

    def calculate(self):
        response = execute_hogql_query(
            query_type="revenue_analytics_insights_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        # We want the result to look just like the Insights query results look like to simplify our UI
        # First, let's generate all of the dates/labels because they'll be exactly the same for all of the results
        all_dates = self.query_date_range.all_values()
        days = [date.strftime("%Y-%m-%d") for date in all_dates]
        labels = [format_label_date(item, self.query_date_range.interval_name) for item in all_dates]

        # We can also group the results we have by a tuple of (breakdown_by, day_start)
        # This will allow us to easily query the results by breakdown_by and day_start
        # and then we can just add the data to the results
        # [0, 1, 2] -> [value, day_start, breakdown_by]
        grouped_results = {}
        breakdowns = []
        for value, day_start, breakdown_by in response.results:
            # Use array to guarantee insertion order
            if breakdown_by not in breakdowns:
                breakdowns.append(breakdown_by)
            grouped_results[(breakdown_by, day_start.strftime("%Y-%m-%d"))] = value

        results = [
            {
                "action": {"days": all_dates, "id": breakdown, "name": breakdown},
                "data": [grouped_results.get((breakdown, day), 0) for day in days],
                "days": days,
                "label": breakdown,
                "labels": labels,
            }
            for breakdown in breakdowns
        ]

        return RevenueAnalyticsInsightsQueryResponse(
            results=results,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )
