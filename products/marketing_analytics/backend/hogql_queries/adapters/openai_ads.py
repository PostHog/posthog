from posthog.schema import NativeMarketingSource

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from ..constants import INTEGRATION_DEFAULT_SOURCES, INTEGRATION_PRIMARY_SOURCE
from .base import HierarchicalNativeAdsConfig, MarketingSourceAdapter, ValidationResult


class OpenAIAdsAdapter(MarketingSourceAdapter[HierarchicalNativeAdsConfig]):
    _source_type = NativeMarketingSource.OPEN_AI_ADS
    _stats_date_column = "start_time"
    _campaign_stats_fk_column = "campaign_id"

    @classmethod
    def get_source_identifier_mapping(cls) -> dict[str, list[str]]:
        return {INTEGRATION_PRIMARY_SOURCE[cls._source_type]: list(INTEGRATION_DEFAULT_SOURCES[cls._source_type])}

    def get_source_type(self) -> str:
        return self._source_type.value

    def validate(self) -> ValidationResult:
        tables = self._level_tables()
        errors = [
            f"OpenAI Ads is missing '{column}' in '{table.name}'. Sync this table again."
            for table, columns in (
                (tables.entity_table, (tables.entity_id_column, tables.entity_name_column)),
                (
                    tables.stats_table,
                    (
                        tables.stats_entity_id_column,
                        "start_time",
                        "impressions",
                        "clicks",
                        "spend",
                        "currency_code",
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
            value = self._apply_currency_conversion(table, table.name, "currency_code", value) or value
        return ast.Call(name="sum", args=[value])

    def _get_impressions_field(self) -> ast.Expr:
        return self._sum_metric("impressions")

    def _get_clicks_field(self) -> ast.Expr:
        return self._sum_metric("clicks")

    def _get_cost_field(self) -> ast.Expr:
        return parse_expr(
            "{spend} + throwIf(countIf(empty(coalesce({currency}, ''))) > 0, {message})",
            placeholders={
                "spend": self._sum_metric("spend", monetary=True),
                "currency": ast.Field(chain=[self._level_tables().stats_table.name, "currency_code"]),
                "message": ast.Constant(
                    value="OpenAI Ads currency is missing. Fully resync campaign_insights, then try again."
                ),
            },
        )

    def _get_reported_conversion_field(self) -> ast.Expr:
        return ast.Constant(value=0)

    def _get_reported_conversion_value_field(self) -> ast.Expr:
        return ast.Constant(value=0)
