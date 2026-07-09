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
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.schema.channel_type import ChannelTypeExprs, create_channel_type_expr
from posthog.hogql.modifiers import create_default_modifiers_for_team

from posthog.event_usage import groups
from posthog.hogql_queries.query_runner import AnalyticsQueryResponseProtocol, AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_compare_to_date_range import QueryCompareToDateRange
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange
from posthog.models.team.team import DEFAULT_CURRENCY

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationTable,
    ensure_precomputed,
)
from products.marketing_analytics.backend.hogql_queries.constants import (
    DRILL_DOWN_LEVEL_CONFIG,
    UNIFIED_CONVERSION_GOALS_CTE_ALIAS,
)
from products.warehouse_sources.backend.facade.hogql import get_view_or_table_by_name

from .adapters.base import MarketingSourceAdapter, QueryContext
from .adapters.factory import MarketingSourceFactory
from .conversion_goal_processor import ConversionGoalProcessor
from .conversion_goals_aggregator import ConversionGoalsAggregator
from .marketing_analytics_config import MarketingAnalyticsConfig
from .utils import convert_team_conversion_goals_to_objects

logger = structlog.get_logger(__name__)

ResponseType = TypeVar("ResponseType", bound=AnalyticsQueryResponseProtocol)

# Discriminator column tagging each row in the compare UNION ALL with its period.
COMPARE_PERIOD_FIELD = "_period"
COMPARE_PERIOD_CURRENT = "current"
COMPARE_PERIOD_PREVIOUS = "previous"


class MarketingAnalyticsBaseQueryRunner(AnalyticsQueryRunner[ResponseType], ABC, Generic[ResponseType]):
    """Base class for marketing analytics query runners with shared functionality."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Build from team so every runner (table, aggregated, non-integrated) picks up attribution
        # settings and the precompute feature flags. Subclasses previously each set this; the aggregated
        # runner didn't, so it silently used defaults (cost precompute always off).
        self.config = MarketingAnalyticsConfig.from_team(self.team)
        self._conversion_goal_warnings: list[str] = []
        self._valid_conversion_goals_count: Optional[int] = None
        # Cost-precompute observability — surfaced in the query telemetry event so we can confirm,
        # per query, whether the native cost table was used or we fell back to the live S3 union.
        self._costs_precompute_used: bool = False
        self._costs_sources_materialized: int = 0
        self._costs_grain: Optional[str] = None

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
                "costs_precompute_used": self._costs_precompute_used,
                "costs_sources_materialized": self._costs_sources_materialized,
                "costs_grain": self._costs_grain,
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

    @cached_property
    def _shared_hogql_database(self) -> Database:
        """Built once and reused across every MarketingSourceFactory AND passed into
        `execute_hogql_query` (via `_shared_hogql_context`), so the request pays Database.create_for
        once instead of 3-5× (it's ~1s with the user's modifiers — feature flags + system-table
        filtering). Built with the runner's user+modifiers so it's valid for resolving the final
        query, not just the factory's warehouse-name lookup."""
        modifiers = create_default_modifiers_for_team(self.team, self.modifiers)
        # Pass the runner's timings so create_for's internal spans (data_warehouse_tables,
        # filter_system_tables_for_user, saved queries, revenue views, …) surface in the query's
        # timings instead of a discarded HogQLTimings — otherwise this whole build shows as an
        # opaque flat span.
        return Database.create_for(
            team=self.team,
            user=self.user,
            modifiers=modifiers,
            timings=self.timings,
            build_postgres_foreign_keys=False,
        )

    @cached_property
    def _shared_hogql_context(self) -> HogQLContext:
        """HogQLContext carrying the prebuilt database, passed to execute_hogql_query so its
        `_generate_hogql` reuses the database instead of building a second one."""
        return HogQLContext(team_id=self.team.pk, database=self._shared_hogql_database)

    def _factory(self, date_range: QueryDateRange):
        """Create factory instance for the given date range"""
        context = QueryContext(
            date_range=date_range,
            team=self.team,
            base_currency=self.team.base_currency or DEFAULT_CURRENCY,
            drill_down_level=self.config.drill_down_level,
            database=self._shared_hogql_database,
        )
        return MarketingSourceFactory(context=context)

    def _get_marketing_source_adapters(self, date_range: QueryDateRange):
        """Get marketing source adapters using the new adapter architecture"""
        try:
            factory: MarketingSourceFactory = self._factory(date_range=date_range)
            with self.timings.measure("ma_adapters_create"):
                adapters = factory.create_adapters()
            with self.timings.measure("ma_adapters_validate"):
                valid_adapters = factory.get_valid_adapters(adapters)

            # Apply integration filter if present (getattr: some query kinds lack the field)
            integration_filter = getattr(self.query, "integrationFilter", None)
            if integration_filter and integration_filter.integrationSourceIds:
                selected_ids = integration_filter.integrationSourceIds
                valid_adapters = [adapter for adapter in valid_adapters if adapter.get_source_id() in selected_ids]

            return valid_adapters

        except Exception as e:
            logger.exception("Error getting marketing source adapters", error=str(e))
            return []

    def _cost_materialization_grain(self) -> MarketingAnalyticsDrillDownLevel:
        """The grain a cost row is materialized at for the current drill-down. AD_GROUP/AD keep their
        own grain (platform stats differ per level); everything else (CHANNEL/SOURCE/CAMPAIGN/UTM) reads
        campaign-grain rows and rolls up — valid because those levels aggregate campaigns."""
        level = self.config.drill_down_level
        if level in (MarketingAnalyticsDrillDownLevel.AD_GROUP, MarketingAnalyticsDrillDownLevel.AD):
            return level
        return MarketingAnalyticsDrillDownLevel.CAMPAIGN

    def _build_costs_from_precompute(
        self, date_range: QueryDateRange
    ) -> Optional[ast.SelectQuery | ast.SelectSetQuery]:
        """Native-table cost source: ensure each source's cost rows are materialized at the grain
        matching the current drill-down (one lazy job per source), then read them with the SAME column
        contract `build_union_query_ast` produces — so `_build_campaign_cost_select` is unchanged.
        Returns None if any source isn't ready → caller falls back to the live S3 adapter union.
        """
        grain = self._cost_materialization_grain()
        # Adapters at the materialization grain (not the drill-down level, which may be SOURCE/CHANNEL).
        mat_context = QueryContext(
            date_range=date_range,
            team=self.team,
            base_currency=self.team.base_currency or DEFAULT_CURRENCY,
            drill_down_level=grain,
            database=self._shared_hogql_database,
        )
        mat_factory = MarketingSourceFactory(context=mat_context)
        with self.timings.measure("ma_precompute_adapters"):
            mat_adapters = mat_factory.get_valid_adapters(mat_factory.create_adapters())
        # NonIntegratedConversionsTableQuery has no integrationFilter field — getattr keeps the
        # precompute path working for it instead of raising AttributeError and falling back to S3.
        integration_filter = getattr(self.query, "integrationFilter", None)
        if integration_filter and integration_filter.integrationSourceIds:
            selected_ids = integration_filter.integrationSourceIds
            mat_adapters = [a for a in mat_adapters if a.get_source_id() in selected_ids]
        mat_adapters = [a for a in mat_adapters if a.supports_level(grain)]
        grain_value = str(grain.value)
        if not mat_adapters:
            logger.info(
                "marketing_costs_precompute",
                outcome="fallback_no_materializable_sources",
                team_id=self.team.pk,
                grain=grain_value,
                source_count=0,
            )
            return None

        ttl_seconds = {"0d": 6 * 60 * 60, "1d": 24 * 60 * 60, "default": 7 * 24 * 60 * 60}
        # Per source: read the native table when it materializes, otherwise keep that one source on the
        # live S3 union. A single unmaterializable/syncing source must not force every source back to S3.
        materialized_source_ids: list = []
        s3_fallback_adapters: list[MarketingSourceAdapter] = []
        for adapter in mat_adapters:
            with self.timings.measure("ma_precompute_build_mat_query"):
                insert_query = adapter.build_materialization_query(adapter.get_source_id())
            if insert_query is None:
                logger.info(
                    "marketing_costs_precompute",
                    outcome="source_fallback_unmaterializable",
                    team_id=self.team.pk,
                    grain=grain_value,
                    source_id=adapter.get_source_id(),
                )
                s3_fallback_adapters.append(adapter)
                continue
            with self.timings.measure("ma_precompute_ensure"):
                result = ensure_precomputed(
                    team=self.team,
                    insert_query=insert_query,
                    time_range_start=date_range.date_from(),
                    time_range_end=date_range.date_to(),
                    ttl_seconds=ttl_seconds,
                    table=LazyComputationTable.MARKETING_COSTS_PREAGGREGATED,
                )
            if not result.ready:
                logger.info(
                    "marketing_costs_precompute",
                    outcome="source_fallback_jobs_not_ready",
                    team_id=self.team.pk,
                    grain=grain_value,
                    source_id=adapter.get_source_id(),
                )
                s3_fallback_adapters.append(adapter)
                continue
            # The ensure_precomputed call above materialized this source. We read by source, not by
            # result.job_ids, because the `marketing_costs_precomputed` view already collapses each cell to its latest job.
            materialized_source_ids.append(adapter.get_source_id())

        if not materialized_source_ids:
            # Nothing materialized — let the caller read every source live, as before.
            logger.info(
                "marketing_costs_precompute",
                outcome="fallback_no_jobs",
                team_id=self.team.pk,
                grain=grain_value,
                source_count=len(mat_adapters),
            )
            return None

        cost_sources: list[ast.SelectQuery | ast.SelectSetQuery] = [
            self._costs_native_read_query(materialized_source_ids, grain, date_range)
        ]
        # Sources that couldn't materialize stay on the live S3 union so the dashboard stays complete.
        if s3_fallback_adapters:
            cost_sources.append(mat_factory.build_union_query_ast(s3_fallback_adapters))

        self._costs_precompute_used = True
        self._costs_sources_materialized = len(mat_adapters) - len(s3_fallback_adapters)
        self._costs_grain = grain_value
        logger.info(
            "marketing_costs_precompute",
            outcome="used",
            team_id=self.team.pk,
            grain=grain_value,
            source_count=len(mat_adapters),
            precompute_sources=len(mat_adapters) - len(s3_fallback_adapters),
            s3_fallback_sources=len(s3_fallback_adapters),
            materialized_source_count=len(materialized_source_ids),
        )
        if len(cost_sources) == 1:
            return cost_sources[0]
        return ast.SelectSetQuery.create_from_queries(cost_sources, set_operator="UNION ALL")

    def _costs_native_read_query(
        self, source_ids: list, grain: MarketingAnalyticsDrillDownLevel, date_range: QueryDateRange
    ) -> ast.SelectQuery:
        """Read deduplicated cost rows for the given materialized sources + grain, re-aliased to the
        adapter column contract so the campaign_costs CTE GROUP BY works identically to the live union.

        Reads the `marketing_costs_precomputed` view, not the raw `marketing_costs_preaggregated` table. The raw
        table is a ReplacingMergeTree whose sort key includes `job_id`, so the same cost cell can survive
        under several job_ids (a re-materialized matured day, a double-triggered job, a compare period
        reusing a wider window). The view collapses each cell to its latest job via argMax(computed_at),
        so we filter by source (not job_id) and let the view own the dedup — one definition shared with
        every other reader. `cost_date` is bounded to the request window with the same inclusive
        `toDateTime` comparison the live adapters use. team_id scoping is enforced inside the view (its
        inner raw-table reference carries the mandatory team_id guard), so no explicit filter here."""
        adapter = MarketingSourceAdapter

        def field(name: str) -> ast.Expr:
            return ast.Field(chain=[name])

        dimension_columns: list[tuple[str, str]] = [
            (adapter.match_key_field, "match_key"),
            (adapter.campaign_name_field, "campaign_name"),
            (adapter.campaign_id_field, "campaign_id"),
            (adapter.source_name_field, "source_name"),
        ]
        if self.config.drill_down_level in (
            MarketingAnalyticsDrillDownLevel.AD_GROUP,
            MarketingAnalyticsDrillDownLevel.AD,
        ):
            dimension_columns.extend(
                [
                    (adapter.ad_group_name_field, "ad_group_name"),
                    (adapter.ad_group_id_field, "ad_group_id"),
                    (adapter.ad_name_field, "ad_name"),
                    (adapter.ad_id_field, "ad_id"),
                ]
            )

        select_columns: list[ast.Expr] = [ast.Alias(alias=alias, expr=field(name)) for alias, name in dimension_columns]
        # Metrics come pre-deduplicated from the view, so a bare read is correct — the downstream
        # campaign_costs CTE still sums across days per campaign.
        select_columns.extend(
            [
                ast.Alias(alias=adapter.impressions_field, expr=field("impressions")),
                ast.Alias(alias=adapter.clicks_field, expr=field("clicks")),
                ast.Alias(alias=adapter.cost_field, expr=field("cost")),
                ast.Alias(alias=adapter.reported_conversion_field, expr=field("reported_conversions")),
                ast.Alias(alias=adapter.reported_conversion_value_field, expr=field("reported_conversion_value")),
            ]
        )

        return ast.SelectQuery(
            select=select_columns,
            select_from=ast.JoinExpr(table=ast.Field(chain=["marketing_costs_precomputed"])),
            where=ast.And(
                exprs=[
                    ast.Call(
                        name="in",
                        args=[
                            field("source_id"),
                            ast.Tuple(exprs=[ast.Constant(value=str(sid)) for sid in source_ids]),
                        ],
                    ),
                    ast.CompareOperation(
                        left=field("grain"),
                        op=ast.CompareOperationOp.Eq,
                        right=ast.Constant(value=str(grain.value)),
                    ),
                    # Bound to the request window, matching the live adapters' inclusive toDateTime filter.
                    ast.CompareOperation(
                        left=ast.Call(name="toDateTime", args=[field("cost_date")]),
                        op=ast.CompareOperationOp.GtEq,
                        right=ast.Call(name="toDateTime", args=[ast.Constant(value=date_range.date_from_str)]),
                    ),
                    ast.CompareOperation(
                        left=ast.Call(name="toDateTime", args=[field("cost_date")]),
                        op=ast.CompareOperationOp.LtEq,
                        right=ast.Call(name="toDateTime", args=[ast.Constant(value=date_range.date_to_str)]),
                    ),
                ]
            ),
        )

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
                select_columns.extend(
                    [
                        ast.Alias(alias=self.config.campaign_field, expr=self._build_channel_type_expr()),
                        ast.Alias(alias=self.config.id_field, expr=ast.Constant(value="")),
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
            elif level == MarketingAnalyticsDrillDownLevel.AD_GROUP:
                # Emit the parent campaign hierarchy alongside the ad group fields so the
                # outer query can show context columns (Campaign + Source + Ad group).
                select_columns.extend(
                    [
                        ast.Field(chain=[self.config.campaign_field]),
                        ast.Field(chain=[self.config.id_field]),
                        ast.Field(chain=[self.config.source_field]),
                        ast.Field(chain=[MarketingSourceAdapter.ad_group_name_field]),
                        ast.Field(chain=[MarketingSourceAdapter.ad_group_id_field]),
                        ast.Alias(alias=self.config.match_key_field, expr=ast.Constant(value="")),
                    ]
                )
            elif level == MarketingAnalyticsDrillDownLevel.AD:
                # Full hierarchy: Campaign + Source + Ad group + Ad.
                select_columns.extend(
                    [
                        ast.Field(chain=[self.config.campaign_field]),
                        ast.Field(chain=[self.config.id_field]),
                        ast.Field(chain=[self.config.source_field]),
                        ast.Field(chain=[MarketingSourceAdapter.ad_group_name_field]),
                        ast.Field(chain=[MarketingSourceAdapter.ad_group_id_field]),
                        ast.Field(chain=[MarketingSourceAdapter.ad_name_field]),
                        ast.Field(chain=[MarketingSourceAdapter.ad_id_field]),
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
        seen_names: set[str] = set()

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

            # Names become SQL column aliases downstream, so a duplicate would collide
            # ("Cannot redefine an alias"). Keep the first, skip the rest with a warning.
            if goal_name in seen_names:
                logger.warning(
                    "filtering_out_duplicate_named_conversion_goal",
                    goal_name=goal_name,
                )
                warnings.append(f"Conversion goal '{goal_name}' skipped: duplicate name")
                continue
            seen_names.add(goal_name)

            valid_goals.append(goal)

        return valid_goals, warnings

    def _get_filtered_select_columns(self, query: ast.SelectQuery) -> list[ast.Expr]:
        """Filter a query's SELECT to the columns requested in self.query.select, in order."""
        if not self.query.select:
            return query.select if query.select else []

        column_mapping: dict[str, ast.Expr] = {}
        for col in query.select:
            key = col.alias if isinstance(col, ast.Alias) else str(col)
            column_mapping[key] = col

        # Skip duplicates so a repeated request (e.g. two conversion goals sharing a
        # name) can't emit the same alias twice and trip "Cannot redefine an alias".
        filtered_select: list[ast.Expr] = []
        seen: set[str] = set()
        for requested_col in self.query.select:
            if requested_col in column_mapping and requested_col not in seen:
                filtered_select.append(column_mapping[requested_col])
                seen.add(requested_col)
        return filtered_select

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
                    goal=conversion_goal, index=index, team=self.team, config=self.config, user=self.user
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

        # Add unified conversion goal CTE if any. Skip building it entirely at levels
        # that exclude conversion goals (AD_GROUP / AD) — the main query never references
        # the CTE there, but ClickHouse still scans the events table to materialize it.
        # That events scan is the heaviest part of the query, so skipping it is a major
        # win at hierarchy levels.
        level_config = DRILL_DOWN_LEVEL_CONFIG.get(self.config.drill_down_level, {})
        if conversion_aggregator and not level_config.get("excludes_conversion_goals"):
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
        # Map adapter-internal source aliases to entries that exist in channel_definition_dict.
        # The Meta Ads adapter emits "meta" (the company/network) as primarySource, but the
        # dict keys are per-platform: "facebook", "instagram", "messenger", etc. We rewrite to
        # "facebook" to land in the Paid Social bucket. This goes away when Meta Ads grows a
        # publisher_platform breakdown (the adapter will emit the real per-platform source).
        source_field = ast.Field(chain=[self.config.source_field])
        normalized_source = ast.Call(
            name="if",
            args=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Call(name="lower", args=[source_field]),
                    right=ast.Constant(value="meta"),
                ),
                ast.Constant(value="facebook"),
                source_field,
            ],
        )
        return create_channel_type_expr(
            custom_rules=modifiers.customChannelTypeRules,
            source_exprs=ChannelTypeExprs(
                source=normalized_source,
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

            # Force the shared warehouse Database build here, in its own span, so its cost is isolated
            # from adapter construction (both otherwise collapse into ma_get_adapters via the cached
            # property's first access).
            with self.timings.measure("ma_build_database"):
                _ = self._shared_hogql_database

            # Build the cost source. When cost precompute is enabled, read the native materialized table
            # (no S3); fall back to the live S3 adapter union if not enabled or jobs aren't ready.
            union_subquery: ast.SelectQuery | ast.SelectSetQuery | None = None
            if self.config.costs_precomputation_enabled:
                with self.timings.measure("ma_build_costs_precompute"):
                    try:
                        union_subquery = self._build_costs_from_precompute(self.query_date_range)
                    except Exception:
                        logger.exception("cost_precompute_failed", team_id=self.team.pk)
                        union_subquery = None
            if union_subquery is None:
                # Only the S3 fallback consumes the live adapters. When precompute serves the query
                # they'd be built and thrown away, so defer construction into this branch.
                with self.timings.measure("ma_get_adapters"):
                    adapters = self._get_marketing_source_adapters(date_range=self.query_date_range)
                with self.timings.measure("ma_build_union_s3"):
                    # AST form to skip parse_select.
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

    def _build_compare_pivot(
        self,
        current_period_query: ast.SelectQuery,
        previous_period_query: ast.SelectQuery,
        select_columns: list[ast.Expr],
        key_columns: list[str],
    ) -> ast.SelectQuery:
        """Combine the two period queries with UNION ALL + a GROUP BY pivot instead of a LEFT JOIN.

        ClickHouse runs a LEFT JOIN sequentially (build the right side, then probe the left); the
        UNION ALL lets it run both period branches as concurrent pipelines. The pivot reproduces the
        LEFT JOIN exactly:
        - Each period query already emits one row per key, so `anyIf(col, _period=...)` picks that
          single value.
        - For a current row with no previous counterpart, `anyIf(col, _period='previous')` matches
          no rows and returns the default of the column's type — '' / 0 for non-Nullable columns,
          NULL for already-Nullable ones (CPC / CTR / ROAS). This is exactly what the LEFT JOIN
          produces under ClickHouse's default `join_use_nulls = 0`, so reproducing it manually
          (e.g. forcing NULL) would actually diverge from the join.
        - `HAVING countIf(current) > 0` drops previous-only rows — matching the LEFT JOIN keeping
          `current_period` as the left side.
        The output tuples, aliases, order and limit are identical to the join form, so the ORDER BY
        (over a current-period metric, expressed on the same tuple alias) and pagination are unchanged.

        `key_columns` are the columns that uniquely identify a row — the same keys the old LEFT JOIN
        matched on. Each runner passes the keys appropriate to its query shape.
        """
        column_aliases = [col.alias if isinstance(col, ast.Alias) else str(col) for col in select_columns]

        def _labeled_period(period: str, period_query: ast.SelectQuery) -> ast.SelectQuery:
            select: list[ast.Expr] = [
                ast.Alias(alias=COMPARE_PERIOD_FIELD, expr=ast.Constant(value=period)),
                *(ast.Field(chain=[alias]) for alias in column_aliases),
            ]
            return ast.SelectQuery(
                select=select,
                select_from=ast.JoinExpr(table=period_query),
            )

        union_query = ast.SelectSetQuery.create_from_queries(
            [
                _labeled_period(COMPARE_PERIOD_CURRENT, current_period_query),
                _labeled_period(COMPARE_PERIOD_PREVIOUS, previous_period_query),
            ],
            "UNION ALL",
        )
        union_alias = "combined"

        def _period_eq(period: str) -> ast.Expr:
            return ast.CompareOperation(
                left=ast.Field(chain=[union_alias, COMPARE_PERIOD_FIELD]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=period),
            )

        def _any_if(alias: str, period: str) -> ast.Expr:
            return ast.Call(
                name="anyIf",
                args=[ast.Field(chain=[union_alias, alias]), _period_eq(period)],
            )

        # Build the pivot columns in the same order/alias as the join form.
        pivot_columns: list[ast.Expr] = [
            ast.Alias(
                alias=alias,
                expr=ast.Call(
                    name="tuple",
                    args=[_any_if(alias, COMPARE_PERIOD_CURRENT), _any_if(alias, COMPARE_PERIOD_PREVIOUS)],
                ),
            )
            for alias in column_aliases
        ]

        group_by: list[ast.Expr] = [ast.Field(chain=[union_alias, key]) for key in key_columns]
        having = ast.CompareOperation(
            left=ast.Call(name="countIf", args=[_period_eq(COMPARE_PERIOD_CURRENT)]),
            op=ast.CompareOperationOp.Gt,
            right=ast.Constant(value=0),
        )

        select_from = ast.JoinExpr(table=union_query, alias=union_alias)
        paginated = self._build_paginated_query(pivot_columns, select_from)
        paginated.group_by = group_by
        paginated.having = having
        return paginated

    def _build_paginated_query(
        self, select_columns: list[ast.Expr], select_from: ast.JoinExpr | None, ctes=None
    ) -> ast.SelectQuery:
        """Build a paginated SelectQuery. Only the compare-capable table runners override this
        (order-by / limit differ); the aggregated runner never builds a compare pivot."""
        raise NotImplementedError

    # Abstract methods that subclasses must implement

    @abstractmethod
    def _build_main_select_query(self, conversion_aggregator) -> ast.SelectQuery:
        """Build the main SELECT query"""
        pass

    @abstractmethod
    def _calculate(self) -> ResponseType:
        """Execute the query and return results"""
        pass
