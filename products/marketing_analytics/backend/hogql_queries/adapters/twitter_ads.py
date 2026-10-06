from posthog.schema import MarketingAnalyticsDrillDownLevel, NativeMarketingSource

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from ..constants import INTEGRATION_DEFAULT_SOURCES, INTEGRATION_PRIMARY_SOURCE
from .base import HierarchicalNativeAdsConfig, MarketingSourceAdapter, ValidationResult


class TwitterAdsAdapter(MarketingSourceAdapter[HierarchicalNativeAdsConfig]):
    _source_type = NativeMarketingSource.TWITTER_ADS
    _stats_date_column = "date"
    _campaign_stats_fk_column = "entity_id"
    _adset_campaign_fk_column = "campaign_id"
    _adset_stats_fk_column = "entity_id"

    @classmethod
    def get_source_identifier_mapping(cls) -> dict[str, list[str]]:
        return {INTEGRATION_PRIMARY_SOURCE[cls._source_type]: list(INTEGRATION_DEFAULT_SOURCES[cls._source_type])}

    def get_source_type(self) -> str:
        return self._source_type.value

    def validate(self) -> ValidationResult:
        tables = self._level_tables()
        required_columns = [
            (tables.entity_table, (tables.entity_id_column, tables.entity_name_column)),
            (
                tables.stats_table,
                (
                    tables.stats_entity_id_column,
                    "date",
                    "impressions",
                    "clicks",
                    "billed_charge_local_micro",
                    "currency",
                ),
            ),
        ]
        if self.context.drill_down_level == MarketingAnalyticsDrillDownLevel.AD_GROUP:
            required_columns.extend(
                [
                    (tables.entity_table, (self._adset_campaign_fk_column,)),
                    (self.config.campaign_table, (self._campaign_pk_column, self._campaign_name_column)),
                ]
            )
        errors = [
            f"X Ads is missing '{column}' in '{table.name}'. Sync this table again."
            for table, columns in required_columns
            for column in columns
            if not self._table_has_column(table, column)
        ]
        return ValidationResult(is_valid=not errors, errors=errors)

    def _sum_metric(self, column: str) -> ast.Expr:
        table = self._level_tables().stats_table
        return parse_expr(
            "sum(coalesce(toFloat({value}), 0))",
            placeholders={"value": ast.Field(chain=[table.name, column])},
        )

    def _get_impressions_field(self) -> ast.Expr:
        return self._sum_metric("impressions")

    def _get_clicks_field(self) -> ast.Expr:
        return self._sum_metric("clicks")

    def _get_cost_field(self) -> ast.Expr:
        table = self._level_tables().stats_table
        return parse_expr(
            "sum(toFloat(convertCurrency(coalesce({currency}, {target}), {target}, "
            "coalesce(toFloat({spend}), 0) / 1000000, coalesce(toDate({date}), today())))) "
            "+ throwIf(countIf(empty(coalesce({currency}, ''))) > 0, {message})",
            placeholders={
                "spend": ast.Field(chain=[table.name, "billed_charge_local_micro"]),
                "currency": ast.Field(chain=[table.name, "currency"]),
                "target": ast.Constant(value=self.context.base_currency),
                "date": ast.Field(chain=[table.name, "date"]),
                "message": ast.Constant(
                    value="X Ads currency is missing. Fully resync the stats table, then try again."
                ),
            },
        )

    def _get_reported_conversion_field(self) -> ast.Expr:
        # The source imports ENGAGEMENT and BILLING metrics, not conversion reports.
        return ast.Constant(value=0)

    def _get_reported_conversion_value_field(self) -> ast.Expr:
        return ast.Constant(value=0)
