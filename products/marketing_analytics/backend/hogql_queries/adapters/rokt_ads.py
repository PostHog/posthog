from posthog.schema import NativeMarketingSource

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from ..constants import INTEGRATION_DEFAULT_SOURCES, INTEGRATION_PRIMARY_SOURCE
from .base import HierarchicalNativeAdsConfig, MarketingSourceAdapter, ValidationResult


class RoktAdsAdapter(MarketingSourceAdapter[HierarchicalNativeAdsConfig]):
    _source_type = NativeMarketingSource.ROKT_ADS
    _stats_date_column = "datetime"
    _campaign_pk_column = "campaign_id"
    _campaign_name_column = "campaign_name"
    _campaign_stats_fk_column = "campaign_id"

    @classmethod
    def get_source_identifier_mapping(cls) -> dict[str, list[str]]:
        return {INTEGRATION_PRIMARY_SOURCE[cls._source_type]: list(INTEGRATION_DEFAULT_SOURCES[cls._source_type])}

    def get_source_type(self) -> str:
        return self._source_type.value

    def validate(self) -> ValidationResult:
        tables = self._level_tables()
        errors = [
            f"Rokt Ads is missing '{column}' in '{table.name}'. Sync this table again."
            for table, columns in (
                (tables.entity_table, (tables.entity_id_column, tables.entity_name_column)),
                (
                    tables.stats_table,
                    (
                        tables.stats_entity_id_column,
                        "datetime",
                        "impressions",
                        "referrals",
                        "gross_cost",
                        "currency_code",
                    ),
                ),
            )
            for column in columns
            if not self._table_has_column(table, column)
        ]
        return ValidationResult(is_valid=not errors, errors=errors)

    def _get_from(self) -> ast.JoinExpr:
        # The report already contains campaign identity; a self-join would multiply daily rows.
        return ast.JoinExpr(table=ast.Field(chain=[self.config.stats_table.name]))

    def _sum_metric(self, column: str) -> ast.Expr:
        table = self.config.stats_table
        if not self._table_has_column(table, column):
            return ast.Constant(value=0)
        return parse_expr(
            "sum(coalesce(toFloat({value}), 0))",
            placeholders={"value": ast.Field(chain=[table.name, column])},
        )

    def _get_impressions_field(self) -> ast.Expr:
        return self._sum_metric("impressions")

    def _get_clicks_field(self) -> ast.Expr:
        return self._sum_metric("referrals")

    def _sum_money(self, column: str) -> ast.Expr:
        table = self.config.stats_table
        if not self._table_has_column(table, column):
            return ast.Constant(value=0)
        return parse_expr(
            "sum(toFloat(convertCurrency(coalesce({currency}, {target}), {target}, coalesce(toFloat({value}), 0), "
            "coalesce(toDate({date}), today())))) "
            "+ throwIf(countIf(empty(coalesce({currency}, ''))) > 0, {message})",
            placeholders={
                "currency": ast.Field(chain=[table.name, "currency_code"]),
                "target": ast.Constant(value=self.context.base_currency),
                "value": ast.Field(chain=[table.name, column]),
                "date": ast.Field(chain=[table.name, "datetime"]),
                "message": ast.Constant(
                    value="Rokt Ads currency is missing. Fully resync CampaignPerformance, then try again."
                ),
            },
        )

    def _get_cost_field(self) -> ast.Expr:
        return self._sum_money("gross_cost")

    def _get_reported_conversion_field(self) -> ast.Expr:
        return self._sum_metric("conversions")

    def _get_reported_conversion_value_field(self) -> ast.Expr:
        return self._sum_money("conversion_value")
