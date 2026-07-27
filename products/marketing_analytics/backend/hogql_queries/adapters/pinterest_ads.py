# Pinterest Ads Marketing Source Adapter

from posthog.schema import NativeMarketingSource

from posthog.hogql import ast

from products.warehouse_sources.backend.facade.models import DataWarehouseTable

from ..constants import INTEGRATION_DEFAULT_SOURCES, INTEGRATION_PRIMARY_SOURCE
from .base import MarketingSourceAdapter, PinterestAdsConfig, ValidationResult


class PinterestAdsAdapter(MarketingSourceAdapter[PinterestAdsConfig]):
    """
    Adapter for Pinterest Ads native marketing data.
    Expects config with:
    - campaign_table + stats_table (campaign_analytics): always required
    - adset_table (ad_groups) + adset_stats_table (ad_group_analytics): optional
    - ad_table + ad_stats_table (ad_analytics): optional
    """

    _source_type = NativeMarketingSource.PINTEREST_ADS

    # Pinterest entity tables use `id` as PK; analytics tables key by
    # `campaign_id` / `ad_group_id` / `ad_id` and partition by `date`.
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
        return "PinterestAds"

    def validate(self) -> ValidationResult:
        """Validate Pinterest Ads tables and required fields"""
        errors: list[str] = []

        try:
            if self.config.campaign_table.name and "campaigns" not in self.config.campaign_table.name.lower():
                errors.append(f"Campaign table name '{self.config.campaign_table.name}' doesn't contain 'campaigns'")
            if self.config.stats_table.name and "campaign_analytics" not in self.config.stats_table.name.lower():
                errors.append(f"Stats table name '{self.config.stats_table.name}' doesn't contain 'campaign_analytics'")

            if not self._has_stats_column(self.config.stats_table, "currency"):
                self.logger.warning(
                    "Pinterest Ads stats table missing currency column, monetary values may be inaccurate",
                    stats_table=self.config.stats_table.name,
                )

            for col in ("total_impression", "total_clickthrough", "spend_in_dollar"):
                if not self._has_stats_column(self.config.stats_table, col):
                    self.logger.warning(
                        f"Pinterest Ads stats table missing '{col}' column, metric will be reported as 0",
                        stats_table=self.config.stats_table.name,
                    )

            is_valid = len(errors) == 0
            self._log_validation_errors(errors)

            return ValidationResult(is_valid=is_valid, errors=errors)

        except Exception as e:
            error_msg = f"Validation error: {str(e)}"
            self.logger.exception("Pinterest Ads validation failed", error=error_msg)
            return ValidationResult(is_valid=False, errors=[error_msg])

    def _has_stats_column(self, table: DataWarehouseTable, column_name: str) -> bool:
        """Pinterest's optional metric columns may be present-but-invalid (warehouse marks
        them with `valid: false` when the customer hasn't enabled them). Treat invalid as
        missing — `_table_has_column` doesn't know about the `valid` flag."""
        columns = getattr(table, "columns", None)
        if not columns or not hasattr(columns, "__contains__") or column_name not in columns:
            return False
        col_meta = columns[column_name]
        if isinstance(col_meta, dict) and not col_meta.get("valid", True):
            return False
        return True

    def _get_impressions_field(self) -> ast.Expr:
        stats_table = self._level_tables().stats_table
        if not self._has_stats_column(stats_table, "total_impression"):
            return ast.Call(name="toFloat", args=[ast.Constant(value=0)])

        field_as_float = ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table.name, "total_impression"])]),
                ast.Constant(value=0),
            ],
        )
        sum = ast.Call(name="SUM", args=[field_as_float])
        return ast.Call(name="toFloat", args=[sum])

    def _get_clicks_field(self) -> ast.Expr:
        stats_table = self._level_tables().stats_table
        if not self._has_stats_column(stats_table, "total_clickthrough"):
            return ast.Call(name="toFloat", args=[ast.Constant(value=0)])

        field_as_float = ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table.name, "total_clickthrough"])]),
                ast.Constant(value=0),
            ],
        )
        sum = ast.Call(name="SUM", args=[field_as_float])
        return ast.Call(name="toFloat", args=[sum])

    def _get_cost_field(self) -> ast.Expr:
        stats_table = self._level_tables().stats_table
        if not self._has_stats_column(stats_table, "spend_in_dollar"):
            return ast.Call(name="toFloat", args=[ast.Constant(value=0)])

        # Pinterest spend_in_dollar is already in standard dollar units (no micro conversion needed)
        spend_field = ast.Field(chain=[stats_table.name, "spend_in_dollar"])
        cost_float = ast.Call(name="toFloat", args=[spend_field])

        converted = self._apply_currency_conversion(stats_table, stats_table.name, "currency", cost_float)
        if converted:
            return ast.Call(name="SUM", args=[converted])

        return ast.Call(name="SUM", args=[cost_float])

    def _get_reported_conversion_field(self) -> ast.Expr:
        """Conversion count (total_conversions) — optional, not all accounts have conversion tracking"""
        stats_table = self._level_tables().stats_table
        if not self._has_stats_column(stats_table, "total_conversions"):
            return ast.Call(name="toFloat", args=[ast.Constant(value=0)])

        field_as_float = ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table.name, "total_conversions"])]),
                ast.Constant(value=0),
            ],
        )
        sum = ast.Call(name="SUM", args=[field_as_float])
        return ast.Call(name="toFloat", args=[sum])

    def _get_reported_conversion_value_field(self) -> ast.Expr:
        """Conversion value (total_checkout_value_in_micro_dollar) — optional, not all accounts have conversion tracking"""
        stats_table = self._level_tables().stats_table
        if not self._has_stats_column(stats_table, "total_checkout_value_in_micro_dollar"):
            return ast.Call(name="toFloat", args=[ast.Constant(value=0)])

        # total_checkout_value_in_micro_dollar is in micro dollars, divide by 1,000,000
        checkout_value_field = ast.Call(
            name="ifNull",
            args=[
                ast.ArithmeticOperation(
                    left=ast.Call(
                        name="toFloat",
                        args=[ast.Field(chain=[stats_table.name, "total_checkout_value_in_micro_dollar"])],
                    ),
                    op=ast.ArithmeticOperationOp.Div,
                    right=ast.Constant(value=1000000),
                ),
                ast.Constant(value=0),
            ],
        )

        converted = self._apply_currency_conversion(stats_table, stats_table.name, "currency", checkout_value_field)
        if converted:
            return ast.Call(name="SUM", args=[converted])

        sum = ast.Call(name="SUM", args=[checkout_value_field])
        return ast.Call(name="toFloat", args=[sum])
