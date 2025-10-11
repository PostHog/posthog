from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from posthog.schema import (
    CachedRevenueAnalyticsMRRQueryResponse,
    HogQLQueryResponse,
    ResolvedDateRangeResponse,
    RevenueAnalyticsMRRQuery,
    RevenueAnalyticsMRRQueryResponse,
    RevenueAnalyticsMRRQueryResultItem,
)

from posthog.hogql import ast
from posthog.hogql.database.schema.exchange_rate import EXCHANGE_RATE_DECIMAL_PRECISION
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.utils.timestamp_utils import format_label_date

from products.revenue_analytics.backend.views import (
    RevenueAnalyticsBaseView,
    RevenueAnalyticsRevenueItemView,
    RevenueAnalyticsSubscriptionView,
)

from .revenue_analytics_query_runner import RevenueAnalyticsQueryRunner

# How many days to look back to calculate initial MRR, needs to be at least 30 to get all
# of the subscriptions from the previous period. Erring on the side of caution here.
LOOKBACK_PERIOD_DAYS = 60

# How many days to keep a subscription's MRR in the database while it hasn't been tagged as churned yet
# but no new charges have been made. This should be made customizable in the future.
# It already is customizable for events, but not for DWH sources.
MRR_EXPIRY_DAYS = 45

# We need to use "Zero" in several places where we need a default, so let's just create one in here and reuse it
ZERO_IN_DECIMAL_PRECISION = ast.Call(
    name="toDecimal",
    args=[ast.Constant(value=0), ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION)],
)
ZERO_PLACEHOLDERS: dict[str, ast.Expr] = {"zero": ZERO_IN_DECIMAL_PRECISION}


class RevenueAnalyticsMRRQueryRunner(RevenueAnalyticsQueryRunner[RevenueAnalyticsMRRQueryResponse]):
    query: RevenueAnalyticsMRRQuery
    cached_response: CachedRevenueAnalyticsMRRQueryResponse

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        subqueries = list(self.revenue_subqueries(RevenueAnalyticsRevenueItemView))
        if not subqueries:
            return ast.SelectQuery.empty(columns=["breakdown_by", "period_start", "amount"])

        queries = [self._to_query_from(subquery) for subquery in subqueries]
        return ast.SelectSetQuery.create_from_queries(queries, set_operator="UNION ALL")

    def _to_query_from(self, view: RevenueAnalyticsBaseView) -> ast.SelectQuery:
        with self.timings.measure("subquery"):
            subquery = self._get_subquery(view)

        return ast.SelectQuery(
            select=[
                ast.Alias(alias="breakdown_by", expr=ast.Field(chain=["breakdown_by"])),
                ast.Alias(alias="date", expr=ast.Field(chain=["date"])),
                ast.Alias(alias="total", expr=ast.Call(name="sum", args=[ast.Field(chain=["amount"])])),
                ast.Alias(alias="new", expr=ast.Call(name="sum", args=[ast.Field(chain=["new_amount"])])),
                ast.Alias(alias="expansion", expr=ast.Call(name="sum", args=[ast.Field(chain=["expansion_amount"])])),
                ast.Alias(
                    alias="contraction", expr=ast.Call(name="sum", args=[ast.Field(chain=["contraction_amount"])])
                ),
                ast.Alias(alias="churn", expr=ast.Call(name="sum", args=[ast.Field(chain=["churn_amount"])])),
            ],
            select_from=ast.JoinExpr(table=subquery),
            # Finally, cleanup the dates we don't care and only used to calculate MRR
            where=self.timestamp_where_clause(chain=["date"]),
            group_by=[
                ast.Field(chain=["breakdown_by"]),
                ast.Field(chain=["date"]),
            ],
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=["date"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["total"]), order="DESC"),
                ast.OrderExpr(expr=ast.Field(chain=["breakdown_by"]), order="ASC"),
            ],
            # Need a huge limit because we need (# periods x # breakdowns)-many rows to be returned
            limit=ast.Constant(value=10000),
        )

    def _get_subquery(self, view: RevenueAnalyticsBaseView) -> ast.SelectQuery:
        with self.timings.measure("mrr_per_day_subquery"):
            mrr_per_day_subquery = self._mrr_per_day_subquery(view)

        query = ast.SelectQuery(
            select=[
                ast.Field(chain=["breakdown_by"]),
                ast.Field(chain=["customer_id"]),
                ast.Field(chain=["subscription_id"]),
                ast.Field(chain=["date"]),
                ast.Field(chain=["amount"]),
                # Then here compute the changes in MRR
                # lagInFrame(amount, 1, toDecimal(0, 10)) OVER (PARTITION BY breakdown_by, customer_id, subscription_id ORDER BY date ASC)
                ast.Alias(
                    alias="previous_amount",
                    expr=ast.WindowFunction(
                        name="lagInFrame",
                        exprs=[
                            ast.Field(chain=["amount"]),
                            ast.Constant(value=1),
                            ast.Call(name="assumeNotNull", args=[ZERO_IN_DECIMAL_PRECISION]),
                        ],
                        over_expr=ast.WindowExpr(
                            partition_by=[
                                ast.Field(chain=["breakdown_by"]),
                                ast.Field(chain=["customer_id"]),
                                ast.Field(chain=["subscription_id"]),
                            ],
                            order_by=[ast.OrderExpr(expr=ast.Field(chain=["date"]), order="ASC")],
                            frame_method="ROWS",
                            frame_start=ast.WindowFrameExpr(frame_type="PRECEDING"),
                            frame_end=ast.WindowFrameExpr(frame_type="FOLLOWING"),
                        ),
                    ),
                ),
                ast.Alias(
                    alias="new_amount",
                    expr=parse_expr(
                        "if(previous_amount = 0, amount, {zero})",
                        placeholders=ZERO_PLACEHOLDERS,
                    ),
                ),
                ast.Alias(
                    alias="expansion_amount",
                    expr=parse_expr(
                        "if(previous_amount > 0 AND amount > previous_amount, amount - previous_amount, {zero})",
                        placeholders=ZERO_PLACEHOLDERS,
                    ),
                ),
                ast.Alias(
                    alias="contraction_amount",
                    expr=parse_expr(
                        "negate(if(previous_amount > 0 AND amount > 0 AND amount < previous_amount, previous_amount - amount, {zero}))",
                        placeholders=ZERO_PLACEHOLDERS,
                    ),
                ),
                ast.Alias(
                    alias="churn_amount",
                    # If no subscription_id, then just assume it's both new (above) and churned (below)
                    # Else, if the amount went to zero, then assume the previous amount is the churned amount
                    # Else, just use 0, it's an ongoing subscription
                    expr=parse_expr(
                        "negate(multiIf(isNull(subscription_id), amount, amount = 0, previous_amount, {zero}))",
                        placeholders=ZERO_PLACEHOLDERS,
                    ),
                ),
            ],
            select_from=ast.JoinExpr(alias="mrr_per_day_subquery", table=mrr_per_day_subquery),
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=["breakdown_by"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["customer_id"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["subscription_id"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["date"]), order="ASC"),
            ],
        )

        # If we're filtering by month, then keep only the last day of each month in the query
        # plus the last entry for each group of breakdown_by, customer_id, subscription_id
        # counted by the `row_number` column above
        #
        # This can't be added directly as a `where` clause because it uses a window function
        if self.query_date_range.interval_name == "month":
            query.where = ast.Or(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["date"]),
                        right=ast.Call(name="toLastDayOfMonth", args=[ast.Field(chain=["date"])]),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["row_number"]),
                        right=ast.Constant(value=1),
                    ),
                ]
            )

        return query

    # Create a list of (date, customer_id, subscription_id, last_charge, last_charge_date)
    # so that we can know what's our MRR on each day (by summing up the amounts on each day)
    # This is extremely memory-intensive, but it's the best way to get the MRR to work
    # We'll need to improve this and materialize it in the future
    def _mrr_per_day_subquery(self, view: RevenueAnalyticsBaseView) -> ast.SelectQuery:
        with self.timings.measure("mrr_per_day_subquery"):
            map_query = self._revenue_map_subquery(view)

        # Get all of the days in the date range,
        # this is useful because we can use it to know what's the MRR on each day
        start_date = self.query_date_range.date_from()
        end_date = self.query_date_range.date_to()

        return ast.SelectQuery(
            select=[
                # Just copy breakdown_by, customer, subscription id over
                ast.Alias(alias="breakdown_by", expr=ast.Field(chain=["breakdown_by"])),
                ast.Alias(alias="customer_id", expr=ast.Field(chain=["customer_id"])),
                ast.Alias(alias="subscription_id", expr=ast.Field(chain=["subscription_id"])),
                # Create a list of dates from the start to the end of the date range
                # This is useful because we can use it to know what's the MRR on each day
                ast.Alias(
                    alias="date",
                    expr=ast.Call(
                        name="arrayJoin",
                        args=[
                            parse_expr(
                                "arrayMap(x -> toStartOfDay(addDays({start_date}, x)), range(-{lookback_period_days}, dateDiff('day', {start_date}, {end_date}) + 1))",
                                placeholders={
                                    "lookback_period_days": ast.Constant(value=LOOKBACK_PERIOD_DAYS),
                                    "start_date": ast.Call(name="toStartOfDay", args=[ast.Constant(value=start_date)]),
                                    "end_date": ast.Constant(value=end_date),
                                },
                            ),
                        ],
                    ),
                ),
                # We will always want to keep the last row even when filtering by month, so let's get that here
                ast.Alias(
                    alias="row_number",
                    expr=parse_expr(
                        "ROW_NUMBER() OVER (PARTITION BY breakdown_by, customer_id, subscription_id ORDER BY date DESC)"
                    ),
                ),
                # Make sure that the date is a string, otherwise the map operations will fail
                ast.Alias(
                    alias="date_string",
                    expr=ast.Call(name="toString", args=[ast.Field(chain=["date"])]),
                ),
                # Get the current day's amount from map (if any)
                ast.Alias(
                    alias="date_amount",
                    expr=parse_expr("if(mapContains(amount_map, date_string), amount_map[date_string], NULL)"),
                ),
                # Date when the amount last changed
                ast.Alias(
                    alias="date_amount_changed",
                    expr=parse_expr(
                        "nullIf(maxIf(date, mapContains(amount_map, date_string)) OVER (PARTITION BY breakdown_by, customer_id, subscription_id ORDER BY date ROWS UNBOUNDED PRECEDING), toDate('1970-01-01'))"
                    ),
                ),
                # Last known amount with a custom expiry
                # We need to expiry it eventually because we don't wanna keep counting
                # someone who might have stopped paying us
                # We wouldn't need this if people tidied up their invoice charges
                # and made sure they all included an end day for that charge
                ast.Alias(
                    alias="amount",
                    expr=parse_expr(
                        "CASE WHEN date_amount_changed IS NULL THEN 0 WHEN dateDiff('day', date_amount_changed, date) > {mrr_expiry_days} THEN 0 ELSE coalesce(last_value(date_amount) OVER (PARTITION BY breakdown_by, customer_id, subscription_id ORDER BY date ROWS UNBOUNDED PRECEDING), 0) END",
                        placeholders={"mrr_expiry_days": ast.Constant(value=MRR_EXPIRY_DAYS)},
                    ),
                ),
            ],
            select_from=ast.JoinExpr(alias="map_query", table=map_query),
        )

    # Create a map of (date, amount) for each customer and subscription
    # This is useful because we can use it to know what's the MRR on each day
    def _revenue_map_subquery(self, view: RevenueAnalyticsBaseView) -> ast.SelectQuery:
        with self.timings.measure("revenue_item_subquery"):
            subquery = self._revenue_item_subquery(view)

        # First, we need to group by day and sum the amounts
        grouped_by_day = ast.SelectQuery(
            select=[
                ast.Alias(alias="breakdown_by", expr=ast.Field(chain=["subquery", "breakdown_by"])),
                ast.Alias(alias="customer_id", expr=ast.Field(chain=["subquery", "customer_id"])),
                ast.Alias(
                    alias="subscription_id",
                    expr=ast.Call(
                        name="nullIf", args=[ast.Field(chain=["subquery", "subscription_id"]), ast.Constant(value="")]
                    ),
                ),
                ast.Alias(
                    alias="day", expr=ast.Call(name="toStartOfDay", args=[ast.Field(chain=["subquery", "timestamp"])])
                ),
                ast.Alias(alias="amount", expr=ast.Call(name="sum", args=[ast.Field(chain=["subquery", "amount"])])),
            ],
            select_from=ast.JoinExpr(alias="subquery", table=subquery),
            group_by=[
                ast.Field(chain=["breakdown_by"]),
                ast.Field(chain=["customer_id"]),
                ast.Field(chain=["subscription_id"]),
                ast.Field(chain=["day"]),
            ],
        )

        # Then, we need to create a map of (date, amount) for each customer and subscription
        # This is useful because we can use it to know what's the MRR on each day
        return ast.SelectQuery(
            select=[
                ast.Alias(alias="breakdown_by", expr=ast.Field(chain=["grouped_by_day", "breakdown_by"])),
                ast.Alias(alias="customer_id", expr=ast.Field(chain=["grouped_by_day", "customer_id"])),
                ast.Alias(alias="subscription_id", expr=ast.Field(chain=["grouped_by_day", "subscription_id"])),
                ast.Alias(
                    alias="amount_map",
                    expr=ast.Call(
                        name="ifNull",
                        args=[
                            ast.Call(
                                name="mapFromArrays",
                                args=[
                                    ast.Call(
                                        name="groupArray",
                                        args=[
                                            ast.Call(name="toString", args=[ast.Field(chain=["grouped_by_day", "day"])])
                                        ],
                                    ),
                                    ast.Call(
                                        name="groupArray",
                                        args=[
                                            ast.Call(
                                                name="toNullable", args=[ast.Field(chain=["grouped_by_day", "amount"])]
                                            )
                                        ],
                                    ),
                                ],
                            ),
                            # Empty map with the right types, but dummy values
                            ast.Call(
                                name="map",
                                args=[
                                    ast.Constant(value=""),
                                    ast.Call(name="toNullable", args=[ZERO_IN_DECIMAL_PRECISION]),
                                ],
                            ),
                        ],
                    ),
                ),
            ],
            select_from=ast.JoinExpr(alias="grouped_by_day", table=grouped_by_day),
            group_by=[
                ast.Field(chain=["breakdown_by"]),
                ast.Field(chain=["customer_id"]),
                ast.Field(chain=["subscription_id"]),
            ],
        )

    # This is slightly more complicated than normal because we need to include some extra 0-revenue
    # items at the end of the query for all of the subscriptions which ended in this period
    # to allow us to properly calculate churn
    def _revenue_item_subquery(self, view: RevenueAnalyticsBaseView) -> ast.SelectQuery | ast.SelectSetQuery:
        queries: list[ast.SelectQuery | ast.SelectSetQuery] = [
            ast.SelectQuery(
                select=[ast.Field(chain=["*"])],
                select_from=ast.JoinExpr(table=ast.Field(chain=[view.name])),
            ),
        ]

        subscription_views = self.revenue_subqueries(RevenueAnalyticsSubscriptionView)
        subscription_view = next(
            (subscription_view for subscription_view in subscription_views if subscription_view.prefix == view.prefix),
            None,
        )

        # If there's a subscription subquery, then add it to the list of queries
        #
        # This should mimic the same structure as RevenueAnalyticsRevenueItemView, but with hardcoded 0 amount
        # It doesn't NEED to include actual values for all fields, so we're only making effort to include the ones we need above
        # and including empty values for the rest to keep the structure the same
        # @see products/revenue_analytics/backend/views/schemas/revenue_item.py
        if subscription_view is not None:
            churn_revenue_items_select = ast.SelectQuery(
                select=[
                    ast.Alias(alias="id", expr=ast.Constant(value=None)),
                    ast.Alias(alias="invoice_item_id", expr=ast.Constant(value=None)),
                    ast.Alias(alias="source_label", expr=ast.Field(chain=["subscription", "source_label"])),
                    ast.Alias(alias="timestamp", expr=ast.Field(chain=["subscription", "ended_at"])),
                    ast.Alias(alias="created_at", expr=ast.Field(chain=["timestamp"])),
                    ast.Alias(alias="is_recurring", expr=ast.Constant(value=True)),
                    ast.Alias(alias="product_id", expr=ast.Field(chain=["subscription", "product_id"])),
                    ast.Alias(alias="customer_id", expr=ast.Field(chain=["subscription", "customer_id"])),
                    ast.Alias(alias="group_0_key", expr=ast.Constant(value=None)),
                    ast.Alias(alias="group_1_key", expr=ast.Constant(value=None)),
                    ast.Alias(alias="group_2_key", expr=ast.Constant(value=None)),
                    ast.Alias(alias="group_3_key", expr=ast.Constant(value=None)),
                    ast.Alias(alias="group_4_key", expr=ast.Constant(value=None)),
                    ast.Alias(alias="invoice_id", expr=ast.Constant(value=None)),
                    ast.Alias(alias="subscription_id", expr=ast.Field(chain=["subscription", "id"])),
                    ast.Alias(alias="session_id", expr=ast.Constant(value=None)),
                    ast.Alias(alias="event_name", expr=ast.Constant(value=None)),
                    ast.Alias(alias="coupon", expr=ast.Constant(value=None)),
                    ast.Alias(alias="coupon_id", expr=ast.Constant(value=None)),
                    ast.Alias(alias="original_currency", expr=ast.Constant(value=None)),
                    ast.Alias(alias="original_amount", expr=ZERO_IN_DECIMAL_PRECISION),
                    ast.Alias(alias="enable_currency_aware_divider", expr=ast.Constant(value=False)),
                    ast.Alias(alias="currency_aware_divider", expr=ZERO_IN_DECIMAL_PRECISION),
                    ast.Alias(alias="currency_aware_amount", expr=ZERO_IN_DECIMAL_PRECISION),
                    ast.Alias(alias="currency", expr=ast.Constant(value=None)),
                    ast.Alias(alias="amount", expr=ZERO_IN_DECIMAL_PRECISION),
                ],
                select_from=ast.JoinExpr(alias="subscription", table=ast.Field(chain=[subscription_view.name])),
                # Add extra days to ensure MRR calculations are correct
                where=self.timestamp_where_clause(
                    chain=["subscription", "ended_at"], extra_days_before=LOOKBACK_PERIOD_DAYS
                ),
            )

            queries.append(churn_revenue_items_select)

        # Join the revenue items with the possible created churn items
        base_query: ast.SelectQuery | ast.SelectSetQuery
        if len(queries) == 1:
            base_query = queries[0]
        else:
            base_query = ast.SelectSetQuery.create_from_queries(
                queries,
                set_operator="UNION ALL",
            )

        query = ast.SelectQuery(
            select=[
                self._build_breakdown_expr(
                    "breakdown_by",
                    ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "source_label"]),
                    view,
                ),
                ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "customer_id"]),
                ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "subscription_id"]),
                ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "timestamp"]),
                ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "amount"]),
            ],
            select_from=self._with_where_property_and_breakdown_joins(
                ast.JoinExpr(
                    alias=RevenueAnalyticsRevenueItemView.get_generic_view_alias(),
                    table=base_query,
                ),
                view,
            ),
            where=ast.And(
                exprs=[
                    self.timestamp_where_clause(
                        chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "timestamp"],
                        extra_days_before=LOOKBACK_PERIOD_DAYS,
                    ),
                    # Only care about recurring events because this is MRR after all
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(
                            chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "is_recurring"]
                        ),
                        right=ast.Constant(value=True),
                    ),
                    *self.where_property_exprs(view),
                ]
            ),
        )

        return query

    # We want the result to look just like the Insights query results look like to simplify our UI
    def _build_results(self, response: HogQLQueryResponse) -> list[RevenueAnalyticsMRRQueryResultItem]:
        # We group the results we have by a tuple of (breakdown_by, date)
        # This will allow us to easily query the results by breakdown_by and date
        # and then we can just add the data to the results
        grouped_results: defaultdict[str, dict[str, tuple[Decimal, Decimal, Decimal, Decimal, Decimal]]] = defaultdict(
            dict
        )
        breakdowns: list[str] = []
        formatted_dates: list[str] = []
        dates: list[datetime] = []
        for breakdown, date, total, new, expansion, contraction, churn in response.results:
            # Use array to guarantee insertion order
            if breakdown not in breakdowns:
                breakdowns.append(breakdown)

            formatted_date = date.strftime("%Y-%m-%d")
            if formatted_date not in formatted_dates:
                formatted_dates.append(formatted_date)
                dates.append(date)

            grouped_results[breakdown][formatted_date] = (
                total,
                new,
                expansion,
                contraction,
                churn,
            )

        labels = [format_label_date(date, self.query_date_range, self.team.week_start_day) for date in dates]

        def _build_result(breakdown: str, *, kind: str | None = None) -> dict:
            label = f"{kind} | {breakdown}" if kind else breakdown
            index = {
                None: 0,
                "New": 1,
                "Expansion": 2,
                "Contraction": 3,
                "Churn": 4,
            }.get(kind, 0)

            results = grouped_results[breakdown]
            data = [results[date][index] for date in formatted_dates]
            return {
                "action": {"days": dates, "id": label, "name": label},
                "breakdown": {"property": breakdown, "kind": kind},
                "data": data,
                "days": formatted_dates,
                "label": label,
                "labels": labels,
            }

        return [
            RevenueAnalyticsMRRQueryResultItem(
                total=_build_result(breakdown),
                new=_build_result(breakdown, kind="New"),
                expansion=_build_result(breakdown, kind="Expansion"),
                contraction=_build_result(breakdown, kind="Contraction"),
                churn=_build_result(breakdown, kind="Churn"),
            )
            for breakdown in breakdowns
        ]

    def _calculate(self):
        with self.timings.measure("to_query"):
            query = self.to_query()

        with self.timings.measure("execute_hogql_query"):
            response = execute_hogql_query(
                query_type="revenue_analytics_mrr_query",
                query=query,
                team=self.team,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        with self.timings.measure("build_results"):
            results = self._build_results(response)

        return RevenueAnalyticsMRRQueryResponse(
            results=results,
            hogql=response.hogql,
            modifiers=self.modifiers,
            resolved_date_range=ResolvedDateRangeResponse(
                date_from=self.query_date_range.date_from(),
                date_to=self.query_date_range.date_to(),
            ),
        )
