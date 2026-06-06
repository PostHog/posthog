# TikTok Ads Marketing Source Adapter

from posthog.schema import NativeMarketingSource

from posthog.hogql import ast

from ..constants import INTEGRATION_DEFAULT_SOURCES, INTEGRATION_FIELD_NAMES, INTEGRATION_PRIMARY_SOURCE
from .base import MarketingSourceAdapter, TikTokAdsConfig, ValidationResult


class TikTokAdsAdapter(MarketingSourceAdapter[TikTokAdsConfig]):
    """
    Adapter for TikTok Ads native marketing data.
    Expects config with:
    - campaign_table + stats_table: always required
    - adset_table (ad_groups) + adset_stats_table (ad_group_report): optional
    - ad_table + ad_stats_table (ad_report): optional
    """

    _source_type = NativeMarketingSource.TIK_TOK_ADS

    # TikTok's reports are date-partitioned by `stat_time_day`. Entity tables use
    # `adgroup_id` / `ad_id` as primary keys; the campaign table sticks to the
    # generated config's `campaign_id` / `campaign_name`.
    _stats_date_column = "stat_time_day"
    _campaign_pk_column = INTEGRATION_FIELD_NAMES[NativeMarketingSource.TIK_TOK_ADS]["id_field"]
    _campaign_name_column = INTEGRATION_FIELD_NAMES[NativeMarketingSource.TIK_TOK_ADS]["name_field"]
    _campaign_stats_fk_column = "campaign_id"
    _adset_pk_column = "adgroup_id"
    _adset_name_column = "adgroup_name"
    _adset_campaign_fk_column = "campaign_id"
    _adset_stats_fk_column = "adgroup_id"
    _ad_pk_column = "ad_id"
    _ad_name_column = "ad_name"
    _ad_adset_fk_column = "adgroup_id"
    _ad_campaign_fk_column = "campaign_id"
    _ad_stats_fk_column = "ad_id"

    @classmethod
    def get_source_identifier_mapping(cls) -> dict[str, list[str]]:
        primary = INTEGRATION_PRIMARY_SOURCE[cls._source_type]
        sources = INTEGRATION_DEFAULT_SOURCES[cls._source_type]
        return {primary: list(sources)}

    def get_source_type(self) -> str:
        return "TikTokAds"

    def validate(self) -> ValidationResult:
        """Validate TikTok Ads tables and required fields"""
        errors: list[str] = []

        try:
            if self.config.campaign_table.name and "campaigns" not in self.config.campaign_table.name.lower():
                errors.append(f"Campaign table name '{self.config.campaign_table.name}' doesn't contain 'campaigns'")
            if self.config.stats_table.name and "campaign_report" not in self.config.stats_table.name.lower():
                errors.append(f"Stats table name '{self.config.stats_table.name}' doesn't contain 'campaign_report'")

            is_valid = len(errors) == 0
            self._log_validation_errors(errors)

            return ValidationResult(is_valid=is_valid, errors=errors)

        except Exception as e:
            error_msg = f"Validation error: {str(e)}"
            self.logger.exception("TikTok Ads validation failed", error=error_msg)
            return ValidationResult(is_valid=False, errors=[error_msg])

    def _get_impressions_field(self) -> ast.Expr:
        stats_table_name = self._level_tables().stats_table.name
        field_as_float = ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, "impressions"])]),
                ast.Constant(value=0),
            ],
        )
        sum = ast.Call(name="SUM", args=[field_as_float])
        return ast.Call(name="toFloat", args=[sum])

    def _get_clicks_field(self) -> ast.Expr:
        stats_table_name = self._level_tables().stats_table.name
        field_as_float = ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, "clicks"])]),
                ast.Constant(value=0),
            ],
        )
        sum = ast.Call(name="SUM", args=[field_as_float])
        return ast.Call(name="toFloat", args=[sum])

    def _get_cost_field(self) -> ast.Expr:
        stats_table = self._level_tables().stats_table
        stats_table_name = stats_table.name

        spend_field = ast.Field(chain=[stats_table_name, "spend"])
        spend_float = ast.Call(
            name="ifNull",
            args=[ast.Call(name="toFloat", args=[spend_field]), ast.Constant(value=0)],
        )

        converted = self._apply_currency_conversion(stats_table, stats_table_name, "currency", spend_float)
        if converted:
            return ast.Call(name="SUM", args=[converted])

        return ast.Call(name="SUM", args=[spend_float])

    def _get_reported_conversion_field(self) -> ast.Expr:
        stats_table_name = self._level_tables().stats_table.name
        field_as_float = ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, "conversion"])]),
                ast.Constant(value=0),
            ],
        )
        sum = ast.Call(name="SUM", args=[field_as_float])
        return ast.Call(name="toFloat", args=[sum])

    def _get_reported_conversion_value_field(self) -> ast.Expr:
        stats_table = self._level_tables().stats_table
        stats_table_name = stats_table.name

        if not self._table_has_column(stats_table, "total_complete_payment_rate"):
            return ast.Constant(value=0)

        field_as_float = ast.Call(
            name="ifNull",
            args=[
                ast.Call(
                    name="toFloat",
                    args=[ast.Field(chain=[stats_table_name, "total_complete_payment_rate"])],
                ),
                ast.Constant(value=0),
            ],
        )

        converted = self._apply_currency_conversion(stats_table, stats_table_name, "currency", field_as_float)
        if converted:
            return ast.Call(name="SUM", args=[converted])

        sum = ast.Call(name="SUM", args=[field_as_float])
        return ast.Call(name="toFloat", args=[sum])
