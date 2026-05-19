# Bing Ads Marketing Source Adapter

from posthog.schema import MarketingAnalyticsDrillDownLevel, NativeMarketingSource

from posthog.hogql import ast

from products.marketing_analytics.backend.hogql_queries.constants import (
    INTEGRATION_DEFAULT_SOURCES,
    INTEGRATION_PRIMARY_SOURCE,
)

from .base import BingAdsConfig, MarketingSourceAdapter, ValidationResult


class BingAdsAdapter(MarketingSourceAdapter[BingAdsConfig]):
    """
    Adapter for Bing Ads native marketing data.
    Expects config with:
    - campaign_table: campaigns entity table
    - stats_table: campaign_performance_report
    - adset_table / adset_stats_table: ad_group_performance_report (same table — Bing
      reports embed entity columns directly, see `_uses_unified_entity_stats` below)
    - ad_table / ad_stats_table: ad_performance_report (same table)

    Bing's performance reports embed `ad_group_id` / `ad_group_name` /
    `campaign_id` / `campaign_name` (and at ad level, also `ad_id` / `ad_title`)
    directly as columns, so there's no separate entity table at AD_GROUP / AD —
    the report is both. `_uses_unified_entity_stats` flips the base FROM/GROUP BY
    builders into the no-join code path.
    """

    _source_type = NativeMarketingSource.BING_ADS

    _stats_date_column = "time_period"
    _campaign_pk_column = "id"
    _campaign_name_column = "name"
    _campaign_stats_fk_column = "campaign_id"

    # Bing imports lowercase + snake-case the API's CamelCase fields, so the
    # `AdGroupId` column arrives as `ad_group_id`, `AdTitle` as `ad_title`, etc.
    _uses_unified_entity_stats = True
    _adset_pk_column = "ad_group_id"
    _adset_name_column = "ad_group_name"
    _ad_pk_column = "ad_id"
    _ad_name_column = "ad_title"

    @classmethod
    def get_source_identifier_mapping(cls) -> dict[str, list[str]]:
        primary = INTEGRATION_PRIMARY_SOURCE[cls._source_type]
        sources = INTEGRATION_DEFAULT_SOURCES[cls._source_type]
        return {primary: list(sources)}

    def get_source_type(self) -> str:
        return "BingAds"

    def validate(self) -> ValidationResult:
        """Validate Bing Ads tables and required fields"""
        errors: list[str] = []

        try:
            if self.config.campaign_table.name and "campaigns" not in self.config.campaign_table.name.lower():
                errors.append(f"Campaign table name '{self.config.campaign_table.name}' doesn't contain 'campaigns'")
            if (
                self.config.stats_table.name
                and "campaign_performance_report" not in self.config.stats_table.name.lower()
            ):
                errors.append(
                    f"Stats table name '{self.config.stats_table.name}' doesn't contain 'campaign_performance_report'"
                )

            is_valid = len(errors) == 0
            self._log_validation_errors(errors)

            return ValidationResult(is_valid=is_valid, errors=errors)

        except Exception as e:
            error_msg = f"Validation error: {str(e)}"
            self.logger.exception("Bing Ads validation failed", error=error_msg)
            return ValidationResult(is_valid=False, errors=[error_msg])

    def _get_source_name_field(self) -> ast.Expr:
        return ast.Call(name="toString", args=[ast.Constant(value="bing")])

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

        converted = self._apply_currency_conversion(stats_table, stats_table_name, "currency_code", spend_float)
        if converted:
            return ast.Call(name="SUM", args=[converted])

        return ast.Call(name="SUM", args=[spend_float])

    def _get_reported_conversion_field(self) -> ast.Expr:
        stats_table_name = self._level_tables().stats_table.name
        field_as_float = ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, "conversions"])]),
                ast.Constant(value=0),
            ],
        )
        sum = ast.Call(name="SUM", args=[field_as_float])
        return ast.Call(name="toFloat", args=[sum])

    def _get_reported_conversion_value_field(self) -> ast.Expr:
        stats_table = self._level_tables().stats_table
        stats_table_name = stats_table.name

        field_as_float = ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, "revenue"])]),
                ast.Constant(value=0),
            ],
        )

        converted = self._apply_currency_conversion(stats_table, stats_table_name, "currency_code", field_as_float)
        if converted:
            return ast.Call(name="SUM", args=[converted])

        sum = ast.Call(name="SUM", args=[field_as_float])
        return ast.Call(name="toFloat", args=[sum])

    def _get_from(self) -> ast.JoinExpr:
        """At AD_GROUP / AD the base unified-mode FROM applies (just `FROM <report>`,
        no joins). At CAMPAIGN we override because Bing requires explicit toString
        casts on both sides of the join: `campaigns.id` is Int64 in the warehouse but
        the report's `campaign_id` arrives as a String, and without casts the join
        silently produces zero matches.
        """
        if self.context.drill_down_level in (
            MarketingAnalyticsDrillDownLevel.AD_GROUP,
            MarketingAnalyticsDrillDownLevel.AD,
        ):
            return super()._get_from()

        campaign_table_name = self.config.campaign_table.name
        stats_table_name = self.config.stats_table.name

        left_field = ast.Call(name="toString", args=[ast.Field(chain=[campaign_table_name, "id"])])
        right_field = ast.Call(name="toString", args=[ast.Field(chain=[stats_table_name, "campaign_id"])])
        join_condition_expr = ast.CompareOperation(left=left_field, op=ast.CompareOperationOp.Eq, right=right_field)

        return ast.JoinExpr(
            table=ast.Field(chain=[campaign_table_name]),
            next_join=ast.JoinExpr(
                table=ast.Field(chain=[stats_table_name]),
                join_type="LEFT JOIN",
                constraint=ast.JoinConstraint(expr=join_condition_expr, constraint_type="ON"),
            ),
        )
