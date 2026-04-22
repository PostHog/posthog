import time
from abc import ABC, abstractmethod
from datetime import datetime
from functools import cached_property
from typing import Generic, Optional, TypeVar

import structlog
import posthoganalytics

from posthog.schema import (
    ConversionGoalFilter1,
    ConversionGoalFilter2,
    ConversionGoalFilter3,
    DateRange,
    MarketingAnalyticsConstants,
    MarketingAnalyticsDrillDownLevel,
)

from posthog.hogql import ast
from posthog.hogql.database.schema.channel_type import ChannelTypeExprs, create_channel_type_expr
from posthog.hogql.modifiers import create_default_modifiers_for_team

from posthog.event_usage import groups
from posthog.hogql_queries.query_runner import AnalyticsQueryResponseProtocol, AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_compare_to_date_range import QueryCompareToDateRange
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange
from posthog.models.team.team import DEFAULT_CURRENCY

from products.data_warehouse.backend.models.util import get_view_or_table_by_name
from products.marketing_analytics.backend.hogql_queries.constants import UNIFIED_CONVERSION_GOALS_CTE_ALIAS

from .adapters.base import MarketingSourceAdapter, QueryContext
from .adapters.factory import MarketingSourceFactory
from .conversion_goal_processor import ConversionGoalProcessor
from .conversion_goals_aggregator import ConversionGoalsAggregator
from .marketing_analytics_config import MarketingAnalyticsConfig
from .utils import convert_team_conversion_goals_to_objects

logger = structlog.get_logger(__name__)

ResponseType = TypeVar("ResponseType", bound=AnalyticsQueryResponseProtocol)


class MarketingAnalyticsBaseQueryRunner(AnalyticsQueryRunner[ResponseType], ABC, Generic[ResponseType]):
    """Base class for marketing analytics query runners with shared functionality."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = MarketingAnalyticsConfig()
        self._conversion_goal_warnings: list[str] = []
        self._valid_conversion_goals_count: Optional[int] = None

    def calculate(self) -> ResponseType:
        start = time.perf_counter()
        try:
            response = self._calculate()
            self._capture_query_event("marketing analytics query performed", start)
            return response
        except Exception as e:
            self._capture_query_event("marketing analytics query failed", start, error=e)
            raise

    def _capture_query_event(self, event: str, start: float, error: Optional[BaseException] = None) -> None:
        try:
            duration_ms = (time.perf_counter() - start) * 1000
            if self._valid_conversion_goals_count is not None:
                conversion_goals_count = self._valid_conversion_goals_count
            else:
                team_goals = self.team.marketing_analytics_config.conversion_goals or []
                draft_goal = getattr(self.query, "draftConversionGoal", None)
                conversion_goals_count = len(team_goals) + (1 if draft_goal else 0)

            # Compare mode is entered via either compareFilter.compare (previous period)
            # or compareFilter.compare_to (specific period) — see query_compare_to_date_range.
            compare_filter = getattr(self.query, "compareFilter", None)
            has_compare = bool(
                compare_filter
                and (
                    getattr(compare_filter, "compare", False)
                    or isinstance(getattr(compare_filter, "compare_to", None), str)
                )
            )

            props: dict = {
                "query_kind": getattr(self.query, "kind", None),
                "duration_ms": round(duration_ms, 2),
                "drill_down_level": getattr(self.config, "drill_down_level", None),
                "attribution_mode": getattr(self.query, "attributionMode", None),
                "conversion_goals_count": conversion_goals_count,
                "has_compare": has_compare,
                "team_id": self.team.pk,
            }
            if error is None:
                props["timings"] = [{"k": t.k, "t": t.t} for t in self.timings.to_list()]
            else:
                props["error_name"] = type(error).__name__
                props["error_message"] = str(error)[:500]
            posthoganalytics.capture(
                distinct_id=str(self.team.uuid),
                event=event,
                properties=props,
                groups=groups(self.team.organization, self.team),
            )
        except Exception:
            logger.exception("Failed to capture marketing analytics telemetry event", event_name=event)

    @cached_property
    def query_date_range(self):
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=None,
            now=datetime.now(),
        )

    def _factory(self, date_range: QueryDateRange):
        """Create factory instance for the given date range"""
        context = QueryContext(
            date_range=date_range,
            team=self.team,
            base_currency=self.team.base_currency or DEFAULT_CURRENCY,
        )
        return MarketingSourceFactory(context=context)

    def _get_marketing_source_adapters(self, date_range: QueryDateRange):
        """Get marketing source adapters using the new adapter architecture"""
        try:
            factory: MarketingSourceFactory = self._factory(date_range=date_range)
            adapters = factory.create_adapters()
            valid_adapters = factory.get_valid_adapters(adapters)

            # Apply integration filter if present
            if self.query.integrationFilter and self.query.integrationFilter.integrationSourceIds:
                selected_ids = self.query.integrationFilter.integrationSourceIds
                valid_adapters = [adapter for adapter in valid_adapters if adapter.get_source_id() in selected_ids]

            return valid_adapters

        except Exception as e:
            logger.exception("Error getting marketing source adapters", error=str(e))
            return []

    def _build_campaign_cost_select(self, union_subquery: ast.SelectQuery | ast.SelectSetQuery) -> ast.SelectQuery:
        """Build the campaign_costs CTE SELECT query"""
        # Build GROUP BY using configuration - this will be overridden in aggregated queries
        group_by_exprs: list[ast.Expr] = self._get_group_by_expressions()

        # Build SELECT columns for the CTE
        select_columns: list[ast.Expr] = []

        # Include grouping columns based on drill-down level.
        # We always emit campaign_name, campaign_id, source_name, match_key
        # so the CTE schema is stable. At channel/source level we repurpose
        # campaign_name to hold the channel or source value.
        if group_by_exprs:
            level = self.config.drill_down_level
            if level == MarketingAnalyticsDrillDownLevel.CHANNEL:
                # Repurpose campaign_name to hold the channel derived from source
                select_columns.extend(
                    [
                        ast.Alias(alias=self.config.campaign_field, expr=self._build_channel_type_expr()),
                        ast.Alias(alias=self.config.id_field, expr=ast.Constant(value="")),
                        ast.Alias(alias=self.config.source_field, expr=ast.Constant(value="")),
                        ast.Alias(alias=self.config.match_key_field, expr=ast.Constant(value="")),
                    ]
                )
            elif level == MarketingAnalyticsDrillDownLevel.SOURCE:
                # Repurpose campaign_name to hold the source
                select_columns.extend(
                    [
                        ast.Alias(alias=self.config.campaign_field, expr=ast.Field(chain=[self.config.source_field])),
                        ast.Alias(alias=self.config.id_field, expr=ast.Constant(value="")),
                        ast.Alias(alias=self.config.source_field, expr=ast.Field(chain=[self.config.source_field])),
                        ast.Alias(alias=self.config.match_key_field, expr=ast.Constant(value="")),
                    ]
                )
            elif level in (
                MarketingAnalyticsDrillDownLevel.MEDIUM,
                MarketingAnalyticsDrillDownLevel.CONTENT,
                MarketingAnalyticsDrillDownLevel.TERM,
            ):
                # No platform data at UTM granularity — single empty group for the FULL OUTER JOIN.
                select_columns.extend(
                    [
                        ast.Alias(alias=self.config.campaign_field, expr=ast.Constant(value="")),
                        ast.Alias(alias=self.config.id_field, expr=ast.Constant(value="")),
                        ast.Alias(alias=self.config.source_field, expr=ast.Constant(value="")),
                        ast.Alias(alias=self.config.match_key_field, expr=ast.Constant(value="")),
                    ]
                )
            else:
                # Campaign level (default) — include campaign, id, source, match_key
                select_columns.extend(
                    [
                        ast.Field(chain=[self.config.campaign_field]),
                        ast.Field(chain=[self.config.id_field]),
                        ast.Field(chain=[self.config.source_field]),
                        # match_key is used for joining with conversion goals
                        # Use any() since all rows in a group have the same match_key value
                        ast.Alias(
                            alias=self.config.match_key_field,
                            expr=ast.Call(name="any", args=[ast.Field(chain=[self.config.match_key_field])]),
                        ),
                    ]
                )

        select_columns.extend(
            [
                ast.Alias(
                    alias=self.config.total_cost_field,
                    expr=ast.Call(
                        name="sum",
                        args=[
                            ast.Call(
                                name="ifNull",
                                args=[
                                    ast.Call(
                                        name="toFloat", args=[ast.Field(chain=[MarketingSourceAdapter.cost_field])]
                                    ),
                                    ast.Constant(value=0),
                                ],
                            )
                        ],
                    ),
                ),
                ast.Alias(
                    alias=self.config.total_clicks_field,
                    expr=ast.Call(
                        name="sum",
                        args=[
                            ast.Call(
                                name="ifNull",
                                args=[
                                    ast.Call(
                                        name="toFloat", args=[ast.Field(chain=[MarketingSourceAdapter.clicks_field])]
                                    ),
                                    ast.Constant(value=0),
                                ],
                            )
                        ],
                    ),
                ),
                ast.Alias(
                    alias=self.config.total_impressions_field,
                    expr=ast.Call(
                        name="sum",
                        args=[
                            ast.Call(
                                name="ifNull",
                                args=[
                                    ast.Call(
                                        name="toFloat",
                                        args=[ast.Field(chain=[MarketingSourceAdapter.impressions_field])],
                                    ),
                                    ast.Constant(value=0),
                                ],
                            )
                        ],
                    ),
                ),
                ast.Alias(
                    alias=self.config.total_reported_conversions_field,
                    expr=ast.Call(
                        name="sum",
                        args=[
                            ast.Call(
                                name="ifNull",
                                args=[
                                    ast.Call(
                                        name="toFloat",
                                        args=[ast.Field(chain=[MarketingSourceAdapter.reported_conversion_field])],
                                    ),
                                    ast.Constant(value=0),
                                ],
                            )
                        ],
                    ),
                ),
                ast.Alias(
                    alias=self.config.total_reported_conversion_value_field,
                    expr=ast.Call(
                        name="sum",
                        args=[
                            ast.Call(
                                name="ifNull",
                                args=[
                                    ast.Call(
                                        name="toFloat",
                                        args=[
                                            ast.Field(chain=[MarketingSourceAdapter.reported_conversion_value_field])
                                        ],
                                    ),
                                    ast.Constant(value=0),
                                ],
                            )
                        ],
                    ),
                ),
            ]
        )

        union_join_expr = ast.JoinExpr(table=union_subquery)

        # Build the CTE SELECT query
        return ast.SelectQuery(
            select=select_columns, select_from=union_join_expr, group_by=group_by_exprs if group_by_exprs else None
        )

    def _get_team_conversion_goals(self) -> list[ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3]:
        """Get conversion goals from team marketing analytics config and convert to proper objects"""
        conversion_goals = convert_team_conversion_goals_to_objects(
            self.team.marketing_analytics_config.conversion_goals, self.team.pk
        )

        # Only check draftConversionGoal if the query type supports it
        if hasattr(self.query, "draftConversionGoal") and self.query.draftConversionGoal:
            conversion_goals = [self.query.draftConversionGoal, *conversion_goals]

        return conversion_goals

    def _filter_invalid_conversion_goals(
        self, conversion_goals: list[ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3]
    ) -> tuple[list[ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3], list[str]]:
        """
        Filter out invalid conversion goals (e.g., those using "All Events" or
        referencing missing Data Warehouse columns).
        Returns (valid_goals, warnings).
        """
        valid_goals: list[ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3] = []
        warnings: list[str] = []

        for goal in conversion_goals:
            goal_name = getattr(goal, "conversion_goal_name", "Unknown")

            # Skip "All Events" goals
            if goal.kind == "EventsNode":
                event_name = getattr(goal, "event", None)
                if event_name is None or event_name == "":
                    logger.info(
                        "filtering_out_all_events_conversion_goal",
                        goal_name=goal_name,
                    )
                    warnings.append(f"Conversion goal '{goal_name}' skipped: 'All Events' cannot be used")
                    continue

            # Validate DataWarehouseNode column existence
            if goal.kind == "DataWarehouseNode" and isinstance(goal, ConversionGoalFilter3):
                table = get_view_or_table_by_name(team=self.team, name=goal.table_name)
                if table is None:
                    logger.warning(
                        "filtering_out_missing_dw_table_goal",
                        goal_name=goal_name,
                        table_name=goal.table_name,
                    )
                    warnings.append(f"Conversion goal '{goal_name}' skipped: table '{goal.table_name}' not found")
                    continue

                schema_map = goal.schema_map or {}
                table_columns = getattr(table, "columns", None) or {}
                missing_cols = []
                for schema_key, default_col in [
                    ("utm_campaign_name", "utm_campaign"),
                    ("utm_source_name", "utm_source"),
                ]:
                    col_name = schema_map.get(schema_key) or default_col
                    if col_name not in table_columns:
                        missing_cols.append(col_name)

                if missing_cols:
                    logger.warning(
                        "filtering_out_missing_column_goal",
                        goal_name=goal_name,
                        table_name=goal.table_name,
                        missing_columns=missing_cols,
                    )
                    warnings.append(
                        f"Conversion goal '{goal_name}' skipped: columns {missing_cols} not found on table '{goal.table_name}'"
                    )
                    continue

            valid_goals.append(goal)

        return valid_goals, warnings

    def _create_conversion_goal_processors(
        self, conversion_goals: list[ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3]
    ) -> list:
        """Create conversion goal processors for reuse across different methods"""
        processors = []
        for index, conversion_goal in enumerate(conversion_goals):
            # Create processor if select is None (all columns) or if conversion goal columns are explicitly selected
            should_create = self.query.select is None or (
                conversion_goal.conversion_goal_name in self.query.select
                or f"{MarketingAnalyticsConstants.COST_PER} {conversion_goal.conversion_goal_name}" in self.query.select
            )
            if should_create:
                processor = ConversionGoalProcessor(
                    goal=conversion_goal, index=index, team=self.team, config=self.config
                )
                processors.append(processor)
        return processors

    def _get_where_conditions(
        self,
        date_range: QueryDateRange,
        base_conditions=None,
        include_date_range=True,
        date_field="timestamp",
        use_date_not_datetime=False,
    ) -> list[ast.Expr]:
        """Build WHERE conditions with common patterns"""
        conditions = base_conditions or []

        if include_date_range:
            # Handle date_field with table prefixes like "events.timestamp"
            date_field_chain = date_field.split(".")
            # Always cast the date field explicitly. Data warehouse columns may be
            # stored as String, and ClickHouse cannot compare String with Date/DateTime.
            # Casting is a no-op when the column is already the correct type.
            raw_field = ast.Field(chain=date_field_chain)
            if use_date_not_datetime:
                date_field_expr = ast.Call(name="toDate", args=[raw_field])
                from_date = ast.Call(name="toDate", args=[ast.Constant(value=date_range.date_from_str)])
                to_date = ast.Call(name="toDate", args=[ast.Constant(value=date_range.date_to_str)])

                gte_condition = ast.CompareOperation(
                    left=date_field_expr, op=ast.CompareOperationOp.GtEq, right=from_date
                )
                lte_condition = ast.CompareOperation(
                    left=date_field_expr, op=ast.CompareOperationOp.LtEq, right=to_date
                )

                conditions.extend([gte_condition, lte_condition])
            else:
                date_cast = ast.Call(name="toDateTime", args=[raw_field])

                from_datetime = ast.Call(name="toDateTime", args=[ast.Constant(value=date_range.date_from_str)])
                to_datetime = ast.Call(name="toDateTime", args=[ast.Constant(value=date_range.date_to_str)])

                gte_condition = ast.CompareOperation(
                    left=date_cast, op=ast.CompareOperationOp.GtEq, right=from_datetime
                )
                lte_condition = ast.CompareOperation(left=date_cast, op=ast.CompareOperationOp.LtEq, right=to_datetime)

                conditions.extend([gte_condition, lte_condition])

        return conditions

    @cached_property
    def query_compare_to_date_range(self):
        """Get the compare date range if compare filter is enabled"""
        if self.query.compareFilter is not None:
            if isinstance(self.query.compareFilter.compare_to, str):
                return QueryCompareToDateRange(
                    date_range=self.query.dateRange,
                    team=self.team,
                    interval=None,
                    now=datetime.now(),
                    compare_to=self.query.compareFilter.compare_to,
                )
            elif self.query.compareFilter.compare:
                return QueryPreviousPeriodDateRange(
                    date_range=self.query.dateRange,
                    team=self.team,
                    interval=None,
                    now=datetime.now(),
                )
        return None

    def _create_previous_period_date_range(self) -> QueryDateRange:
        """Create the date range for the previous period comparison"""
        return QueryDateRange(
            date_range=DateRange(
                date_from=self.query_compare_to_date_range.date_from().isoformat(),
                date_to=self.query_compare_to_date_range.date_to().isoformat(),
            ),
            team=self.team,
            interval=None,
            now=datetime.now(),
        )

    def _build_complete_query_ast(
        self,
        union_subquery: ast.SelectQuery | ast.SelectSetQuery,
        processors: list,
        date_range: QueryDateRange,
    ) -> ast.SelectQuery:
        """Build the complete query with CTEs using AST expressions"""

        # Create conversion goals aggregator if needed
        conversion_aggregator = ConversionGoalsAggregator(processors, self.config) if processors else None

        # Build the main SELECT query
        main_query = self._build_main_select_query(conversion_aggregator)

        # Build CTEs as a dictionary
        ctes: dict[str, ast.CTE] = {}

        # Add campaign_costs CTE
        campaign_cost_select = self._build_campaign_cost_select(union_subquery)
        campaign_cost_cte = ast.CTE(
            name=self.config.campaign_costs_cte_name, expr=campaign_cost_select, cte_type="subquery"
        )
        ctes[self.config.campaign_costs_cte_name] = campaign_cost_cte

        # Add unified conversion goal CTE if any
        if conversion_aggregator:
            # Check if this is an aggregated query (no GROUP BY)
            group_by_exprs = self._get_group_by_expressions()
            if not group_by_exprs:
                # For aggregated queries, create aggregated conversion goals CTE
                unified_cte = self._generate_aggregated_conversion_goals_cte(conversion_aggregator, date_range)
            else:
                # For table queries, use the normal conversion goals CTE
                unified_cte = conversion_aggregator.generate_unified_cte(date_range, self._get_where_conditions)

            if unified_cte:
                ctes[UNIFIED_CONVERSION_GOALS_CTE_ALIAS] = unified_cte

        # Add CTEs to the main query
        main_query.ctes = ctes

        return main_query

    def _build_channel_type_expr(self) -> ast.Expr:
        """Compute channel_type for adapter data using web analytics' classification."""
        modifiers = create_default_modifiers_for_team(self.team)
        return create_channel_type_expr(
            custom_rules=modifiers.customChannelTypeRules,
            source_exprs=ChannelTypeExprs(
                source=ast.Field(chain=[self.config.source_field]),
                medium=ast.Constant(value="cpc"),  # all adapter data is paid
                campaign=ast.Constant(value=""),
                referring_domain=ast.Constant(value="$direct"),
                url=ast.Constant(value=""),
                hostname=ast.Constant(value=""),
                pathname=ast.Constant(value=""),
                has_gclid=ast.Constant(value=False),
                has_fbclid=ast.Constant(value=False),
                gad_source=ast.Constant(value=None),
            ),
        )

    def _apply_drill_down_level(self) -> None:
        """Read drillDownLevel from query and apply to config"""
        level = getattr(self.query, "drillDownLevel", None)
        if level is not None:
            self.config.drill_down_level = level

    def to_query(self) -> ast.SelectQuery:
        """Generate the HogQL query using the new adapter architecture"""
        with self.timings.measure("marketing_analytics_base_query"):
            # Apply drill-down level from query to config
            self._apply_drill_down_level()

            # Get marketing source adapters
            adapters = self._get_marketing_source_adapters(date_range=self.query_date_range)

            # Build the union query using the factory (AST form to skip parse_select).
            union_subquery = self._factory(date_range=self.query_date_range).build_union_query_ast(adapters)

            # Get conversion goals and filter out invalid ones
            conversion_goals = self._get_team_conversion_goals()
            valid_conversion_goals, self._conversion_goal_warnings = self._filter_invalid_conversion_goals(
                conversion_goals
            )
            self._valid_conversion_goals_count = len(valid_conversion_goals)

            # Create processors only for valid conversion goals
            processors = (
                self._create_conversion_goal_processors(valid_conversion_goals) if valid_conversion_goals else []
            )

            # Build the complete query with CTEs using AST
            return self._build_complete_query_ast(union_subquery, processors, self.query_date_range)

    def _generate_aggregated_conversion_goals_cte(self, conversion_aggregator, date_range) -> Optional[ast.CTE]:
        """Generate aggregated conversion goals CTE without GROUP BY for aggregated queries"""
        try:
            # Get the processors
            processors = conversion_aggregator.processors
            if not processors:
                return None

            # Build select columns for aggregated conversion goals
            select_columns: list[ast.Expr] = []

            for processor in processors:
                # For aggregated queries, create a simple COUNT expression from events table
                # This counts total conversions in the date range without campaign/source matching

                # Build WHERE conditions for this conversion goal
                where_conditions = self._get_where_conditions(
                    date_range=date_range,
                    include_date_range=True,
                    date_field="events.timestamp",
                    use_date_not_datetime=False,
                )

                # Add conversion goal specific conditions
                if processor.goal.kind == "EventsNode":
                    # Event-based conversion goal
                    event_condition = ast.CompareOperation(
                        left=ast.Field(chain=["events", "event"]),
                        op=ast.CompareOperationOp.Eq,
                        right=ast.Constant(value=processor.goal.event),
                    )
                    where_conditions.append(event_condition)
                elif processor.goal.kind == "ActionsNode":
                    # Action-based conversion goal - more complex, skip for now
                    continue

                # For aggregated queries, use a scalar subquery to count conversions
                conversion_subquery = ast.SelectQuery(
                    select=[ast.Call(name="count", args=[])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    where=ast.And(exprs=where_conditions) if where_conditions else None,
                )

                # Use the same column naming convention as the regular conversion goals aggregator
                conversion_column_name = self.config.get_conversion_goal_column_name(processor.index)

                select_columns.append(
                    ast.Alias(
                        alias=conversion_column_name,  # This will be "conversion_0", "conversion_1", etc.
                        expr=conversion_subquery,
                    )
                )

            if not select_columns:
                return None

            # Create a simple SELECT that counts conversions directly from events
            # This gives us total conversion counts across all campaigns/sources
            aggregated_select = ast.SelectQuery(select=select_columns)

            return ast.CTE(name=UNIFIED_CONVERSION_GOALS_CTE_ALIAS, expr=aggregated_select, cte_type="subquery")

        except Exception as e:
            logger.exception("Error generating aggregated conversion goals CTE", error=str(e))
            # If we can't generate aggregated conversion goals, don't create the CTE
            return None

    def _get_group_by_expressions(self) -> list[ast.Expr]:
        """Get GROUP BY expressions"""
        if self.config.drill_down_level == MarketingAnalyticsDrillDownLevel.CHANNEL:
            # channel is a computed alias, so GROUP BY the same expression
            return [self._build_channel_type_expr()]
        return [ast.Field(chain=[field]) for field in self.config.group_by_fields]

    # Abstract methods that subclasses must implement

    @abstractmethod
    def _build_main_select_query(self, conversion_aggregator) -> ast.SelectQuery:
        """Build the main SELECT query"""
        pass

    @abstractmethod
    def _calculate(self) -> ResponseType:
        """Execute the query and return results"""
        pass
