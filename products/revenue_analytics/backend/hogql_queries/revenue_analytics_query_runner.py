import dataclasses
from collections import defaultdict
from datetime import datetime
from typing import Optional, Union, cast
from posthog.hogql.property import property_to_expr
from posthog.hogql_queries.query_runner import QueryRunnerWithHogQLContext
from posthog.hogql import ast
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import (
    RevenueAnalyticsGrowthRateQuery,
    RevenueAnalyticsOverviewQuery,
    RevenueAnalyticsRevenueQuery,
    RevenueAnalyticsTopCustomersQuery,
)
from products.revenue_analytics.backend.utils import (
    REVENUE_SELECT_OUTPUT_CHARGE_KEY,
    REVENUE_SELECT_OUTPUT_CUSTOMER_KEY,
    REVENUE_SELECT_OUTPUT_INVOICE_ITEM_KEY,
    REVENUE_SELECT_OUTPUT_PRODUCT_KEY,
    REVENUE_SELECT_OUTPUT_SUBSCRIPTION_KEY,
    revenue_selects_from_database,
)
from products.revenue_analytics.backend.views import (
    RevenueAnalyticsBaseView,
    RevenueAnalyticsChargeView,
    RevenueAnalyticsCustomerView,
    RevenueAnalyticsInvoiceItemView,
    RevenueAnalyticsProductView,
    RevenueAnalyticsSubscriptionView,
)

# If we are running a query that has no date range ("all"/all time),
# we use this as a fallback for the earliest timestamp that we have data for
EARLIEST_TIMESTAMP = datetime.fromisoformat("2015-01-01T00:00:00Z")


@dataclasses.dataclass(frozen=True)
class RevenueSubqueries:
    charge: ast.SelectSetQuery | None
    customer: ast.SelectSetQuery | None
    invoice_item: ast.SelectSetQuery | None
    product: ast.SelectSetQuery | None
    subscription: ast.SelectSetQuery | None


# Base class, empty for now but might include some helpers in the future
class RevenueAnalyticsQueryRunner(QueryRunnerWithHogQLContext):
    query: Union[
        RevenueAnalyticsGrowthRateQuery,
        RevenueAnalyticsOverviewQuery,
        RevenueAnalyticsRevenueQuery,
        RevenueAnalyticsTopCustomersQuery,
    ]

    @cached_property
    def where_property_exprs(self) -> list[ast.Expr]:
        return [property_to_expr(property, self.team, scope="revenue_analytics") for property in self.query.properties]

    @cached_property
    def joins_set_for_properties(self) -> set[str]:
        joins_set = set()
        for property in self.query.properties:
            if property.key == "product":
                joins_set.add("products")
            elif property.key == "country":
                joins_set.add("customers")
            elif property.key == "customer":
                joins_set.add("customers")
        return joins_set

    # This assumes there's a base select coming from the `invoice_items` view
    # and we can then join from that table with the other tables so that's
    # why we'll never see a join for the `invoice_items` table - it's supposed to be there already
    @cached_property
    def joins_for_properties(self) -> list[ast.JoinExpr]:
        joins = []
        for join in self.joins_set_for_properties:
            if join == "products":
                if self.revenue_subqueries.product is not None:
                    joins.append(self.create_product_join(self.revenue_subqueries.product))
            elif join == "customers":
                if self.revenue_subqueries.customer is not None:
                    joins.append(self.create_customer_join(self.revenue_subqueries.customer))

        return joins

    # Recursively appends joins to the initial join
    # by using the `next_join` field of the last dangling join
    def append_joins(self, initial_join: ast.JoinExpr, joins: list[ast.JoinExpr]) -> ast.JoinExpr:
        base_join = initial_join
        for current_join in joins:
            while base_join.next_join is not None:
                base_join = base_join.next_join
            base_join.next_join = current_join
        return initial_join

    # NOTE: It doesn't make sense to join with the `invoice_items` table
    # because it's the base table we're all joining to
    def create_subquery_join(
        self, join_to: type[RevenueAnalyticsBaseView], subquery: ast.SelectQuery | ast.SelectSetQuery
    ) -> ast.JoinExpr:
        if join_to == RevenueAnalyticsProductView:
            return self.create_product_join(subquery)
        elif join_to == RevenueAnalyticsCustomerView:
            return self.create_customer_join(subquery)
        elif join_to == RevenueAnalyticsChargeView:
            return self.create_charge_join(subquery)
        elif join_to == RevenueAnalyticsSubscriptionView:
            return self.create_subscription_join(subquery)
        else:
            raise ValueError(f"Invalid join to: {join_to}")

    def create_product_join(self, product_subquery: ast.SelectQuery | ast.SelectSetQuery) -> ast.JoinExpr:
        return ast.JoinExpr(
            alias=RevenueAnalyticsProductView.get_generic_view_alias(),
            table=product_subquery,
            join_type="LEFT JOIN",
            constraint=ast.JoinConstraint(
                constraint_type="ON",
                expr=ast.CompareOperation(
                    left=ast.Field(chain=[RevenueAnalyticsProductView.get_generic_view_alias(), "id"]),
                    right=ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "product_id"]),
                    op=ast.CompareOperationOp.Eq,
                ),
            ),
        )

    def create_customer_join(self, customer_subquery: ast.SelectQuery | ast.SelectSetQuery) -> ast.JoinExpr:
        return ast.JoinExpr(
            alias=RevenueAnalyticsCustomerView.get_generic_view_alias(),
            table=customer_subquery,
            join_type="LEFT JOIN",
            constraint=ast.JoinConstraint(
                constraint_type="ON",
                expr=ast.CompareOperation(
                    left=ast.Field(chain=[RevenueAnalyticsCustomerView.get_generic_view_alias(), "id"]),
                    right=ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "customer_id"]),
                    op=ast.CompareOperationOp.Eq,
                ),
            ),
        )

    def create_charge_join(self, charge_subquery: ast.SelectQuery | ast.SelectSetQuery) -> ast.JoinExpr:
        return ast.JoinExpr(
            alias=RevenueAnalyticsChargeView.get_generic_view_alias(),
            table=charge_subquery,
            join_type="LEFT JOIN",
            constraint=ast.JoinConstraint(
                constraint_type="ON",
                expr=ast.CompareOperation(
                    left=ast.Field(chain=[RevenueAnalyticsChargeView.get_generic_view_alias(), "id"]),
                    right=ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "charge_id"]),
                    op=ast.CompareOperationOp.Eq,
                ),
            ),
        )

    def create_subscription_join(self, subscription_subquery: ast.SelectQuery | ast.SelectSetQuery) -> ast.JoinExpr:
        return ast.JoinExpr(
            alias=RevenueAnalyticsSubscriptionView.get_generic_view_alias(),
            table=subscription_subquery,
            join_type="LEFT JOIN",
            constraint=ast.JoinConstraint(
                constraint_type="ON",
                expr=ast.CompareOperation(
                    left=ast.Field(chain=[RevenueAnalyticsSubscriptionView.get_generic_view_alias(), "id"]),
                    right=ast.Field(
                        chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "subscription_id"]
                    ),
                    op=ast.CompareOperationOp.Eq,
                ),
            ),
        )

    @cached_property
    def revenue_selects(self) -> defaultdict[str, dict[str, ast.SelectQuery | None]]:
        return revenue_selects_from_database(self.database)

    @cached_property
    def revenue_subqueries(self) -> RevenueSubqueries:
        def parse_selects(select_key: str) -> ast.SelectSetQuery | None:
            queries = [
                cast(ast.SelectQuery, selects[select_key])
                for _, selects in self.revenue_selects.items()
                if selects[select_key] is not None
            ]

            return ast.SelectSetQuery.create_from_queries(queries, set_operator="UNION ALL") if queries else None

        return RevenueSubqueries(
            charge=parse_selects(REVENUE_SELECT_OUTPUT_CHARGE_KEY),
            customer=parse_selects(REVENUE_SELECT_OUTPUT_CUSTOMER_KEY),
            invoice_item=parse_selects(REVENUE_SELECT_OUTPUT_INVOICE_ITEM_KEY),
            product=parse_selects(REVENUE_SELECT_OUTPUT_PRODUCT_KEY),
            subscription=parse_selects(REVENUE_SELECT_OUTPUT_SUBSCRIPTION_KEY),
        )

    @cached_property
    def query_date_range(self):
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=self.query.interval if hasattr(self.query, "interval") else None,
            now=datetime.now(),
            earliest_timestamp_fallback=EARLIEST_TIMESTAMP,
        )

    def timestamp_where_clause(
        self,
        chain: Optional[list[str | int]] = None,
        extra_days_before: int = 0,
    ) -> ast.Expr:
        if chain is None:
            chain = ["timestamp"]

        date_from = self.query_date_range.date_from_as_hogql()
        if extra_days_before > 0:
            date_from = ast.Call(
                name="addDays",
                args=[date_from, ast.Constant(value=-extra_days_before)],
            )
        date_to = self.query_date_range.date_to_as_hogql()

        return ast.Call(
            name="and",
            args=[
                ast.CompareOperation(
                    left=ast.Field(chain=chain),
                    right=date_from,
                    op=ast.CompareOperationOp.GtEq,
                ),
                ast.CompareOperation(
                    left=ast.Field(chain=chain),
                    right=date_to,
                    op=ast.CompareOperationOp.LtEq,
                ),
            ],
        )
