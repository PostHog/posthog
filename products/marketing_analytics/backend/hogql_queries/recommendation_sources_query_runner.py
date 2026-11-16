from abc import ABC, abstractmethod
from functools import cached_property
from typing import Any

from posthog.schema import MarketingAnalyticsRecommendationsSource, MarketingAnalyticsRecommendationsSourceType

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.query import create_default_modifiers_for_team, execute_hogql_query

from posthog.hogql_queries.query_runner import AR, AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.marketing_analytics.backend.hogql_queries.marketing_recommendations import RECOMMENDATION_SOURCE_TYPES
from products.warehouse_sources.backend.facade.api import (
    all_queryable_table_keys,
    list_schemas_for_source,
    list_sources,
)

ROW_LIMIT = 50000


class RecommendationSourcesQueryRunner(AnalyticsQueryRunner[AR], ABC):
    hogql_query_type: str

    @property
    @abstractmethod
    def query_date_range(self) -> QueryDateRange: ...

    @cached_property
    def hogql_database(self) -> Database:
        return Database.create_for(
            team=self.team,
            user=self.user,
            modifiers=create_default_modifiers_for_team(self.team, self.modifiers),
            timings=self.timings,
        )

    @cached_property
    def hogql_context(self) -> HogQLContext:
        return HogQLContext(
            team_id=self.team.pk,
            modifiers=create_default_modifiers_for_team(self.team, self.modifiers),
            database=self.hogql_database,
        )

    def to_query(self) -> ast.SelectQuery:
        return ast.SelectQuery(select=[ast.Constant(value=1)])

    def _project_sources(self) -> list[MarketingAnalyticsRecommendationsSource]:
        table_keys = all_queryable_table_keys(self.team.pk)
        sources = []
        for source in list_sources(self.team.pk):
            if source.source_type not in RECOMMENDATION_SOURCE_TYPES:
                continue
            tables = {
                schema.name: table_keys[schema.table_id].queryable_key
                for schema in list_schemas_for_source(source.id, self.team.pk)
                if schema.should_sync
                and schema.last_synced_at is not None
                and schema.table_id is not None
                and schema.table_id in table_keys
            }
            recommendation_source = _recommendation_source(source.source_type, tables)
            if recommendation_source is not None:
                sources.append(recommendation_source)
        return sources

    def _readable(self, table: str | None) -> bool:
        if not table:
            return False
        return self.hogql_database.has_table(table) and not self.hogql_database.is_table_access_denied(table)

    def _has_field(self, table: str, field: str) -> bool:
        return self.hogql_database.get_table(table.split(".")).has_field(field)

    def _field(self, table: str, field: str) -> ast.Expr:
        if self._has_field(table, field):
            return ast.Field(chain=[field])
        return ast.Constant(value=None)

    def _select(self, sql: str, table: str, **placeholders: ast.Expr) -> list[list[Any]]:
        date_range = self.query_date_range
        result = execute_hogql_query(
            query_type=self.hogql_query_type,
            query=parse_select(
                # HogQL caps a query without a LIMIT at 100 rows, and accounts often have more campaigns.
                sql if "LIMIT" in sql else f"{sql}\nLIMIT {ROW_LIMIT}",
                placeholders={
                    "table": ast.Field(chain=list[str | int](table.split("."))),
                    "date_from": ast.Constant(value=date_range.date_from()),
                    "date_to": ast.Constant(value=date_range.date_to()),
                    **placeholders,
                },
            ),
            context=self.hogql_context,
            team=self.team,
            user=self.user,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )
        return result.results or []

    def _customer_id(self, source: MarketingAnalyticsRecommendationsSource) -> str | None:
        table = source.campaignTable
        if not self._readable(table):
            return None
        assert table
        if not self._has_field(table, "customer_id"):
            return None
        rows = self._select("SELECT any(toString(customer_id)) FROM {table}", table)
        return rows[0][0] if rows and rows[0][0] else None

    def _account_label(self, source: MarketingAnalyticsRecommendationsSource) -> str:
        customer_id = self._customer_id(source)
        if customer_id and len(customer_id) == 10:
            customer_id = f"{customer_id[:3]}-{customer_id[3:6]}-{customer_id[6:]}"
        return f"Google Ads account {customer_id}" if customer_id else "Google Ads account"


def _recommendation_source(source_type: str, tables: dict[str, str]) -> MarketingAnalyticsRecommendationsSource | None:
    if source_type == "GoogleAds":
        if "campaign" not in tables or "campaign_stats" not in tables:
            return None
        return MarketingAnalyticsRecommendationsSource(
            sourceType=MarketingAnalyticsRecommendationsSourceType.GOOGLE_ADS,
            campaignTable=tables["campaign"],
            campaignStatsTable=tables["campaign_stats"],
            campaignImpressionShareTable=tables.get("campaign_impression_share_stats"),
            customerTable=tables.get("customer"),
            searchTermTable=tables.get("search_term_stats"),
            searchTermKeywordTable=tables.get("search_term_keyword_stats"),
            adTable=tables.get("ad"),
            performanceMaxSearchTermTable=tables.get("performance_max_search_term_stats"),
            campaignConversionActionTable=tables.get("campaign_conversion_action_stats"),
            searchTermConversionActionTable=tables.get("search_term_conversion_action_stats"),
        )
    query_table = tables.get("search_analytics_by_query") or tables.get("search_analytics_by_query_page")
    if query_table is None:
        return None
    return MarketingAnalyticsRecommendationsSource(
        sourceType=MarketingAnalyticsRecommendationsSourceType.GOOGLE_SEARCH_CONSOLE,
        queryTable=query_table,
        queryPageTable=tables.get("search_analytics_by_query_page"),
        sitesTable=tables.get("sites"),
    )
