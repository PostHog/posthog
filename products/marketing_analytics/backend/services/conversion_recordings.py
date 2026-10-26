from typing import TypedDict

from rest_framework.exceptions import ValidationError

from posthog.schema import ConversionGoalFilter3, MarketingAnalyticsDrillDownLevel

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_select

from posthog.hogql_queries.paginators import HogQLHasMorePaginator

from products.marketing_analytics.backend.hogql_queries.constants import MARKETING_SPILL_AFTER_BYTES
from products.marketing_analytics.backend.hogql_queries.conversion_goals_aggregator import ConversionGoalsAggregator
from products.marketing_analytics.backend.hogql_queries.errors import MarketingPrecomputeNotReady
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_table_query_runner import (
    MarketingAnalyticsTableQueryRunner,
)
from products.marketing_analytics.backend.hogql_queries.marketing_lazy_precompute import handle_not_ready


class ConversionRecordingsResponse(TypedDict):
    session_ids: list[str]
    has_more: bool
    preparing: bool


class ConversionRecordingsQuery(MarketingAnalyticsTableQueryRunner):
    def sessions_query(self, goal_id: str, group: str, source: str, campaign_id: str | None) -> ast.SelectQuery:
        self.validate()
        self._apply_drill_down_level()
        level = self.config.drill_down_level
        if level in (MarketingAnalyticsDrillDownLevel.AD, MarketingAnalyticsDrillDownLevel.AD_GROUP):
            raise ValidationError("Conversion recordings are not available at ad or ad group level.")

        goals, _ = self._filter_invalid_conversion_goals(self._get_team_conversion_goals())
        processors = self._create_conversion_goal_processors(goals)
        processor = next((p for p in processors if p.goal.conversion_goal_id == goal_id), None)
        if processor is None:
            raise ValidationError("This conversion goal is no longer available. Refresh the table and try again.")
        if isinstance(processor.goal, ConversionGoalFilter3):
            raise ValidationError("Conversion recordings are only available for event and action goals.")
        processor.include_session_ids = True

        # Resolve through the table's own joins: the displayed campaign can come from costs, not its UTM.
        table = self.to_query()
        key_fields = [self.config.campaign_field]
        if level in (MarketingAnalyticsDrillDownLevel.CAMPAIGN, MarketingAnalyticsDrillDownLevel.CHANNEL_SOURCE):
            key_fields.append(self.config.source_field)
        if level == MarketingAnalyticsDrillDownLevel.CAMPAIGN:
            key_fields.append(self.config.id_field)
        table.select.extend(
            ast.Alias(
                alias=f"_conversion_{field}",
                expr=ast.Field(chain=self.config.get_unified_conversion_field_chain(field)),
            )
            for field in key_fields
        )
        row_conditions = [
            parse_expr(
                "{field} = {value}",
                {
                    "field": ast.Field(chain=[self.config.get_campaign_column_alias()]),
                    "value": ast.Constant(value=group),
                },
            )
        ]
        if level in (MarketingAnalyticsDrillDownLevel.CAMPAIGN, MarketingAnalyticsDrillDownLevel.CHANNEL_SOURCE):
            row_conditions.append(parse_expr("Source = {source}", {"source": ast.Constant(value=source)}))
        if level == MarketingAnalyticsDrillDownLevel.CAMPAIGN and not (
            self.query.compareFilter and self.query.compareFilter.compare
        ):
            row_conditions.append(parse_expr("ID = {id}", {"id": ast.Constant(value=campaign_id or "-")}))
        selected_keys = ast.SelectQuery(
            select=[ast.Tuple(exprs=[ast.Field(chain=[f"_conversion_{field}"]) for field in key_fields])],
            select_from=ast.JoinExpr(table=table, alias="table_rows"),
            where=ast.And(exprs=row_conditions),
        )

        conversions = processor.generate_cte_query(
            self._get_where_conditions(
                date_range=self.query_date_range,
                include_date_range=True,
                date_field=processor.get_date_field(),
                use_date_not_datetime=True,
            ),
            date_from=self.query_date_range.date_from(),
            date_to=self.query_date_range.date_to(),
        )
        grouping_fields = {self.config.campaign_field, self.config.id_field, self.config.source_field}
        conversions.select = [
            col for col in conversions.select if isinstance(col, ast.Alias) and col.alias in grouping_fields
        ]
        conversions.group_by = None
        session_id = (
            ast.Field(chain=["session_id"])
            if processor.uses_attribution_pipeline
            else parse_expr("toString(ifNull(events.properties.$session_id, ''))")
        )
        conversions.select.append(ast.Alias(alias="conversion_session_id", expr=session_id))

        mapped_fields: dict[str, ast.Expr] = {field: ast.Field(chain=[field]) for field in grouping_fields}
        if level == MarketingAnalyticsDrillDownLevel.CAMPAIGN:
            mapped_fields[self.config.campaign_field], mapped_fields[self.config.id_field] = ConversionGoalsAggregator(
                [processor], self.config
            )._apply_campaign_name_mappings(
                mapped_fields[self.config.campaign_field],
                mapped_fields[self.config.id_field],
                mapped_fields[self.config.source_field],
            )
        sessions = parse_select(
            "SELECT DISTINCT conversion_session_id FROM {conversions} WHERE {key} IN {keys}"
            " AND notEmpty(conversion_session_id) AND conversion_session_id != '00000000-0000-0000-0000-000000000000'",
            {
                "conversions": conversions,
                "key": ast.Tuple(exprs=[mapped_fields[field] for field in key_fields]),
                "keys": selected_keys,
            },
        )
        assert isinstance(sessions, ast.SelectQuery)
        return sessions

    def sessions(
        self, goal_id: str, group: str, source: str, campaign_id: str | None, after: str | None, limit: int
    ) -> ConversionRecordingsResponse:
        try:
            query = self.sessions_query(goal_id, group, source, campaign_id)
        except MarketingPrecomputeNotReady as not_ready:
            handle_not_ready(team=self.team, query=not_ready.query or self.query)
            return {"session_ids": [], "has_more": False, "preparing": True}

        paginator = HogQLHasMorePaginator(limit=limit)
        sessions = parse_select(
            "SELECT conversion_session_id FROM {conversions} WHERE conversion_session_id > {after} ORDER BY conversion_session_id",
            {"conversions": query, "after": ast.Constant(value=after or "")},
        )
        paginator.execute_hogql_query(
            query=sessions,
            query_type="marketing_analytics_conversion_recordings",
            team=self.team,
            user=self.user,
            modifiers=self.modifiers,
            context=self._shared_hogql_context,
            # The row selection embeds the full table query, which groups by high-cardinality campaign
            # dimensions. Let the GROUP BY spill to disk, as the table runner does, rather than hit the memory limit.
            settings=HogQLGlobalSettings(max_bytes_before_external_group_by=MARKETING_SPILL_AFTER_BYTES),
        )
        return {
            "session_ids": [str(row[0]) for row in paginator.results],
            "has_more": paginator.has_more(),
            "preparing": False,
        }
