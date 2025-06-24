from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.schema import (
    CachedRevenueAnalyticsInsightsQueryResponse,
    RevenueAnalyticsInsightsQueryResponse,
    RevenueAnalyticsInsightsQuery,
    RevenueAnalyticsInsightsQueryGroupBy,
)
from posthog.utils import format_label_date

from .revenue_analytics_query_runner import (
    RevenueAnalyticsQueryRunner,
)
from products.revenue_analytics.backend.views import (
    RevenueAnalyticsBaseView,
    RevenueAnalyticsChargeView,
    RevenueAnalyticsCustomerView,
    RevenueAnalyticsInvoiceItemView,
    RevenueAnalyticsProductView,
)

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
        _, _, invoice_item_subquery, _ = self.revenue_subqueries
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

        # Limit to 2 group bys at most for performance reasons
        # This is also implemented in the frontend, but let's guarantee it here too
        for group_by in self.query.groupBy[:2]:
            query = self._append_group_by(query, group_by)

        return query

    def _append_group_by(
        self, query: ast.SelectQuery, group_by: RevenueAnalyticsInsightsQueryGroupBy
    ) -> ast.SelectQuery:
        # Join with the subquery to get access to the coalesced field
        # and also change the `breakdown_by` to include that
        join_to, field_name = self._join_to_and_field_name_for_group_by(group_by)

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
                    query.select[0].expr,
                    ast.Constant(value=" - "),
                    ast.Call(
                        name="coalesce",
                        args=[
                            ast.Field(chain=[join_to.get_generic_view_alias(), field_name]),
                            ast.Constant(value=NO_BREAKDOWN_PLACEHOLDER),
                        ],
                    ),
                ],
            )

        # We wanna include a join with the subquery to get the coalesced field
        # and also change the `breakdown_by` to include that
        # However, because we're already likely joining with the subquery because
        # we might be filtering on item, we need to be extra safe here and guarantee
        # there's no join with the subquery before adding this one
        subquery = self._subquery_for_view(join_to)
        if subquery is not None and query.select_from is not None:
            has_subquery_join = False
            current_join: ast.JoinExpr | None = query.select_from
            while current_join is not None:
                if current_join.alias == join_to.get_generic_view_alias():
                    has_subquery_join = True
                    break
                current_join = current_join.next_join

            if not has_subquery_join:
                query.select_from = self.append_joins(
                    query.select_from,
                    [self.create_subquery_join(join_to, subquery)],
                )

        return query

    def _join_to_and_field_name_for_group_by(
        self, group_by: RevenueAnalyticsInsightsQueryGroupBy
    ) -> tuple[type[RevenueAnalyticsBaseView], str]:
        if group_by == RevenueAnalyticsInsightsQueryGroupBy.PRODUCT:
            return RevenueAnalyticsProductView, "name"
        elif group_by == RevenueAnalyticsInsightsQueryGroupBy.COUNTRY:
            return RevenueAnalyticsCustomerView, "country"
        elif group_by == RevenueAnalyticsInsightsQueryGroupBy.COHORT:
            return RevenueAnalyticsCustomerView, "cohort"
        elif group_by == RevenueAnalyticsInsightsQueryGroupBy.COUPON:
            return RevenueAnalyticsInvoiceItemView, "coupon"
        elif group_by == RevenueAnalyticsInsightsQueryGroupBy.COUPON_ID:
            return RevenueAnalyticsInvoiceItemView, "coupon_id"
        elif group_by == RevenueAnalyticsInsightsQueryGroupBy.INITIAL_COUPON:
            return RevenueAnalyticsCustomerView, "initial_coupon"
        elif group_by == RevenueAnalyticsInsightsQueryGroupBy.INITIAL_COUPON_ID:
            return RevenueAnalyticsCustomerView, "initial_coupon_id"
        else:
            raise ValueError(f"Invalid group by: {group_by}")

    def _subquery_for_view(self, view: type[RevenueAnalyticsBaseView]) -> ast.SelectSetQuery | None:
        charge_subquery, customer_subquery, invoice_item_subquery, product_subquery = self.revenue_subqueries
        if view == RevenueAnalyticsProductView:
            return product_subquery
        elif view == RevenueAnalyticsCustomerView:
            return customer_subquery
        elif view == RevenueAnalyticsInvoiceItemView:
            return invoice_item_subquery
        elif view == RevenueAnalyticsChargeView:
            return charge_subquery
        else:
            raise ValueError(f"Invalid view: {view}")

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
