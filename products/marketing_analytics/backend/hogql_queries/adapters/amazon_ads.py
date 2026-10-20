from posthog.schema import NativeMarketingSource

from posthog.hogql import ast

from ..constants import INTEGRATION_DEFAULT_SOURCES, INTEGRATION_PRIMARY_SOURCE
from .base import HierarchicalNativeAdsConfig, MarketingSourceAdapter, ValidationResult


class AmazonAdsAdapter(MarketingSourceAdapter[HierarchicalNativeAdsConfig]):
    _source_type = NativeMarketingSource.AMAZON_ADS
    _stats_date_column = "date"
    _campaign_stats_fk_column = "campaign_id"
    _campaign_pk_column = "campaign_id"

    @classmethod
    def get_source_identifier_mapping(cls) -> dict[str, list[str]]:
        return {INTEGRATION_PRIMARY_SOURCE[cls._source_type]: list(INTEGRATION_DEFAULT_SOURCES[cls._source_type])}

    def get_source_type(self) -> str:
        return self._source_type.value

    def validate(self) -> ValidationResult:
        tables = self._level_tables()
        errors = [
            f"Amazon Ads is missing '{column}' in '{table.name}'. Sync this table again."
            for table, columns in (
                (tables.entity_table, (tables.entity_id_column, tables.entity_name_column)),
                (
                    tables.stats_table,
                    (
                        tables.stats_entity_id_column,
                        "date",
                        "impressions",
                        "clicks",
                        "cost",
                        "campaign_budget_currency_code",
                    ),
                ),
            )
            for column in columns
            if not self._table_has_column(table, column)
        ]
        return ValidationResult(is_valid=not errors, errors=errors)

    def _sum_metric(self, column: str, *, monetary: bool = False) -> ast.Expr:
        table = self._level_tables().stats_table
        if not self._table_has_column(table, column):
            return ast.Constant(value=0)
        value: ast.Expr = ast.Call(
            name="coalesce",
            args=[ast.Call(name="toFloat", args=[ast.Field(chain=[table.name, column])]), ast.Constant(value=0)],
        )
        if monetary:
            value = self._apply_currency_conversion(table, table.name, "campaign_budget_currency_code", value) or value
        return ast.Call(name="sum", args=[value])

    def _get_impressions_field(self) -> ast.Expr:
        return self._sum_metric("impressions")

    def _get_clicks_field(self) -> ast.Expr:
        return self._sum_metric("clicks")

    def _get_cost_field(self) -> ast.Expr:
        return self._sum_metric("cost", monetary=True)

    def _get_reported_conversion_field(self) -> ast.Expr:
        # Attribution windows overlap, so only the 14-day purchase metric contributes.
        return self._sum_metric("purchases14d")

    def _get_reported_conversion_value_field(self) -> ast.Expr:
        return self._sum_metric("sales14d", monetary=True)
