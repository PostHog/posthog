import dataclasses
from collections import defaultdict
from datetime import datetime
from typing import Literal, Optional, Union, cast
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
    RevenueAnalyticsCustomerCountQuery,
    RevenueAnalyticsGroupBy,
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

# This is used to replace the breakdown value when there's no breakdown
NO_BREAKDOWN_PLACEHOLDER = "<none>"

AVAILABLE_JOINS = Literal["customers", "invoice_items", "products"]
PROPERTY_TO_JOIN_MAP: dict[str, AVAILABLE_JOINS] = {
    "source": "customers",
    "amount": "invoice_items",
    "country": "customers",
    "cohort": "customers",
    "coupon": "invoice_items",
    "coupon_id": "invoice_items",
    "initial_coupon": "customers",
    "initial_coupon_id": "customers",
    "product": "products",
}


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
        RevenueAnalyticsCustomerCountQuery,
        RevenueAnalyticsGrowthRateQuery,
        RevenueAnalyticsOverviewQuery,
        RevenueAnalyticsRevenueQuery,
        RevenueAnalyticsTopCustomersQuery,
    ]

    @cached_property
    def where_property_exprs(self) -> list[ast.Expr]:
        return [property_to_expr(property, self.team, scope="revenue_analytics") for property in self.query.properties]

    @cached_property
    def joins_set_for_properties(self) -> set[AVAILABLE_JOINS]:
        joins_set = set()
        for property in self.query.properties:
            if property.key in PROPERTY_TO_JOIN_MAP:
                joins_set.add(PROPERTY_TO_JOIN_MAP[property.key])

        return joins_set

    # This assumes there's a base select coming from the `invoice_items` view
    # and we can then join from that table with the other tables so that's
    # why we'll never see a join for the `invoice_items` table - it's supposed to be there already
    def joins_for_properties(self, join_from: type[RevenueAnalyticsBaseView]) -> list[ast.JoinExpr]:
        joins = []
        for join in self.joins_set_for_properties:
            join_to_add = None
            if join == "customers":
                if self.revenue_subqueries.customer is not None:
                    join_to_add = self._create_customer_join(join_from, self.revenue_subqueries.customer)
            elif join == "invoice_items":
                if self.revenue_subqueries.invoice_item is not None:
                    join_to_add = self._create_invoice_item_join(join_from, self.revenue_subqueries.invoice_item)
            elif join == "products":
                if self.revenue_subqueries.product is not None:
                    join_to_add = self._create_product_join(join_from, self.revenue_subqueries.product)

            if join_to_add is not None:
                joins.append(join_to_add)

        return joins

    # Recursively appends joins to the initial join
    # by using the `next_join` field of the last dangling join
    def _append_joins(self, initial_join: ast.JoinExpr, joins: list[ast.JoinExpr]) -> ast.JoinExpr:
        base_join = initial_join

        # Collect all existing joins aliases so that we don't add duplicates
        existing_joins = [base_join]
        while base_join.next_join is not None:
            base_join = base_join.next_join
            existing_joins.append(base_join)

        # Turn the existing aliases into a set for easy lookup
        # NOTE: This is weird syntax, but it's set comprehension, ruff requires us to use it
        alias_set = {join.alias for join in existing_joins if join.alias is not None}

        # Add all the joins making sure there aren't duplicates
        for join in joins:
            if join.alias is not None:
                if join.alias in alias_set:
                    continue
                alias_set.add(join.alias)

            base_join.next_join = join
            base_join = join

        return initial_join

    def _create_subquery_join(
        self,
        join_from: type[RevenueAnalyticsBaseView],
        join_to: type[RevenueAnalyticsBaseView],
        subquery: ast.SelectQuery | ast.SelectSetQuery,
    ) -> ast.JoinExpr | None:
        if join_to == RevenueAnalyticsProductView:
            return self._create_product_join(join_from, subquery)
        elif join_to == RevenueAnalyticsCustomerView:
            return self._create_customer_join(join_from, subquery)
        elif join_to == RevenueAnalyticsChargeView:
            return self._create_charge_join(join_from, subquery)
        elif join_to == RevenueAnalyticsSubscriptionView:
            return self._create_subscription_join(join_from, subquery)
        elif join_to == RevenueAnalyticsInvoiceItemView:
            return self._create_invoice_item_join(join_from, subquery)
        else:
            raise ValueError(f"Invalid join to: {join_to}")

    def _create_product_join(
        self,
        join_from: type[RevenueAnalyticsBaseView],
        product_subquery: ast.SelectQuery | ast.SelectSetQuery,
    ) -> ast.JoinExpr | None:
        if join_from == RevenueAnalyticsInvoiceItemView or join_from == RevenueAnalyticsSubscriptionView:
            return ast.JoinExpr(
                alias=RevenueAnalyticsProductView.get_generic_view_alias(),
                table=product_subquery,
                join_type="LEFT JOIN",
                constraint=ast.JoinConstraint(
                    constraint_type="ON",
                    expr=ast.CompareOperation(
                        left=ast.Field(chain=[join_from.get_generic_view_alias(), "product_id"]),
                        right=ast.Field(chain=[RevenueAnalyticsProductView.get_generic_view_alias(), "id"]),
                        op=ast.CompareOperationOp.Eq,
                    ),
                ),
            )
        return None

    def _create_customer_join(
        self,
        join_from: type[RevenueAnalyticsBaseView],
        customer_subquery: ast.SelectQuery | ast.SelectSetQuery,
    ) -> ast.JoinExpr | None:
        if join_from == RevenueAnalyticsInvoiceItemView or join_from == RevenueAnalyticsSubscriptionView:
            return ast.JoinExpr(
                alias=RevenueAnalyticsCustomerView.get_generic_view_alias(),
                table=customer_subquery,
                join_type="LEFT JOIN",
                constraint=ast.JoinConstraint(
                    constraint_type="ON",
                    expr=ast.CompareOperation(
                        left=ast.Field(chain=[join_from.get_generic_view_alias(), "customer_id"]),
                        right=ast.Field(chain=[RevenueAnalyticsCustomerView.get_generic_view_alias(), "id"]),
                        op=ast.CompareOperationOp.Eq,
                    ),
                ),
            )
        return None

    def _create_charge_join(
        self,
        join_from: type[RevenueAnalyticsBaseView],
        charge_subquery: ast.SelectQuery | ast.SelectSetQuery,
    ) -> ast.JoinExpr | None:
        if join_from == RevenueAnalyticsInvoiceItemView:
            return ast.JoinExpr(
                alias=RevenueAnalyticsChargeView.get_generic_view_alias(),
                table=charge_subquery,
                join_type="LEFT JOIN",
                constraint=ast.JoinConstraint(
                    constraint_type="ON",
                    expr=ast.CompareOperation(
                        left=ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "charge_id"]),
                        right=ast.Field(chain=[RevenueAnalyticsChargeView.get_generic_view_alias(), "id"]),
                        op=ast.CompareOperationOp.Eq,
                    ),
                ),
            )
        return None

    def _create_subscription_join(
        self,
        join_from: type[RevenueAnalyticsBaseView],
        subscription_subquery: ast.SelectQuery | ast.SelectSetQuery,
    ) -> ast.JoinExpr | None:
        if join_from == RevenueAnalyticsInvoiceItemView:
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
        return None

    def _create_invoice_item_join(
        self,
        join_from: type[RevenueAnalyticsBaseView],
        invoice_item_subquery: ast.SelectQuery | ast.SelectSetQuery,
    ) -> ast.JoinExpr | None:
        if join_from == RevenueAnalyticsSubscriptionView:
            return ast.JoinExpr(
                alias=RevenueAnalyticsInvoiceItemView.get_generic_view_alias(),
                table=invoice_item_subquery,
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
        return None

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

    def _append_group_by(
        self,
        query: ast.SelectQuery,
        join_from: type[RevenueAnalyticsBaseView],
        group_by: RevenueAnalyticsGroupBy,
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
                subquery_join = self._create_subquery_join(join_from, join_to, subquery)
                if subquery_join is not None:
                    query.select_from = self._append_joins(query.select_from, [subquery_join])

        return query

    def _join_to_and_field_name_for_group_by(
        self, group_by: RevenueAnalyticsGroupBy
    ) -> tuple[type[RevenueAnalyticsBaseView], str]:
        if group_by == RevenueAnalyticsGroupBy.PRODUCT:
            return RevenueAnalyticsProductView, "name"
        elif group_by == RevenueAnalyticsGroupBy.COUNTRY:
            return RevenueAnalyticsCustomerView, "country"
        elif group_by == RevenueAnalyticsGroupBy.COHORT:
            return RevenueAnalyticsCustomerView, "cohort"
        elif group_by == RevenueAnalyticsGroupBy.COUPON:
            return RevenueAnalyticsInvoiceItemView, "coupon"
        elif group_by == RevenueAnalyticsGroupBy.COUPON_ID:
            return RevenueAnalyticsInvoiceItemView, "coupon_id"
        elif group_by == RevenueAnalyticsGroupBy.INITIAL_COUPON:
            return RevenueAnalyticsCustomerView, "initial_coupon"
        elif group_by == RevenueAnalyticsGroupBy.INITIAL_COUPON_ID:
            return RevenueAnalyticsCustomerView, "initial_coupon_id"
        else:
            raise ValueError(f"Invalid group by: {group_by}")

    def _subquery_for_view(self, view: type[RevenueAnalyticsBaseView]) -> ast.SelectSetQuery | None:
        if view == RevenueAnalyticsProductView:
            return self.revenue_subqueries.product
        elif view == RevenueAnalyticsCustomerView:
            return self.revenue_subqueries.customer
        elif view == RevenueAnalyticsInvoiceItemView:
            return self.revenue_subqueries.invoice_item
        elif view == RevenueAnalyticsChargeView:
            return self.revenue_subqueries.charge
        elif view == RevenueAnalyticsSubscriptionView:
            return self.revenue_subqueries.subscription
        else:
            raise ValueError(f"Invalid view: {view}")
