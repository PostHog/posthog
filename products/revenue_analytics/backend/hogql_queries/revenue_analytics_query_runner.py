from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Optional, Union
from zoneinfo import ZoneInfo

from posthog.schema import (
    DatabaseSchemaManagedViewTableKind,
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
from products.data_warehouse.backend.types import DataWarehouseManagedViewSetKind, ExternalDataSourceType
from products.revenue_analytics.backend.views import (
    RevenueAnalyticsBaseView,
    RevenueAnalyticsChargeView,
    RevenueAnalyticsCustomerView,
    RevenueAnalyticsProductView,
    RevenueAnalyticsRevenueItemView,
    RevenueAnalyticsSubscriptionView,
)
from products.revenue_analytics.backend.views.schemas import (
    SCHEMAS as VIEW_SCHEMAS,
    Schema as RevenueAnalyticsSchema,
)

# This is the placeholder that we use for the breakdown_by field when the breakdown is not present
NO_BREAKDOWN_PLACEHOLDER = "<none>"

# If we are running a query that has no date range ("all"/all time),
# we use this as a fallback for the earliest timestamp that we have data for
EARLIEST_TIMESTAMP = datetime.fromisoformat("2015-01-01T00:00:00Z")

# Not all filter/breakdown properties can be accessed from all views
FILTERS_AVAILABLE_REVENUE_ITEM_VIEW: list[DatabaseSchemaManagedViewTableKind] = [
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CHARGE,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_SUBSCRIPTION,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_PRODUCT,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM,
]

FILTERS_AVAILABLE_SUBSCRIPTION_VIEW: list[DatabaseSchemaManagedViewTableKind] = [
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_PRODUCT,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_SUBSCRIPTION,
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

    def where_property_exprs(self, join_from: RevenueAnalyticsBaseView) -> list[ast.Expr]:
        # Some filters are not namespaced and they should simply use the raw property
        # so let's map them to include the full property with the join_from alias
        mapped_properties = [
            property
            if len(property.key.split(".")) != 1
            else property.model_copy(update={"key": f"{join_from.get_generic_view_alias()}.{property.key}"})
            for property in self.query.properties
        ]

        return [
            property_to_expr(property, self.team, scope="revenue_analytics")
            for property in mapped_properties
            if self._can_access_property_from(property, join_from.__class__)
        ]

    def parsed_breakdown_from(self, join_from: type[RevenueAnalyticsBaseView]) -> list[RevenueAnalyticsBreakdown]:
        if not hasattr(self.query, "breakdown"):
            return []

        # Some breakdowns are not namespaced and they should simply use the raw property
        # so let's map them to include the full property with the join_from alias
        mapped_breakdowns = [
            breakdown
            if len(breakdown.property.split(".")) != 1
            else breakdown.model_copy(update={"property": f"{join_from.get_generic_view_alias()}.{breakdown.property}"})
            for breakdown in self.query.breakdown
        ]

        # Keep only the ones who can be accessed from the given join_from
        valid_breakdowns = [
            breakdown for breakdown in mapped_breakdowns if self._can_access_breakdown_from(breakdown, join_from)
        ]

        # Limit to 2 breakdowns at most for performance reasons
        return valid_breakdowns[:2]

    def _can_access_property_from(
        self, property: RevenueAnalyticsPropertyFilter, join_from: type[RevenueAnalyticsBaseView]
    ) -> bool:
        scopes = property.key.split(".")
        if len(scopes) == 1:
            return True  # Raw access, always allowed

        scope, *_ = scopes
        if join_from == RevenueAnalyticsRevenueItemView:
            return scope in FILTERS_AVAILABLE_REVENUE_ITEM_VIEW
        elif join_from == RevenueAnalyticsSubscriptionView:
            return scope in FILTERS_AVAILABLE_SUBSCRIPTION_VIEW

        # Everything else is disallowed
        return False

    def _can_access_breakdown_from(
        self, breakdown: RevenueAnalyticsBreakdown, join_from: type[RevenueAnalyticsBaseView]
    ) -> bool:
        scopes = breakdown.property.split(".")
        if len(scopes) == 1:
            return True  # Raw access, always allowed

        scope, *_ = scopes
        if join_from == RevenueAnalyticsRevenueItemView:
            return scope in FILTERS_AVAILABLE_REVENUE_ITEM_VIEW
        elif join_from == RevenueAnalyticsSubscriptionView:
            return scope in FILTERS_AVAILABLE_SUBSCRIPTION_VIEW

        # Everything else is disallowed
        return False

    def _joins_set_for_properties(self, join_from: type[RevenueAnalyticsBaseView]) -> set[str]:
        joins_set = set()
        for property in self.query.properties:
            if self._can_access_property_from(property, join_from):
                scope, *_ = property.key.split(".")
                joins_set.add(scope)

        return joins_set

    def _joins_set_for_breakdown(self, join_from: type[RevenueAnalyticsBaseView]) -> set[str]:
        joins_set = set()

        for breakdown in self.parsed_breakdown_from(join_from):
            if self._can_access_breakdown_from(breakdown, join_from):
                scope, *_ = breakdown.property.split(".")
                joins_set.add(scope)

        return joins_set

    def _with_where_property_and_breakdown_joins(
        self, join_expr: ast.JoinExpr, join_from: RevenueAnalyticsBaseView
    ) -> ast.JoinExpr:
        return self._with_joins(
            join_expr,
            join_from,
            self._joins_set_for_properties(join_from.__class__) | self._joins_set_for_breakdown(join_from.__class__),
        )

    def _with_where_property_joins(self, join_expr: ast.JoinExpr, join_from: RevenueAnalyticsBaseView) -> ast.JoinExpr:
        return self._with_joins(join_expr, join_from, self._joins_set_for_properties(join_from.__class__))

    def _with_where_breakdown_joins(self, join_expr: ast.JoinExpr, join_from: RevenueAnalyticsBaseView) -> ast.JoinExpr:
        return self._with_joins(join_expr, join_from, self._joins_set_for_breakdown(join_from.__class__))

    def _with_joins(
        self, join_expr: ast.JoinExpr, join_from: RevenueAnalyticsBaseView, joins_set: set[str]
    ) -> ast.JoinExpr:
        joins = []
        for join in sorted(joins_set):
            join_to_add: ast.JoinExpr | None = None
            if join == "revenue_analytics_charge" and join_from.__class__ != RevenueAnalyticsChargeView:
                join_to_add = self._create_charge_join(join_from)
            elif join == "revenue_analytics_customer" and join_from.__class__ != RevenueAnalyticsCustomerView:
                join_to_add = self._create_customer_join(join_from)
            elif join == "revenue_analytics_product" and join_from.__class__ != RevenueAnalyticsProductView:
                join_to_add = self._create_product_join(join_from)
            elif join == "revenue_analytics_revenue_item" and join_from.__class__ != RevenueAnalyticsRevenueItemView:
                # Can never join TO revenue_item because it's N:N
                pass
            elif join == "revenue_analytics_subscription" and join_from.__class__ != RevenueAnalyticsSubscriptionView:
                join_to_add = self._create_subscription_join(join_from)

            if join_to_add is not None:
                joins.append(join_to_add)

        return self._append_joins(join_expr, joins)

    def _create_charge_join(self, join_from: RevenueAnalyticsBaseView) -> ast.JoinExpr:
        charge_schema = VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CHARGE]
        charge_suffix = charge_schema.events_suffix if join_from.is_event_view() else charge_schema.source_suffix

        return ast.JoinExpr(
            alias=RevenueAnalyticsChargeView.get_generic_view_alias(),
            table=ast.Field(chain=[*join_from.prefix.split("."), charge_suffix]),
            join_type="LEFT JOIN",
            constraint=ast.JoinConstraint(
                constraint_type="ON",
                expr=ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=[join_from.get_generic_view_alias(), "charge_id"]),
                    right=ast.Field(chain=[RevenueAnalyticsChargeView.get_generic_view_alias(), "id"]),
                ),
            ),
        )

    def _create_customer_join(self, join_from: RevenueAnalyticsBaseView) -> ast.JoinExpr:
        customer_schema = VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER]
        customer_suffix = customer_schema.events_suffix if join_from.is_event_view() else customer_schema.source_suffix

        return ast.JoinExpr(
            alias=RevenueAnalyticsCustomerView.get_generic_view_alias(),
            table=ast.Field(chain=[*join_from.prefix.split("."), customer_suffix]),
            join_type="LEFT JOIN",
            constraint=ast.JoinConstraint(
                constraint_type="ON",
                expr=ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=[join_from.get_generic_view_alias(), "customer_id"]),
                    right=ast.Field(chain=[RevenueAnalyticsCustomerView.get_generic_view_alias(), "id"]),
                ),
            ),
        )

    def _create_product_join(self, join_from: RevenueAnalyticsBaseView) -> ast.JoinExpr:
        product_schema = VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_PRODUCT]
        product_suffix = product_schema.events_suffix if join_from.is_event_view() else product_schema.source_suffix

        return ast.JoinExpr(
            alias=RevenueAnalyticsProductView.get_generic_view_alias(),
            table=ast.Field(chain=[*join_from.prefix.split("."), product_suffix]),
            join_type="LEFT JOIN",
            constraint=ast.JoinConstraint(
                constraint_type="ON",
                expr=ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=[join_from.get_generic_view_alias(), "product_id"]),
                    right=ast.Field(chain=[RevenueAnalyticsProductView.get_generic_view_alias(), "id"]),
                ),
            ),
        )

    def _create_subscription_join(self, join_from: RevenueAnalyticsBaseView) -> ast.JoinExpr:
        subscription_schema = VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_SUBSCRIPTION]
        subscription_suffix = (
            subscription_schema.events_suffix if join_from.is_event_view() else subscription_schema.source_suffix
        )

        return ast.JoinExpr(
            alias=RevenueAnalyticsSubscriptionView.get_generic_view_alias(),
            table=ast.Field(chain=[*join_from.prefix.split("."), subscription_suffix]),
            join_type="LEFT JOIN",
            constraint=ast.JoinConstraint(
                constraint_type="ON",
                expr=ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=[join_from.get_generic_view_alias(), "subscription_id"]),
                    right=ast.Field(chain=[RevenueAnalyticsSubscriptionView.get_generic_view_alias(), "id"]),
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
    def revenue_subqueries(schema: RevenueAnalyticsSchema, database: Database) -> Iterable[RevenueAnalyticsBaseView]:
        for view_name in database.get_view_names():
            if view_name.endswith(schema.source_suffix) or view_name.endswith(schema.events_suffix):
                # Handle both the old way (`RevenueAnalyticsBaseView`) and the feature-flagged way (`SavedQuery` via managed viewsets)
                # Once the `managed-viewsets` feature flag is fully rolled out we can remove the first check
                # To be extra sure we aren't including user-defined queries we also assert they're managed by the Revenue Analytics managed viewset
                table = database.get_table(view_name)
                if isinstance(table, RevenueAnalyticsBaseView):
                    yield table
                elif (
                    isinstance(table, SavedQuery)
                    and table.metadata.get("managed_viewset_kind") == DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS
                ):
                    yield RevenueAnalyticsQueryRunner.saved_query_to_revenue_analytics_base_view(table)

    # This is pretty complex right now and it's doing a lot of string matching to determine the class
    # This will become simpler once we don't need to support the old way anymore
    @staticmethod
    def saved_query_to_revenue_analytics_base_view(saved_query: SavedQuery) -> RevenueAnalyticsBaseView:
        Klass: type[RevenueAnalyticsBaseView] | None = None
        if saved_query.name.endswith(
            VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CHARGE].source_suffix
        ) or saved_query.name.endswith(
            VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CHARGE].events_suffix
        ):
            Klass = RevenueAnalyticsChargeView
        elif saved_query.name.endswith(
            VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER].source_suffix
        ) or saved_query.name.endswith(
            VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER].events_suffix
        ):
            Klass = RevenueAnalyticsCustomerView
        elif saved_query.name.endswith(
            VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_PRODUCT].source_suffix
        ) or saved_query.name.endswith(
            VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_PRODUCT].events_suffix
        ):
            Klass = RevenueAnalyticsProductView
        elif saved_query.name.endswith(
            VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM].source_suffix
        ) or saved_query.name.endswith(
            VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM].events_suffix
        ):
            Klass = RevenueAnalyticsRevenueItemView
        elif saved_query.name.endswith(
            VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_SUBSCRIPTION].source_suffix
        ) or saved_query.name.endswith(
            VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_SUBSCRIPTION].events_suffix
        ):
            Klass = RevenueAnalyticsSubscriptionView
        else:
            raise ValueError(f"Saved query {saved_query.name} is not a revenue analytics view")

        is_event_view = "revenue_analytics.events" in saved_query.name
        return Klass(
            id=saved_query.id,
            query=saved_query.query,
            name=saved_query.name,
            fields=saved_query.fields,
            metadata=saved_query.metadata,
            # :KLUTCH: None of these properties below are great but it's all we can do to figure this one out for now
            # We'll be able to come up with a better solution we don't need to support the old managed views anymore
            prefix=".".join(saved_query.name.split(".")[:-1]),
            source_id=None,  # Not used so just ignore it
            event_name=saved_query.name.split(".")[2] if is_event_view else None,
        )

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

    def _build_breakdown_expr(self, alias: str, field: ast.Field, join_from: RevenueAnalyticsBaseView) -> ast.Alias:
        expr: ast.Expr = field

        for breakdown in self.parsed_breakdown_from(join_from.__class__):
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
