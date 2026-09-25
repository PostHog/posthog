from typing import Any, Optional

from posthog.schema import HogQLQueryModifiers, MarketingAnalyticsActorsQuery, MarketingAnalyticsDrillDownLevel

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.timings import HogQLTimings

from posthog.hogql_queries.actors_query_runner import ActorsQueryNotReady
from posthog.models import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl

from .conversion_goal_processor import ConversionGoalProcessor
from .conversion_goals_aggregator import ConversionGoalsAggregator
from .errors import MarketingPrecomputeNotReady
from .marketing_analytics_table_query_runner import MarketingAnalyticsTableQueryRunner
from .marketing_lazy_precompute import handle_not_ready


class MarketingAnalyticsActorsQueryRunner(MarketingAnalyticsTableQueryRunner):
    def __init__(
        self,
        query: MarketingAnalyticsActorsQuery | dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
        query_id: Optional[str] = None,
        user: Optional[User] = None,
    ) -> None:
        actors_query = (
            query if isinstance(query, MarketingAnalyticsActorsQuery) else MarketingAnalyticsActorsQuery(**query)
        )
        self.actors_query = actors_query
        super().__init__(
            query=actors_query.source,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            query_id=query_id,
            user=user,
        )

    def validate_query_runner_access(self, user: User) -> bool:
        return UserAccessControl(user=user, team=self.team).assert_access_level_for_resource("web_analytics", "viewer")

    def to_actors_query(self) -> ast.SelectQuery:
        try:
            return self._build_actors_query()
        except MarketingPrecomputeNotReady as not_ready:
            handle_not_ready(team=self.team, query=not_ready.query or self.query)
            raise ActorsQueryNotReady from not_ready

    def _build_actors_query(self) -> ast.SelectQuery:
        self._apply_drill_down_level()
        valid_goals, self._skipped_conversion_goals = self._filter_invalid_conversion_goals(
            self._get_team_conversion_goals()
        )
        goal_and_index = next(
            (
                (goal, index)
                for index, goal in enumerate(valid_goals)
                if goal.conversion_goal_id == self.actors_query.conversionGoalId
            ),
            None,
        )
        if goal_and_index is None:
            raise ValueError("Conversion goal not found")

        goal, index = goal_and_index
        processor = ConversionGoalProcessor(
            goal=goal,
            index=index,
            team=self.team,
            config=self.config,
            user=self.user,
            timings=self.timings,
            filter_test_accounts=self.filter_test_accounts,
        )
        date_range = self.query_date_range
        additional_conditions = self._get_where_conditions(
            date_range=date_range,
            include_date_range=True,
            date_field=processor.get_date_field(),
            use_date_not_datetime=True,
        )
        attributed = processor.generate_attributed_conversions_query(
            additional_conditions,
            date_from=date_range.date_from(),
            date_to=date_range.date_to(),
        )

        alias = "attributed_conversions"
        field_exprs = processor.build_attributed_field_exprs(table_alias=alias)

        level = self.config.drill_down_level
        source_expr = field_exprs["source"]
        if level in (MarketingAnalyticsDrillDownLevel.CHANNEL, MarketingAnalyticsDrillDownLevel.CHANNEL_SOURCE):
            breakdown_expr = processor._build_channel_type_expr(field_exprs)
        elif level == MarketingAnalyticsDrillDownLevel.SOURCE:
            breakdown_expr = source_expr
        elif level in (
            MarketingAnalyticsDrillDownLevel.MEDIUM,
            MarketingAnalyticsDrillDownLevel.CONTENT,
            MarketingAnalyticsDrillDownLevel.TERM,
        ):
            breakdown_expr = field_exprs[processor._UTM_LEVEL_FIELD_MAP[level]]
        else:
            campaign_expr, _ = ConversionGoalsAggregator([processor], self.config).apply_campaign_name_mappings(
                field_exprs["campaign"], ast.Field(chain=[alias, "campaign_id"]), source_expr
            )
            breakdown_expr = campaign_expr

        conditions: list[ast.Expr] = [
            ast.CompareOperation(
                left=breakdown_expr,
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=self.actors_query.breakdown.value),
            )
        ]
        if self.actors_query.breakdown.source is not None:
            conditions.append(
                ast.CompareOperation(
                    left=source_expr,
                    op=ast.CompareOperationOp.Eq,
                    right=ast.Constant(value=self.actors_query.breakdown.source),
                )
            )

        return ast.SelectQuery(
            select=[ast.Alias(alias="actor_id", expr=ast.Field(chain=[alias, "person_id"]))],
            select_from=ast.JoinExpr(table=attributed, alias=alias),
            where=ast.And(exprs=conditions) if len(conditions) > 1 else conditions[0],
            distinct=True,
        )
