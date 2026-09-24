from posthog.schema import NativeMarketingSource

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from ..constants import INTEGRATION_DEFAULT_SOURCES, INTEGRATION_PRIMARY_SOURCE
from .base import HierarchicalNativeAdsConfig, MarketingSourceAdapter, ValidationResult


class AppleSearchAdsAdapter(MarketingSourceAdapter[HierarchicalNativeAdsConfig]):
    _source_type = NativeMarketingSource.APPLE_SEARCH_ADS
    _stats_date_column = "date"
    _campaign_stats_fk_column = "campaign_id"
    _adset_campaign_fk_column = "campaign_id"
    _adset_stats_fk_column = "ad_group_id"

    @classmethod
    def get_source_identifier_mapping(cls) -> dict[str, list[str]]:
        return {INTEGRATION_PRIMARY_SOURCE[cls._source_type]: list(INTEGRATION_DEFAULT_SOURCES[cls._source_type])}

    def get_source_type(self) -> str:
        return self._source_type.value

    def validate(self) -> ValidationResult:
        tables = self._level_tables()
        errors = [
            f"Apple Ads is missing '{column}' in '{table.name}'. Sync this table again."
            for table, columns in (
                (tables.entity_table, (tables.entity_id_column, tables.entity_name_column)),
                (tables.stats_table, (tables.stats_entity_id_column, "date", "impressions", "taps", "local_spend")),
            )
            for column in columns
            if not self._table_has_column(table, column)
        ]
        return ValidationResult(is_valid=not errors, errors=errors)

    def _sum_metric(self, *columns: str) -> ast.Expr:
        table = self._level_tables().stats_table
        fields: list[ast.Expr] = [
            ast.Call(name="toFloat", args=[ast.Field(chain=[table.name, column])])
            for column in columns
            if self._table_has_column(table, column)
        ]
        if not fields:
            return ast.Constant(value=0)
        return ast.Call(name="sum", args=[ast.Call(name="coalesce", args=[*fields, ast.Constant(value=0)])])

    def _get_impressions_field(self) -> ast.Expr:
        return self._sum_metric("impressions")

    def _get_clicks_field(self) -> ast.Expr:
        return self._sum_metric("taps")

    def _get_cost_field(self) -> ast.Expr:
        table = self._level_tables().stats_table
        # Apple stores spend as a JSON money object in account currency, including under API v1.
        return parse_expr(
            "sum(toFloat(convertCurrency({spend}.currency, {currency}, "
            "coalesce(toFloat({spend}.amount), 0), coalesce(toDate({date}), today()))))",
            placeholders={
                "spend": ast.Field(chain=[table.name, "local_spend"]),
                "currency": ast.Constant(value=self.context.base_currency),
                "date": ast.Field(chain=[table.name, "date"]),
            },
        )

    def _get_reported_conversion_field(self) -> ast.Expr:
        # API v1 renamed installs; repinned sources can contain both column generations.
        return self._sum_metric("total_installs", "installs")

    def _get_reported_conversion_value_field(self) -> ast.Expr:
        return ast.Constant(value=0)
