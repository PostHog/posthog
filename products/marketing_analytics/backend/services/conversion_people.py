from typing import TypedDict

from rest_framework.exceptions import ValidationError

from posthog.schema import ActorsQuery, ConversionGoalFilter3, MarketingAnalyticsDrillDownLevel, PersonsArgMaxVersion

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from posthog.api.person import PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
from posthog.hogql_queries.actor_strategies import PersonStrategy
from posthog.hogql_queries.paginators import HogQLHasMorePaginator

from products.marketing_analytics.backend.hogql_queries.conversion_goals_aggregator import ConversionGoalsAggregator
from products.marketing_analytics.backend.hogql_queries.errors import MarketingPrecomputeNotReady
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_table_query_runner import (
    MarketingAnalyticsTableQueryRunner,
)
from products.marketing_analytics.backend.hogql_queries.marketing_lazy_precompute import handle_not_ready


class ConversionPerson(TypedDict):
    id: str
    name: str


class ConversionPeopleResponse(TypedDict):
    results: list[ConversionPerson]
    has_more: bool
    preparing: bool


class ConversionPeopleQuery(MarketingAnalyticsTableQueryRunner):
    def people_query(self, goal_id: str, group: str, source: str, campaign_id: str | None) -> ast.SelectQuery:
        self.validate()
        self._apply_drill_down_level()
        level = self.config.drill_down_level
        if level in (MarketingAnalyticsDrillDownLevel.AD, MarketingAnalyticsDrillDownLevel.AD_GROUP):
            raise ValidationError("Conversion people are not available at ad or ad group level.")

        goals, _ = self._filter_invalid_conversion_goals(self._get_team_conversion_goals())
        processors = self._create_conversion_goal_processors(goals)
        processor = next((p for p in processors if p.goal.conversion_goal_id == goal_id), None)
        if processor is None:
            raise ValidationError("This conversion goal is no longer available. Refresh the table and try again.")

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
        if level == MarketingAnalyticsDrillDownLevel.CAMPAIGN and campaign_id is not None:
            row_conditions.append(parse_expr("ID = {id}", {"id": ast.Constant(value=campaign_id)}))
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
        conversions.distinct = True
        if isinstance(processor.goal, ConversionGoalFilter3):
            table_name = processor.get_table_name()
            distinct_id = processor.goal.schema_map.get("distinct_id_field") or processor.goal.distinct_id_field
            assert conversions.select_from is not None
            conversions.select_from.next_join = ast.JoinExpr(
                table=ast.Field(chain=["person_distinct_ids"]),
                alias="conversion_identity",
                join_type="INNER JOIN",
                constraint=ast.JoinConstraint(
                    constraint_type="ON",
                    expr=parse_expr(
                        "conversion_identity.distinct_id = toString({distinct_id})",
                        {
                            "distinct_id": ast.Field(chain=[table_name, distinct_id]),
                        },
                    ),
                ),
            )
            person_id = ast.Field(chain=["conversion_identity", "person_id"])
        else:
            person_id = ast.Field(chain=["person_id"])
        conversions.select.append(ast.Alias(alias="actor_id", expr=person_id))

        mapped_fields: dict[str, ast.Expr] = {field: ast.Field(chain=[field]) for field in grouping_fields}
        if level == MarketingAnalyticsDrillDownLevel.CAMPAIGN:
            mapped_fields[self.config.campaign_field], mapped_fields[self.config.id_field] = ConversionGoalsAggregator(
                [processor], self.config
            )._apply_campaign_name_mappings(
                mapped_fields[self.config.campaign_field],
                mapped_fields[self.config.id_field],
                mapped_fields[self.config.source_field],
            )
        people = parse_select(
            "SELECT DISTINCT actor_id FROM {conversions} WHERE {key} IN {keys}",
            {
                "conversions": conversions,
                "key": ast.Tuple(exprs=[mapped_fields[field] for field in key_fields]),
                "keys": selected_keys,
            },
        )
        assert isinstance(people, ast.SelectQuery)
        return people

    def people(
        self, goal_id: str, group: str, source: str, campaign_id: str | None, search: str, offset: int, limit: int
    ) -> ConversionPeopleResponse:
        try:
            query = self.people_query(goal_id, group, source, campaign_id)
        except MarketingPrecomputeNotReady as not_ready:
            handle_not_ready(team=self.team, query=not_ready.query or self.query)
            return {"results": [], "has_more": False, "preparing": True}

        paginator = HogQLHasMorePaginator(limit=limit, offset=offset)
        strategy = PersonStrategy(team=self.team, query=ActorsQuery(search=search), paginator=paginator, user=self.user)
        conditions = strategy.filter_conditions()
        names = [
            parse_expr("nullIf(toString({property}), '')", {"property": ast.Field(chain=["properties", name])})
            for name in (self.team.person_display_name_properties or PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES)
        ]
        # PersonsTable moves the `persons.id IN` join condition into its deduplication subquery.
        # Without it, the equality join deduplicates every person in the team before it filters.
        people = parse_select(
            (
                "SELECT id, {name} FROM {conversions} AS converted INNER JOIN persons"
                " ON persons.id = converted.actor_id AND persons.id IN (SELECT actor_id FROM {conversions})"
                " WHERE {conditions} ORDER BY id"
            ),
            {
                "name": ast.Call(name="coalesce", args=[*names, parse_expr("toString(id)")]),
                "conversions": query,
                "conditions": ast.And(exprs=conditions) if conditions else ast.Constant(value=True),
            },
        )
        paginator.execute_hogql_query(
            query=people,
            query_type="marketing_analytics_conversion_people",
            team=self.team,
            user=self.user,
            modifiers=self.modifiers.model_copy(update={"personsArgMaxVersion": PersonsArgMaxVersion.V2}),
            context=self._shared_hogql_context,
        )
        return {
            "results": [{"id": str(row[0]), "name": str(row[1])} for row in paginator.results],
            "has_more": paginator.has_more(),
            "preparing": False,
        }
