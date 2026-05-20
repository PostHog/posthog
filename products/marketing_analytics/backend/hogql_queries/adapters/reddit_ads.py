# Reddit Ads Marketing Source Adapter

from posthog.schema import NativeMarketingSource

from posthog.hogql import ast

from ..constants import INTEGRATION_DEFAULT_SOURCES, INTEGRATION_PRIMARY_SOURCE
from .base import MarketingSourceAdapter, RedditAdsConfig, ValidationResult


class RedditAdsAdapter(MarketingSourceAdapter[RedditAdsConfig]):
    """
    Adapter for Reddit Ads native marketing data.
    Expects config with:
    - campaign_table + stats_table (campaign_report): always required
    - adset_table (ad_groups) + adset_stats_table (ad_group_report): optional
    - ad_table + ad_stats_table (ad_report): optional
    """

    _source_type = NativeMarketingSource.REDDIT_ADS

    # Reddit's report tables key by `campaign_id` / `ad_group_id` / `ad_id` and date.
    _stats_date_column = "date"
    _campaign_pk_column = "id"
    _campaign_name_column = "name"
    _campaign_stats_fk_column = "campaign_id"
    _adset_pk_column = "id"
    _adset_name_column = "name"
    _adset_campaign_fk_column = "campaign_id"
    _adset_stats_fk_column = "ad_group_id"
    _ad_pk_column = "id"
    _ad_name_column = "name"
    _ad_adset_fk_column = "ad_group_id"
    _ad_campaign_fk_column = "campaign_id"
    _ad_stats_fk_column = "ad_id"

    @classmethod
    def get_source_identifier_mapping(cls) -> dict[str, list[str]]:
        primary = INTEGRATION_PRIMARY_SOURCE[cls._source_type]
        sources = INTEGRATION_DEFAULT_SOURCES[cls._source_type]
        return {primary: list(sources)}

    def get_source_type(self) -> str:
        return "RedditAds"

    def validate(self) -> ValidationResult:
        """Validate Reddit Ads tables and required fields"""
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
            self.logger.exception("Reddit Ads validation failed", error=error_msg)
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

        # Reddit reports spend in micros — divide by 1,000,000.
        spend_field = ast.Field(chain=[stats_table_name, "spend"])
        cost_standard = ast.ArithmeticOperation(
            left=spend_field, op=ast.ArithmeticOperationOp.Div, right=ast.Constant(value=1000000)
        )
        cost_float = ast.Call(name="toFloat", args=[cost_standard])

        converted = self._apply_currency_conversion(stats_table, stats_table_name, "currency", cost_float)
        if converted:
            return ast.Call(name="SUM", args=[converted])

        return ast.Call(name="SUM", args=[cost_float])

    def _get_reported_conversion_field(self) -> ast.Expr:
        """Get conversion count (number of conversions)"""
        stats_table_name = self._level_tables().stats_table.name
        field_as_float = ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, "key_conversion_total_count"])]),
                ast.Constant(value=0),
            ],
        )
        sum = ast.Call(name="SUM", args=[field_as_float])
        return ast.Call(name="toFloat", args=[sum])

    def _get_reported_conversion_value_field(self) -> ast.Expr:
        """Get conversion value (monetary value of conversions)"""
        stats_table = self._level_tables().stats_table
        stats_table_name = stats_table.name

        # Reddit Ads API: "Divide by 100: CONVERSION*TOTAL_VALUE"
        # See: https://ads-api.reddit.com/docs/v3/operations/Get%20A%20Report
        purchase_field = ast.Call(
            name="ifNull",
            args=[
                ast.ArithmeticOperation(
                    left=ast.Call(
                        name="toFloat",
                        args=[ast.Field(chain=[stats_table_name, "conversion_purchase_total_value"])],
                    ),
                    op=ast.ArithmeticOperationOp.Div,
                    right=ast.Constant(value=100),
                ),
                ast.Constant(value=0),
            ],
        )
        signup_field = ast.Call(
            name="ifNull",
            args=[
                ast.ArithmeticOperation(
                    left=ast.Call(
                        name="toFloat",
                        args=[ast.Field(chain=[stats_table_name, "conversion_signup_total_value"])],
                    ),
                    op=ast.ArithmeticOperationOp.Div,
                    right=ast.Constant(value=100),
                ),
                ast.Constant(value=0),
            ],
        )

        converted_purchase = self._apply_currency_conversion(stats_table, stats_table_name, "currency", purchase_field)
        converted_signup = self._apply_currency_conversion(stats_table, stats_table_name, "currency", signup_field)

        if converted_purchase and converted_signup:
            sum_purchase = ast.Call(name="SUM", args=[converted_purchase])
            sum_signup = ast.Call(name="SUM", args=[converted_signup])
            total = ast.ArithmeticOperation(left=sum_purchase, op=ast.ArithmeticOperationOp.Add, right=sum_signup)
            return ast.Call(name="toFloat", args=[total])

        sum_purchase = ast.Call(name="SUM", args=[purchase_field])
        sum_signup = ast.Call(name="SUM", args=[signup_field])
        total = ast.ArithmeticOperation(left=sum_purchase, op=ast.ArithmeticOperationOp.Add, right=sum_signup)
        return ast.Call(name="toFloat", args=[total])
