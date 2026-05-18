# LinkedIn Ads Marketing Source Adapter

from posthog.schema import NativeMarketingSource

from posthog.hogql import ast

from ..constants import INTEGRATION_DEFAULT_SOURCES, INTEGRATION_PRIMARY_SOURCE
from .base import LinkedinAdsConfig, MarketingSourceAdapter, ValidationResult


class LinkedinAdsAdapter(MarketingSourceAdapter[LinkedinAdsConfig]):
    """
    Adapter for LinkedIn Ads native marketing data.
    Expects config with:
    - campaign_table (campaign_groups) + stats_table (campaign_group_stats): always required
    - adset_table (campaigns) + adset_stats_table (campaign_stats): optional; needed
      for AD_GROUP drill-down
    - ad_table (creatives) + ad_stats_table (creative_stats): optional; needed for
      AD drill-down

    LinkedIn's hierarchy is `account → campaign_group → campaign → creative`. We
    map CampaignGroups to "campaign" (matching the marketer's mental model),
    `campaigns` resource to "ad group" (LinkedIn's API confusingly uses "campaign"
    for what most platforms call "ad group"), and `creatives` to "ad".
    """

    _source_type = NativeMarketingSource.LINKEDIN_ADS

    _stats_date_column = "date_start"
    _campaign_pk_column = "id"
    _campaign_name_column = "name"
    _campaign_stats_fk_column = "campaign_group_id"
    # `campaign_group_id` is surfaced from the URN `campaignGroup` column — see
    # VIRTUAL_COLUMN_URN_MAPPING in linkedin_ads/schemas.py.
    _adset_pk_column = "id"
    _adset_name_column = "name"
    _adset_campaign_fk_column = "campaign_group_id"
    _adset_stats_fk_column = "campaign_id"
    # `creatives.id` is URN-extracted at import time so it lines up with the
    # `creative_id` virtual column on creative_stats.
    _ad_pk_column = "id"
    _ad_name_column = "name"
    _ad_adset_fk_column = "campaign_id"
    _ad_campaign_fk_column = "campaign_group_id"  # not used: AD joins through adsets first
    _ad_stats_fk_column = "creative_id"

    @classmethod
    def get_source_identifier_mapping(cls) -> dict[str, list[str]]:
        primary = INTEGRATION_PRIMARY_SOURCE[cls._source_type]
        sources = INTEGRATION_DEFAULT_SOURCES[cls._source_type]
        return {primary: list(sources)}

    def get_source_type(self) -> str:
        return "LinkedinAds"

    def validate(self) -> ValidationResult:
        """Validate LinkedIn Ads tables and required fields"""
        errors: list[str] = []

        try:
            if self.config.campaign_table.name and "campaign_groups" not in self.config.campaign_table.name.lower():
                errors.append(
                    f"Campaign table name '{self.config.campaign_table.name}' doesn't contain 'campaign_groups'"
                )
            if self.config.stats_table.name and "campaign_group_stats" not in self.config.stats_table.name.lower():
                errors.append(
                    f"Stats table name '{self.config.stats_table.name}' doesn't contain 'campaign_group_stats'"
                )

            is_valid = len(errors) == 0
            self._log_validation_errors(errors)

            return ValidationResult(is_valid=is_valid, errors=errors)

        except Exception as e:
            error_msg = f"Validation error: {str(e)}"
            self.logger.exception("LinkedIn Ads validation failed", error=error_msg)
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
        stats_table_name = self._level_tables().stats_table.name
        base_currency = self.context.base_currency

        cost_field = ast.Field(chain=[stats_table_name, "cost_in_usd"])
        cost_float = ast.Call(
            name="ifNull",
            args=[ast.Call(name="toFloat", args=[cost_field]), ast.Constant(value=0)],
        )
        sum = ast.Call(name="SUM", args=[cost_float])

        # LinkedIn Ads costs are already in USD, convert to base currency if not USD
        if base_currency.upper() != "USD":
            usd_currency = ast.Constant(value="USD")
            convert_currency = ast.Call(
                name="convertCurrency", args=[usd_currency, ast.Constant(value=base_currency), sum]
            )
            return ast.Call(name="toFloat", args=[convert_currency])

        # Base currency is already USD, no conversion needed
        return ast.Call(name="toFloat", args=[sum])

    def _get_reported_conversion_field(self) -> ast.Expr:
        stats_table_name = self._level_tables().stats_table.name
        field_as_float = ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, "external_website_conversions"])]),
                ast.Constant(value=0),
            ],
        )
        sum = ast.Call(name="SUM", args=[field_as_float])
        return ast.Call(name="toFloat", args=[sum])

    def _get_reported_conversion_value_field(self) -> ast.Expr:
        stats_table = self._level_tables().stats_table
        stats_table_name = stats_table.name

        if not self._table_has_column(stats_table, "conversion_value_in_local_currency"):
            return ast.Constant(value=0)

        field_as_float = ast.Call(
            name="ifNull",
            args=[
                ast.Call(
                    name="toFloat",
                    args=[ast.Field(chain=[stats_table_name, "conversion_value_in_local_currency"])],
                ),
                ast.Constant(value=0),
            ],
        )

        converted = self._apply_currency_conversion(stats_table, stats_table_name, "currency", field_as_float)
        if converted:
            return ast.Call(name="SUM", args=[converted])

        sum = ast.Call(name="SUM", args=[field_as_float])
        return ast.Call(name="toFloat", args=[sum])
