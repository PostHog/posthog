from posthog.schema import MarketingAnalyticsDrillDownLevel, NativeMarketingSource

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from ..constants import INTEGRATION_DEFAULT_SOURCES, INTEGRATION_PRIMARY_SOURCE
from .base import HierarchicalNativeAdsConfig, MarketingSourceAdapter, ValidationResult

# X reports a campaign's spend in millionths of the funding instrument's currency.
_MICROS_PER_UNIT = 1000000


class TwitterAdsAdapter(MarketingSourceAdapter[HierarchicalNativeAdsConfig]):
    """X Ads (Twitter Ads) campaigns and ad groups.

    X splits a day's figures by placement, so `campaign_stats` holds up to three rows per entity
    per day (`ALL_ON_TWITTER`, `SPOTLIGHT`, `TREND`). The base adapter groups by campaign and date
    and every metric here aggregates, so the placements add up into the one row a tile wants.
    """

    _source_type = NativeMarketingSource.TWITTER_ADS
    _stats_date_column = "date"
    _campaign_pk_column = "id"
    _campaign_name_column = "name"
    # Both stats tables name their entity `entity_id`, whatever level that entity sits at.
    _campaign_stats_fk_column = "entity_id"
    _adset_pk_column = "id"
    _adset_name_column = "name"
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
                    self._stats_date_column,
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
        if not self._table_has_column(table, column):
            return ast.Constant(value=0)
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
        if not self._table_has_column(table, "billed_charge_local_micro"):
            return ast.Constant(value=0)

        spend = parse_expr(
            "coalesce(toFloat({value}), 0) / {micros}",
            placeholders={
                "value": ast.Field(chain=[table.name, "billed_charge_local_micro"]),
                "micros": ast.Constant(value=_MICROS_PER_UNIT),
            },
        )
        converted = self._apply_currency_conversion(table, table.name, "currency", spend)
        return ast.Call(name="sum", args=[converted or spend])

    def _get_reported_conversion_field(self) -> ast.Expr:
        # The source requests the ENGAGEMENT and BILLING metric groups, neither of which carries a
        # conversion count, so there is nothing to report until it asks for a conversion group.
        return ast.Constant(value=0)

    def _get_reported_conversion_value_field(self) -> ast.Expr:
        return ast.Constant(value=0)
