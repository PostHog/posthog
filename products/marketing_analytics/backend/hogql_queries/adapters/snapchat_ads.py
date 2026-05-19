# Snapchat Ads Marketing Source Adapter

from posthog.schema import NativeMarketingSource

from posthog.hogql import ast

from ..constants import (
    INTEGRATION_DEFAULT_SOURCES,
    INTEGRATION_PRIMARY_SOURCE,
    SNAPCHAT_CONVERSION_FIELDS,
    SNAPCHAT_CONVERSION_VALUE_FIELDS,
)
from .base import MarketingSourceAdapter, SnapchatAdsConfig, ValidationResult


class SnapchatAdsAdapter(MarketingSourceAdapter[SnapchatAdsConfig]):
    """
    Adapter for Snapchat Ads native marketing data.
    Expects config with:
    - campaign_table + stats_table (campaign_stats_daily): always required
    - adset_table (ad_squads) + adset_stats_table (ad_squad_stats_daily): optional
    - ad_table + ad_stats_table (ad_stats_daily): optional

    Snapchat calls "ad groups" `ad_squads`. All entity tables use `id` as PK; all
    stats tables also expose the entity ID as `id` (not `campaign_id`/`ad_squad_id`/
    `ad_id`), so FK columns on stats are just `id`.
    """

    _source_type = NativeMarketingSource.SNAPCHAT_ADS

    _stats_date_column = "start_time"
    _campaign_pk_column = "id"
    _campaign_name_column = "name"
    _campaign_stats_fk_column = "id"
    _adset_pk_column = "id"
    _adset_name_column = "name"
    _adset_campaign_fk_column = "campaign_id"
    _adset_stats_fk_column = "id"
    _ad_pk_column = "id"
    _ad_name_column = "name"
    _ad_adset_fk_column = "ad_squad_id"
    _ad_campaign_fk_column = "campaign_id"
    _ad_stats_fk_column = "id"

    @classmethod
    def get_source_identifier_mapping(cls) -> dict[str, list[str]]:
        primary = INTEGRATION_PRIMARY_SOURCE[cls._source_type]
        sources = INTEGRATION_DEFAULT_SOURCES[cls._source_type]
        return {primary: list(sources)}

    def get_source_type(self) -> str:
        return "SnapchatAds"

    def validate(self) -> ValidationResult:
        """Validate Snapchat Ads tables and required fields"""
        errors: list[str] = []

        try:
            if self.config.campaign_table.name and "campaigns" not in self.config.campaign_table.name.lower():
                errors.append(f"Campaign table name '{self.config.campaign_table.name}' doesn't contain 'campaigns'")
            if self.config.stats_table.name and "campaign_stats_daily" not in self.config.stats_table.name.lower():
                errors.append(
                    f"Stats table name '{self.config.stats_table.name}' doesn't contain 'campaign_stats_daily'"
                )

            is_valid = len(errors) == 0
            self._log_validation_errors(errors)

            return ValidationResult(is_valid=is_valid, errors=errors)

        except Exception as e:
            error_msg = f"Validation error: {str(e)}"
            self.logger.exception("Snapchat Ads validation failed", error=error_msg)
            return ValidationResult(is_valid=False, errors=[error_msg])

    def _get_source_name_field(self) -> ast.Expr:
        return ast.Call(name="toString", args=[ast.Constant(value="snapchat")])

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
        # Snapchat uses "swipes" instead of "clicks"
        stats_table_name = self._level_tables().stats_table.name
        field_as_float = ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, "swipes"])]),
                ast.Constant(value=0),
            ],
        )
        sum = ast.Call(name="SUM", args=[field_as_float])
        return ast.Call(name="toFloat", args=[sum])

    def _get_cost_field(self) -> ast.Expr:
        stats_table = self._level_tables().stats_table
        stats_table_name = stats_table.name

        # Snapchat spend is in micros (divide by 1,000,000)
        spend_field = ast.Field(chain=[stats_table_name, "spend"])
        spend_float = ast.Call(
            name="ifNull",
            args=[
                ast.ArithmeticOperation(
                    left=ast.Call(name="toFloat", args=[spend_field]),
                    op=ast.ArithmeticOperationOp.Div,
                    right=ast.Constant(value=1000000),
                ),
                ast.Constant(value=0),
            ],
        )

        converted = self._apply_currency_conversion(stats_table, stats_table_name, "currency", spend_float)
        if converted:
            return ast.Call(name="SUM", args=[converted])

        return ast.Call(name="SUM", args=[spend_float])

    def _build_conversion_sum(self, field_names: list[str], apply_currency: bool = False) -> ast.Expr:
        stats_table = self._level_tables().stats_table
        stats_table_name = stats_table.name
        exprs: list[ast.Expr] = []

        try:
            columns = getattr(stats_table, "columns", None)
            if columns and hasattr(columns, "__contains__"):
                for field_name in field_names:
                    if field_name in columns:
                        exprs.append(
                            ast.Call(
                                name="ifNull",
                                args=[
                                    ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, field_name])]),
                                    ast.Constant(value=0),
                                ],
                            )
                        )
        except (TypeError, AttributeError, KeyError):
            pass

        if not exprs:
            return ast.Constant(value=0)

        total = exprs[0]
        for expr in exprs[1:]:
            total = ast.Call(name="plus", args=[total, expr])

        if apply_currency:
            converted = self._apply_currency_conversion(stats_table, stats_table_name, "currency", total)
            if converted:
                return ast.Call(name="SUM", args=[converted])

        return ast.Call(name="toFloat", args=[ast.Call(name="SUM", args=[total])])

    def _get_reported_conversion_field(self) -> ast.Expr:
        return self._build_conversion_sum(SNAPCHAT_CONVERSION_FIELDS)

    def _get_reported_conversion_value_field(self) -> ast.Expr:
        return self._build_conversion_sum(SNAPCHAT_CONVERSION_VALUE_FIELDS, apply_currency=True)
