from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from posthog.hogql import ast
from posthog.hogql.database.schema.exchange_rate import EXCHANGE_RATE_DECIMAL_PRECISION
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.utils.timestamp_utils import format_label_date
from posthog.schema import (
    CachedRevenueAnalyticsRevenueQueryResponse,
    HogQLQueryResponse,
    ResolvedDateRangeResponse,
    RevenueAnalyticsRevenueQuery,
    RevenueAnalyticsRevenueQueryResponse,
    RevenueAnalyticsRevenueQueryResult,
    RevenueAnalyticsRevenueQueryResultItem,
)
from products.revenue_analytics.backend.views import RevenueAnalyticsRevenueItemView, RevenueAnalyticsSubscriptionView

from .revenue_analytics_query_runner import (
    RevenueAnalyticsQueryRunner,
)

LOOKBACK_PERIOD_DAYS = 60
LOOKBACK_PERIOD = timedelta(days=LOOKBACK_PERIOD_DAYS)

MRR_EXPIRY_DAYS = 45

ZERO_IN_DECIMAL_PRECISION = ast.Call(
    name="toDecimal",
    args=[ast.Constant(value=0), ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION)],
)
ZERO_PLACEHOLDERS: dict[str, ast.Expr] = {"zero": ZERO_IN_DECIMAL_PRECISION}


class RevenueAnalyticsRevenueQueryRunner(RevenueAnalyticsQueryRunner[RevenueAnalyticsRevenueQueryResponse]):
    query: RevenueAnalyticsRevenueQuery
    cached_response: CachedRevenueAnalyticsRevenueQueryResponse

    # TODO: FIX THIS ONE, JUST NEED TO GROUP BY DATE AND SUM THE VALUES AND THAT'S It
    def to_query(self) -> ast.SelectQuery:
        with self.timings.measure("subquery"):
            subquery = self._get_subquery()
            if subquery is None:
                return ast.SelectQuery.empty(
                    columns=[
                        "breakdown_by",
                        "day_start",
                        "period_start",
                        "is_recurring",
                        "total_value",
                        "new_value",
                        "expansion_value",
                        "contraction_value",
                        "churn_value",
                    ]
                )

        return ast.SelectQuery(
            select=[
                ast.Alias(alias="breakdown_by", expr=ast.Field(chain=["breakdown_by"])),
                ast.Alias(alias="day_start", expr=ast.Field(chain=["day_start"])),
                ast.Alias(alias="period_start", expr=ast.Field(chain=["period_start"])),
                ast.Alias(alias="is_recurring", expr=ast.Field(chain=["is_recurring"])),
                ast.Alias(alias="total_value", expr=ast.Call(name="sum", args=[ast.Field(chain=["total_amount"])])),
                ast.Alias(alias="new_value", expr=ast.Call(name="sum", args=[ast.Field(chain=["new_amount"])])),
                ast.Alias(
                    alias="expansion_value", expr=ast.Call(name="sum", args=[ast.Field(chain=["expansion_amount"])])
                ),
                ast.Alias(
                    alias="contraction_value", expr=ast.Call(name="sum", args=[ast.Field(chain=["contraction_amount"])])
                ),
                ast.Alias(alias="churn_value", expr=ast.Call(name="sum", args=[ast.Field(chain=["churn_amount"])])),
            ],
            select_from=ast.JoinExpr(table=subquery),
            group_by=[
                ast.Field(chain=["day_start"]),
                ast.Field(chain=["period_start"]),
                ast.Field(chain=["breakdown_by"]),
                ast.Field(chain=["is_recurring"]),
            ],
            # Return sorted by period_start/day_start, and then for each individual day we put the maximum first (value)
            # This will allow us to return the list sorted according to the numbers in the first day
            # Finally sort by breakdown_by for the rare cases where they tie (usually at 0 revenue)
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=["period_start"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["day_start"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["total_value"]), order="DESC"),
                ast.OrderExpr(expr=ast.Field(chain=["breakdown_by"]), order="ASC"),
            ],
            # Need a huge limit because we need (dates x breakdown)-many rows to be returned
            limit=ast.Constant(value=10000),
        )

    def _get_subquery(self) -> ast.SelectQuery | None:
        with self.timings.measure("mrr_per_day_subquery"):
            mrr_per_day_subquery = self._mrr_per_day_subquery()
            if mrr_per_day_subquery is None:
                return None

        query = ast.SelectQuery(
            select=[
                ast.Field(chain=["breakdown_by"]),
                ast.Field(chain=["customer_id"]),
                ast.Field(chain=["subscription_id"]),
                ast.Field(chain=["date"]),
                ast.Field(chain=["value"]),
                # Then here compute the changes in MRR
                ast.Alias(
                    alias="previous_value",  # lagInFrame(value) OVER (PARTITION BY breakdown_by, customer_id, subscription_id ORDER BY date ASC)
                    expr=ast.WindowFunction(
                        name="lagInFrame",
                        args=[ast.Field(chain=["value"]), ast.Constant(value=1), ast.Constant(value=None)],
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
                    expr=parse_expr("if(isNull(previous_value), value, {zero})", placeholders=ZERO_PLACEHOLDERS),
                ),
                ast.Alias(
                    alias="expansion_amount",
                    expr=parse_expr(
                        "if(isNotNull(previous_value) AND value > previous_value, value - previous_value, {zero})",
                        placeholders=ZERO_PLACEHOLDERS,
                    ),
                ),
                ast.Alias(
                    alias="contraction_amount",
                    expr=parse_expr(
                        "negate(if(isNotNull(previous_value) AND value < previous_value AND value > 0, previous_value - value, {zero}))",
                        placeholders=ZERO_PLACEHOLDERS,
                    ),
                ),
                ast.Alias(
                    alias="churn_amount",
                    # If no subscription_id, then just assume it's both new (above) and churned (below)
                    # Else, if the amount went to zero, then assume the previous amount is the churned amount
                    # Else, just use 0, it's an ongoing subscription
                    expr=parse_expr(
                        "negate(multiIf(isNull(subscription_id), value, value = 0, coalesce(previous_value, {zero}), {zero}))",
                        placeholders=ZERO_PLACEHOLDERS,
                    ),
                ),
            ],
            select_from=ast.JoinExpr(alias="mrr_per_day_subquery", table=mrr_per_day_subquery),
            where=ast.Or(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["date"]),
                        right=ast.Call(name="toLastDayOfMonth", args=[ast.Field(chain=["date"])]),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["date"]),
                        right=ast.Call(name="today", args=[]),
                    ),
                ]
            ),
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=["breakdown_by"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["customer_id"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["subscription_id"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["date"]), order="ASC"),
            ],
        )

        return query

    # Create a list of (date, customer_id, subscription_id, last_charge, last_charge_date)
    # so that we can know what's our MRR on each day (by summing up the values on each day)
    # This is extremely memory-intensive, but it's the best way to get the MRR to work
    # We'll need to improve this and materialize it in the future
    def _mrr_per_day_subquery(self) -> ast.SelectQuery | None:
        with self.timings.measure("mrr_per_day_subquery"):
            map_query = self._revenue_map_subquery()
            if map_query is None:
                return None

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
                                "toStartOfDay(arrayMap(x -> addDays({start_date}, x), range(-{lookback_period_days}, dateDiff('day', {start_date}, {end_date}) + 1)))",
                                placeholders={
                                    "lookback_period_days": ast.Constant(value=LOOKBACK_PERIOD_DAYS),
                                    "start_date": ast.Constant(value=start_date),
                                    "end_date": ast.Constant(value=end_date),
                                },
                            ),
                        ],
                    ),
                ),
                # Get the current day's charge from map (if any)
                ast.Alias(
                    alias="current_charge",
                    expr=parse_expr(
                        "CASE WHEN mapContains(period_start_map, date) THEN period_start_map[date] ELSE NULL END"
                    ),
                ),
                # Date when the value last changed
                ast.Alias(
                    alias="date_value_changed",
                    expr=parse_expr(
                        "nullIf(maxIf(date, mapContains(period_start_map, date)) OVER (PARTITION BY customer_id, subscription_id ORDER BY date ROWS UNBOUNDED PRECEDING), toDate('1970-01-01'))"
                    ),
                ),
                # Last known value with a custom expiry
                # We need to expiry it eventually because we don't wanna keep counting
                # someone who might have stopped paying us
                # We wouldn't need this if people tidied up their invoice charges
                # and made sure they all included an end day for that charge
                ast.Alias(
                    alias="value",
                    expr=parse_expr(
                        "CASE WHEN date_value_changed IS NULL THEN 0 WHEN dateDiff('day', date_value_changed, date) > {mrr_expiry_days} THEN 0 ELSE coalesce(last_value(current_charge) OVER (PARTITION BY customer_id, subscription_id ORDER BY date ROWS UNBOUNDED PRECEDING), 0) END",
                        placeholders={"mrr_expiry_days": ast.Constant(value=MRR_EXPIRY_DAYS)},
                    ),
                ),
            ],
            select_from=ast.JoinExpr(alias=RevenueAnalyticsRevenueItemView.get_generic_view_alias(), table=map_query),
        )

    # Create a map of (date, amount) for each customer and subscription
    # This is useful because we can use it to know what's the MRR on each day
    def _revenue_map_subquery(self) -> ast.SelectQuery | None:
        with self.timings.measure("revenue_item_subquery"):
            subquery = self._revenue_item_subquery()
            if subquery is None:
                return None

        return ast.SelectQuery(
            select=[
                ast.Alias(
                    name="breakdown_by",
                    expr=ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "source_label"]),
                ),
                ast.Alias(
                    name="customer_id",
                    expr=ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "customer_id"]),
                ),
                ast.Alias(
                    name="subscription_id",
                    expr=ast.Call(
                        name="nullIf",
                        args=[
                            ast.Field(
                                chain=[
                                    RevenueAnalyticsRevenueItemView.get_generic_view_alias(),
                                    "subscription_id",
                                ]
                            ),
                            ast.Constant(value=""),
                        ],
                    ),
                ),
                ast.Alias(
                    name="period_start",
                    expr=ast.Call(
                        name="toStartOfDay",
                        args=[ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "timestamp"])],
                    ),
                ),
                ast.Alias(
                    name="period_start_map",
                    expr=ast.Call(
                        name="mapFromArrays",
                        args=[
                            ast.Call(
                                name="groupArray",
                                args=[
                                    ast.Field(
                                        chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "period_start"]
                                    )
                                ],
                            ),
                            ast.Call(
                                name="groupArray",
                                args=[
                                    ast.Field(
                                        chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "amount"]
                                    )
                                ],
                            ),
                        ],
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                alias=RevenueAnalyticsRevenueItemView.get_generic_view_alias(),
                table=subquery,
            ),
            group_by=[
                ast.Field(chain=["breakdown_by"]),
                ast.Field(chain=["customer_id"]),
                ast.Field(chain=["subscription_id"]),
                ast.Field(chain=["period_start"]),
            ],
        )

    # This is slightly more complicated than normal because we need to include some extra 0-revenue
    # items at the end of the query for all of the subscriptions which ended in this period
    # to allow us to properly calculate churn
    def _revenue_item_subquery(self) -> ast.SelectQuery | ast.SelectSetQuery | None:
        if self.revenue_subqueries.revenue_item is None:
            return None

        revenue_item_subquery = ast.SelectQuery(
            select=[ast.Field(chain=["*"])],
            select_from=ast.JoinExpr(
                alias="inner_revenue_item",
                table=self.revenue_subqueries.revenue_item,
            ),
            where=self.timestamp_where_clause(
                chain=["inner_revenue_item", "ended_at"],
                extra_days_before=LOOKBACK_PERIOD_DAYS,
            ),
        )

        # If there's no subscription subquery, we can just return the revenue item subquery
        if self.revenue_subqueries.subscription is None:
            return revenue_item_subquery

        # This should mimic the same structure as RevenueAnalyticsRevenueItemView, but with hardcoded 0 amount
        # It doesn't NEED to include actual values for all fields, so we're only making effort to include the ones we need above
        # and including empty values for the rest to keep the structure the same
        # @see products/revenue_analytics/backend/views/schemas/revenue_item.py
        churn_revenue_items_select = ast.SelectQuery(
            select=[
                ast.Alias(alias="id", expr=ast.Constant(value=None)),
                ast.Alias(alias="invoice_item_id", expr=ast.Constant(value=None)),
                ast.Alias(
                    alias="source_label",
                    expr=ast.Field(chain=[RevenueAnalyticsSubscriptionView.get_generic_view_alias(), "source_label"]),
                ),
                ast.Alias(
                    alias="timestamp",
                    expr=ast.Field(chain=[RevenueAnalyticsSubscriptionView.get_generic_view_alias(), "ended_at"]),
                ),
                ast.Alias(alias="created_at", expr=ast.Field(chain=["timestamp"])),
                ast.Alias(alias="is_recurring", expr=ast.Constant(value=True)),
                ast.Alias(
                    alias="product_id",
                    expr=ast.Field(chain=[RevenueAnalyticsSubscriptionView.get_generic_view_alias(), "product_id"]),
                ),
                ast.Alias(
                    alias="customer_id",
                    expr=ast.Field(chain=[RevenueAnalyticsSubscriptionView.get_generic_view_alias(), "customer_id"]),
                ),
                ast.Alias(alias="invoice_id", expr=ast.Constant(value=None)),
                ast.Alias(
                    alias="subscription_id",
                    expr=ast.Field(chain=[RevenueAnalyticsSubscriptionView.get_generic_view_alias(), "id"]),
                ),
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
            select_from=ast.JoinExpr(
                alias="inner_subscription",
                table=self.revenue_subqueries.subscription,
            ),
            where=self.timestamp_where_clause(
                chain=["inner_subscription", "ended_at"],
                extra_days_before=LOOKBACK_PERIOD_DAYS,  # Add extra days to ensure MRR calculations are correct
            ),
        )

        # Join the revenue items with the newly created churn items
        return ast.SelectSetQuery.create_from_queries(
            [revenue_item_subquery, churn_revenue_items_select],
            set_operator="UNION ALL",
        )

    def _build_results(self, response: HogQLQueryResponse) -> RevenueAnalyticsRevenueQueryResult:
        # We want the result to look just like the Insights query results look like to simplify our UI
        # First, let's generate all of the dates/labels because they'll be exactly the same for all of the results
        all_dates = self.query_date_range.all_values()
        days = [date.strftime("%Y-%m-%d") for date in all_dates]
        labels = [format_label_date(item, self.query_date_range, self.team.week_start_day) for item in all_dates]

        def _build_result(breakdown: str, kind: str | None, data: list[Decimal]) -> dict:
            label = f"{kind} | {breakdown}" if kind else breakdown
            return {
                "action": {"days": all_dates, "id": label, "name": label},
                "data": data,
                "days": days,
                "label": label,
                "labels": labels,
            }

        # We can also group the results we have by a tuple of (breakdown_by, period_start)
        # This will allow us to easily query the results by breakdown_by and period_start
        # and then we can just add the data to the results
        # [0, 1, 2] -> [value, period_start, breakdown_by]
        grouped_results: defaultdict[tuple[str, str], Decimal] = defaultdict(Decimal)
        breakdowns: list[str] = []
        for (
            breakdown_by,
            _day_start,
            period_start,
            _is_recurring,
            total_value,
            _new_value,
            _expansion_value,
            _contraction_value,
            _churn_value,
        ) in response.results:
            # Use array to guarantee insertion order
            if breakdown_by not in breakdowns:
                breakdowns.append(breakdown_by)
            grouped_results[(breakdown_by, period_start.strftime("%Y-%m-%d"))] += total_value

        gross_results = [
            _build_result(breakdown, None, [grouped_results.get((breakdown, day), Decimal(0)) for day in days])
            for breakdown in breakdowns
        ]

        # Group recurring results by breakdown and sort by day_start
        recurring_by_breakdown: defaultdict[tuple[str, str], list[tuple[datetime, Decimal]]] = defaultdict(list)
        for (
            breakdown_by,
            day_start,
            _period_start,
            is_recurring,
            total_value,
            new_value,
            expansion_value,
            contraction_value,
            churn_value,
        ) in response.results:
            if is_recurring:
                recurring_by_breakdown[("total", breakdown_by)].append((day_start.date(), total_value))
                recurring_by_breakdown[("new", breakdown_by)].append((day_start.date(), new_value))
                recurring_by_breakdown[("expansion", breakdown_by)].append((day_start.date(), expansion_value))
                recurring_by_breakdown[("contraction", breakdown_by)].append((day_start.date(), contraction_value))
                recurring_by_breakdown[("churn", breakdown_by)].append((day_start.date(), churn_value))

        # For each breakdown, calculate MRR using pointer race
        mrr_results: list[RevenueAnalyticsRevenueQueryResultItem] = []
        for breakdown in breakdowns:
            total_events = recurring_by_breakdown[("total", breakdown)]
            total_events.sort(key=lambda x: x[0])
            new_events = recurring_by_breakdown[("new", breakdown)]
            new_events.sort(key=lambda x: x[0])
            expansion_events = recurring_by_breakdown[("expansion", breakdown)]
            expansion_events.sort(key=lambda x: x[0])
            contraction_events = recurring_by_breakdown[("contraction", breakdown)]
            contraction_events.sort(key=lambda x: x[0])
            churn_events = recurring_by_breakdown[("churn", breakdown)]
            churn_events.sort(key=lambda x: x[0])

            # Pointer race algorithm
            start_ptr = 0  # Points to oldest subscription in window
            end_ptr = 0  # Points to next subscription to add

            total_accumulator = Decimal(0)
            new_accumulator = Decimal(0)
            expansion_accumulator = Decimal(0)
            contraction_accumulator = Decimal(0)
            churn_accumulator = Decimal(0)

            total_mrr_data: list[Decimal] = []
            new_mrr_data: list[Decimal] = []
            expansion_mrr_data: list[Decimal] = []
            contraction_mrr_data: list[Decimal] = []
            churn_mrr_data: list[Decimal] = []

            # Process each day in our result set
            for day in days:
                day_date = datetime.strptime(day, "%Y-%m-%d").date()
                lookback_until = day_date - LOOKBACK_PERIOD

                # Move start pointer: remove subscriptions older than 30 days
                while start_ptr < len(total_events) and total_events[start_ptr][0] < lookback_until:
                    total_accumulator -= total_events[start_ptr][1]
                    new_accumulator -= new_events[start_ptr][1]
                    expansion_accumulator -= expansion_events[start_ptr][1]
                    contraction_accumulator -= contraction_events[start_ptr][1]
                    churn_accumulator -= churn_events[start_ptr][1]
                    start_ptr += 1

                # Move end pointer: add subscriptions up to current day
                while end_ptr < len(total_events) and total_events[end_ptr][0] <= day_date:
                    total_accumulator += total_events[end_ptr][1]
                    new_accumulator += new_events[end_ptr][1]
                    expansion_accumulator += expansion_events[end_ptr][1]
                    contraction_accumulator += contraction_events[end_ptr][1]
                    churn_accumulator += churn_events[end_ptr][1]
                    end_ptr += 1

                total_mrr_data.append(total_accumulator)
                new_mrr_data.append(new_accumulator)
                expansion_mrr_data.append(expansion_accumulator)
                contraction_mrr_data.append(contraction_accumulator)
                churn_mrr_data.append(churn_accumulator)

            mrr_results.append(
                RevenueAnalyticsRevenueQueryResultItem(
                    total=_build_result(breakdown, None, total_mrr_data),
                    new=_build_result(breakdown, "New", new_mrr_data),
                    expansion=_build_result(breakdown, "Expansion", expansion_mrr_data),
                    contraction=_build_result(breakdown, "Contraction", contraction_mrr_data),
                    churn=_build_result(breakdown, "Churn", churn_mrr_data),
                )
            )

        return RevenueAnalyticsRevenueQueryResult(gross=gross_results, mrr=mrr_results)

    def _calculate(self):
        with self.timings.measure("to_query"):
            query = self.to_query()

        with self.timings.measure("execute_hogql_query"):
            response = execute_hogql_query(
                query_type="revenue_analytics_revenue_query",
                query=query,
                team=self.team,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        with self.timings.measure("build_results"):
            results = self._build_results(response)

        return RevenueAnalyticsRevenueQueryResponse(
            results=results,
            hogql=response.hogql,
            modifiers=self.modifiers,
            resolved_date_range=ResolvedDateRangeResponse(
                date_from=self.query_date_range.date_from(),
                date_to=self.query_date_range.date_to(),
            ),
        )
