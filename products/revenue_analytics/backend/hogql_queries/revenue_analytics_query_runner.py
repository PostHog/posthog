from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Optional, Union
from zoneinfo import ZoneInfo

from posthog.schema import (
    IntervalType,
    RevenueAnalyticsBreakdown,
    RevenueAnalyticsGrossRevenueQuery,
    RevenueAnalyticsMetricsQuery,
    RevenueAnalyticsMRRQuery,
    RevenueAnalyticsOverviewQuery,
    RevenueAnalyticsPropertyFilter,
    RevenueAnalyticsTopCustomersQuery,
)

from posthog.hogql import ast
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import SavedQuery
from posthog.hogql.property import property_to_expr

from posthog.hogql_queries.query_runner import AR, QueryRunnerWithHogQLContext
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import User
from posthog.models.filters.mixins.utils import cached_property
from posthog.rbac.user_access_control import UserAccessControl

from products.data_warehouse.backend.models import ExternalDataSchema
from products.data_warehouse.backend.types import ExternalDataSourceType
from products.revenue_analytics.backend.views import (
    CHARGE_ALIAS,
    CUSTOMER_ALIAS,
    PRODUCT_ALIAS,
    REVENUE_ITEM_ALIAS,
    SUBSCRIPTION_ALIAS,
    RevenueAnalyticsViewKind,
    get_kind,
    get_kind_alias,
    get_prefix,
    is_event_view,
    is_revenue_analytics_view,
)
from products.revenue_analytics.backend.views.schemas import SCHEMAS as VIEW_SCHEMAS

# This is the placeholder that we use for the breakdown_by field when the breakdown is not present
NO_BREAKDOWN_PLACEHOLDER = "<none>"

# If we are running a query that has no date range ("all"/all time),
# we use this as a fallback for the earliest timestamp that we have data for
EARLIEST_TIMESTAMP = datetime.fromisoformat("2015-01-01T00:00:00Z")

# Not all filter/breakdown properties can be accessed from all views
FILTERS_AVAILABLE_REVENUE_ITEM_VIEW: list[str] = [
    CHARGE_ALIAS,
    CUSTOMER_ALIAS,
    SUBSCRIPTION_ALIAS,
    PRODUCT_ALIAS,
    REVENUE_ITEM_ALIAS,
]

FILTERS_AVAILABLE_SUBSCRIPTION_VIEW: list[str] = [
    CUSTOMER_ALIAS,
    PRODUCT_ALIAS,
    SUBSCRIPTION_ALIAS,
]


class RevenueAnalyticsQueryRunner(QueryRunnerWithHogQLContext[AR]):
    query: Union[
        RevenueAnalyticsMetricsQuery,
        RevenueAnalyticsMRRQuery,
        RevenueAnalyticsGrossRevenueQuery,
        RevenueAnalyticsOverviewQuery,
        RevenueAnalyticsTopCustomersQuery,
    ]

    def validate_query_runner_access(self, user: User) -> bool:
        user_access_control = UserAccessControl(user=user, team=self.team)
        return user_access_control.assert_access_level_for_resource("revenue_analytics", "viewer")

    def where_property_exprs(self, join_from: SavedQuery) -> list[ast.Expr]:
        join_from_kind = get_kind(join_from)
        join_from_alias = get_kind_alias(join_from)

        # Some filters are not namespaced and they should simply use the raw property
        # so let's map them to include the full property with the join_from alias
        mapped_properties = [
            property
            if len(property.key.split(".")) != 1
            else property.model_copy(update={"key": f"{join_from_alias}.{property.key}"})
            for property in self.query.properties
        ]

        return [
            property_to_expr(property, self.team, scope="revenue_analytics")
            for property in mapped_properties
            if self._can_access_property_from(property, join_from_kind)
        ]

    def parsed_breakdown_from(self, join_from_kind: RevenueAnalyticsViewKind | None) -> list[RevenueAnalyticsBreakdown]:
        if not hasattr(self.query, "breakdown"):
            return []

        join_from_alias = join_from_kind if join_from_kind else ""

        # Some breakdowns are not namespaced and they should simply use the raw property
        # so let's map them to include the full property with the join_from alias
        mapped_breakdowns = [
            breakdown
            if len(breakdown.property.split(".")) != 1
            else breakdown.model_copy(update={"property": f"{join_from_alias}.{breakdown.property}"})
            for breakdown in self.query.breakdown
        ]

        # Keep only the ones who can be accessed from the given join_from
        valid_breakdowns = [
            breakdown for breakdown in mapped_breakdowns if self._can_access_breakdown_from(breakdown, join_from_kind)
        ]

        # Limit to 2 breakdowns at most for performance reasons
        return valid_breakdowns[:2]

    def _can_access_property_from(
        self, property: RevenueAnalyticsPropertyFilter, join_from_kind: RevenueAnalyticsViewKind | None
    ) -> bool:
        scopes = property.key.split(".")
        if len(scopes) == 1:
            return True  # Raw access, always allowed

        scope, *_ = scopes
        if join_from_kind == REVENUE_ITEM_ALIAS:
            return scope in FILTERS_AVAILABLE_REVENUE_ITEM_VIEW
        elif join_from_kind == SUBSCRIPTION_ALIAS:
            return scope in FILTERS_AVAILABLE_SUBSCRIPTION_VIEW

        # Everything else is disallowed
        return False

    def _can_access_breakdown_from(
        self, breakdown: RevenueAnalyticsBreakdown, join_from_kind: RevenueAnalyticsViewKind | None
    ) -> bool:
        scopes = breakdown.property.split(".")
        if len(scopes) == 1:
            return True  # Raw access, always allowed

        scope, *_ = scopes
        if join_from_kind == REVENUE_ITEM_ALIAS:
            return scope in FILTERS_AVAILABLE_REVENUE_ITEM_VIEW
        elif join_from_kind == SUBSCRIPTION_ALIAS:
            return scope in FILTERS_AVAILABLE_SUBSCRIPTION_VIEW

        # Everything else is disallowed
        return False

    def _joins_set_for_properties(self, join_from_kind: RevenueAnalyticsViewKind | None) -> set[str]:
        joins_set = set()
        for property in self.query.properties:
            if self._can_access_property_from(property, join_from_kind):
                scope, *_ = property.key.split(".")
                joins_set.add(scope)

        return joins_set

    def _joins_set_for_breakdown(self, join_from_kind: RevenueAnalyticsViewKind | None) -> set[str]:
        joins_set = set()

        for breakdown in self.parsed_breakdown_from(join_from_kind):
            if self._can_access_breakdown_from(breakdown, join_from_kind):
                scope, *_ = breakdown.property.split(".")
                joins_set.add(scope)

        return joins_set

    def _with_where_property_and_breakdown_joins(self, join_expr: ast.JoinExpr, join_from: SavedQuery) -> ast.JoinExpr:
        join_from_kind = get_kind(join_from)
        return self._with_joins(
            join_expr,
            join_from,
            self._joins_set_for_properties(join_from_kind) | self._joins_set_for_breakdown(join_from_kind),
        )

    def _with_where_property_joins(self, join_expr: ast.JoinExpr, join_from: SavedQuery) -> ast.JoinExpr:
        return self._with_joins(join_expr, join_from, self._joins_set_for_properties(get_kind(join_from)))

    def _with_where_breakdown_joins(self, join_expr: ast.JoinExpr, join_from: SavedQuery) -> ast.JoinExpr:
        return self._with_joins(join_expr, join_from, self._joins_set_for_breakdown(get_kind(join_from)))

    def _with_joins(self, join_expr: ast.JoinExpr, join_from: SavedQuery, joins_set: set[str]) -> ast.JoinExpr:
        join_from_kind = get_kind(join_from)
        joins = []
        for join in sorted(joins_set):
            join_to_add: ast.JoinExpr | None = None
            if join == CHARGE_ALIAS and join_from_kind != CHARGE_ALIAS:
                join_to_add = self._create_charge_join(join_from)
            elif join == CUSTOMER_ALIAS and join_from_kind != CUSTOMER_ALIAS:
                join_to_add = self._create_customer_join(join_from)
            elif join == PRODUCT_ALIAS and join_from_kind != PRODUCT_ALIAS:
                join_to_add = self._create_product_join(join_from)
            elif join == REVENUE_ITEM_ALIAS and join_from_kind != REVENUE_ITEM_ALIAS:
                # Can never join TO revenue_item because it's N:N
                pass
            elif join == SUBSCRIPTION_ALIAS and join_from_kind != SUBSCRIPTION_ALIAS:
                join_to_add = self._create_subscription_join(join_from)

            if join_to_add is not None:
                joins.append(join_to_add)

        return self._append_joins(join_expr, joins)

    def _create_charge_join(self, join_from: SavedQuery) -> ast.JoinExpr:
        charge_schema = VIEW_SCHEMAS[CHARGE_ALIAS]
        charge_suffix = charge_schema.events_suffix if is_event_view(join_from) else charge_schema.source_suffix
        join_from_prefix = get_prefix(join_from)

        return ast.JoinExpr(
            alias=CHARGE_ALIAS,
            table=ast.Field(chain=[*join_from_prefix.split("."), charge_suffix]),
            join_type="LEFT JOIN",
            constraint=ast.JoinConstraint(
                constraint_type="ON",
                expr=ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=[get_kind_alias(join_from), "charge_id"]),
                    right=ast.Field(chain=[CHARGE_ALIAS, "id"]),
                ),
            ),
        )

    def _create_customer_join(self, join_from: SavedQuery) -> ast.JoinExpr:
        customer_schema = VIEW_SCHEMAS[CUSTOMER_ALIAS]
        customer_suffix = customer_schema.events_suffix if is_event_view(join_from) else customer_schema.source_suffix
        join_from_prefix = get_prefix(join_from)

        return ast.JoinExpr(
            alias=CUSTOMER_ALIAS,
            table=ast.Field(chain=[*join_from_prefix.split("."), customer_suffix]),
            join_type="LEFT JOIN",
            constraint=ast.JoinConstraint(
                constraint_type="ON",
                expr=ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=[get_kind_alias(join_from), "customer_id"]),
                    right=ast.Field(chain=[CUSTOMER_ALIAS, "id"]),
                ),
            ),
        )

    def _create_product_join(self, join_from: SavedQuery) -> ast.JoinExpr:
        product_schema = VIEW_SCHEMAS[PRODUCT_ALIAS]
        product_suffix = product_schema.events_suffix if is_event_view(join_from) else product_schema.source_suffix
        join_from_prefix = get_prefix(join_from)

        return ast.JoinExpr(
            alias=PRODUCT_ALIAS,
            table=ast.Field(chain=[*join_from_prefix.split("."), product_suffix]),
            join_type="LEFT JOIN",
            constraint=ast.JoinConstraint(
                constraint_type="ON",
                expr=ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=[get_kind_alias(join_from), "product_id"]),
                    right=ast.Field(chain=[PRODUCT_ALIAS, "id"]),
                ),
            ),
        )

    def _create_subscription_join(self, join_from: SavedQuery) -> ast.JoinExpr:
        subscription_schema = VIEW_SCHEMAS[SUBSCRIPTION_ALIAS]
        subscription_suffix = (
            subscription_schema.events_suffix if is_event_view(join_from) else subscription_schema.source_suffix
        )
        join_from_prefix = get_prefix(join_from)

        return ast.JoinExpr(
            alias=SUBSCRIPTION_ALIAS,
            table=ast.Field(chain=[*join_from_prefix.split("."), subscription_suffix]),
            join_type="LEFT JOIN",
            constraint=ast.JoinConstraint(
                constraint_type="ON",
                expr=ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=[get_kind_alias(join_from), "subscription_id"]),
                    right=ast.Field(chain=[SUBSCRIPTION_ALIAS, "id"]),
                ),
            ),
        )

    # Recursively appends joins to the initial join
    # by using the `next_join` field of the last dangling join
    def _append_joins(self, initial_join: ast.JoinExpr, joins: list[ast.JoinExpr]) -> ast.JoinExpr:
        if len(joins) == 0:
            return initial_join

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

    @staticmethod
    def revenue_subqueries(view_kind: RevenueAnalyticsViewKind, database: Database) -> Iterable[SavedQuery]:
        schema = VIEW_SCHEMAS[view_kind]

        for view_name in database.get_view_names():
            if view_name.endswith(schema.source_suffix) or view_name.endswith(schema.events_suffix):
                # To be extra sure we aren't including user-defined queries we assert they're managed by the Revenue Analytics managed viewset
                table = database.get_table(view_name)
                if isinstance(table, SavedQuery) and is_revenue_analytics_view(table):
                    yield table

    @cached_property
    def query_date_range(self):
        # Respect the convertToProjectTimezone modifier for date range calculation
        # When convertToProjectTimezone=False, use UTC for both date boundaries AND column conversion
        timezone_info = self.team.timezone_info if self.modifiers.convertToProjectTimezone else ZoneInfo("UTC")

        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            timezone_info=timezone_info,
            # Can only be either day | month only, simpler implementation
            interval=IntervalType(self.query.interval) if hasattr(self.query, "interval") else None,
            now=datetime.now(timezone_info),
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

    def _dates_expr(self) -> ast.Expr:
        return ast.Call(
            name=f"toStartOf{self.query_date_range.interval_name.title()}",
            args=[
                ast.Call(
                    name="toDateTime",
                    args=[
                        ast.Call(
                            name="arrayJoin",
                            args=[ast.Constant(value=self.query_date_range.all_values())],
                        )
                    ],
                )
            ],
        )

    def _period_lteq_expr(self, left: ast.Expr, right: ast.Expr) -> ast.Expr:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.LtEq,
            left=ast.Call(
                name=f"toStartOf{self.query_date_range.interval_name.title()}",
                args=[left],
            ),
            right=right,
        )

    def _period_eq_expr(self, left: ast.Expr, right: ast.Expr) -> ast.Expr:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Call(
                name=f"toStartOf{self.query_date_range.interval_name.title()}",
                args=[left],
            ),
            right=right,
        )

    def _period_gteq_expr(self, left: ast.Expr, right: ast.Expr) -> ast.Expr:
        return ast.Or(
            exprs=[
                ast.Call(name="isNull", args=[left]),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Call(
                        name=f"toStartOf{self.query_date_range.interval_name.title()}",
                        args=[left],
                    ),
                    right=right,
                ),
            ],
        )

    def _build_breakdown_expr(self, alias: str, field: ast.Field, join_from: SavedQuery) -> ast.Alias:
        expr: ast.Expr = field

        for breakdown in self.parsed_breakdown_from(get_kind(join_from)):
            # dumb assertion because mypy is dumb, praying for ty coming soon
            breakdown_expr = ast.Field(chain=breakdown.property.split("."))  # type: ignore
            expr = ast.Call(
                name="concat",
                args=[
                    expr,
                    ast.Constant(value=" - "),
                    ast.Call(
                        name="if",
                        args=[
                            ast.Or(
                                exprs=[
                                    ast.Call(name="isNull", args=[breakdown_expr]),
                                    ast.Call(name="empty", args=[breakdown_expr]),
                                ]
                            ),
                            ast.Constant(value=NO_BREAKDOWN_PLACEHOLDER),
                            breakdown_expr,
                        ],
                    ),
                ],
            )

        return ast.Alias(alias=alias, expr=expr)

    SMALL_CACHE_TARGET_AGE = timedelta(minutes=1)
    DEFAULT_CACHE_TARGET_AGE = timedelta(hours=6)

    def cache_target_age(self, last_refresh: Optional[datetime], lazy: bool = False) -> Optional[datetime]:
        """
        If we're syncing Revenue data for the first time, cache for `SMALL_CACHE_TARGET_AGE`
        Otherwise, cache it for half the frequency we sync data from Stripe

        If we can't figure out the interval, default to caching for `DEFAULT_CACHE_TARGET_AGE`.
        """
        if last_refresh is None:
            return None

        # All schemas syncing revenue data
        schemas = ExternalDataSchema.objects.filter(
            team=self.team,
            should_sync=True,
            source__source_type=ExternalDataSourceType.STRIPE,
        )

        # If we can detect we're syncing Revenue data for the first time, cache for just 1 minute
        # this guarantees we'll "always" have fresh data for the first sync
        if any(
            schema.status == ExternalDataSchema.Status.RUNNING and schema.last_synced_at is None for schema in schemas
        ):
            return last_refresh + self.SMALL_CACHE_TARGET_AGE

        # Otherwise, let's check the frequency of the schemas that are syncing revenue data
        # In the rare case where we can't figure out the interval, default to caching for 6 hours
        intervals = [schema.sync_frequency_interval for schema in schemas if schema.sync_frequency_interval is not None]
        if not intervals:
            return last_refresh + self.DEFAULT_CACHE_TARGET_AGE

        # If we can figure out the interval, let's cache for half of that
        # to guarantee that - on average - we'll have fresh data for the next sync
        min_interval = min(intervals)
        adjusted_interval = min_interval / 2
        return last_refresh + adjusted_interval
