# Meta Ads Marketing Source Adapter

from posthog.schema import NativeMarketingSource

from posthog.hogql import ast

from ..constants import INTEGRATION_DEFAULT_SOURCES, INTEGRATION_PRIMARY_SOURCE, META_CONVERSION_ACTION_TYPES
from .base import MarketingSourceAdapter, MetaAdsConfig, ValidationResult

# Use centralized conversion action types from constants
# Priority: omni (deduplicated) > fallback/aggregated (deduplicated by Meta) > specific (channel breakdowns)
META_OMNI_ACTION_TYPES = META_CONVERSION_ACTION_TYPES["omni"]
META_FALLBACK_ACTION_TYPES = META_CONVERSION_ACTION_TYPES["fallback"]
META_SPECIFIC_ACTION_TYPES = META_CONVERSION_ACTION_TYPES["specific"]


class MetaAdsAdapter(MarketingSourceAdapter[MetaAdsConfig]):
    """
    Adapter for Meta Ads native marketing data.
    Expects config with:
    - campaign_table + stats_table: always required
    - adset_table + adset_stats_table: optional; needed for AD_GROUP drill-down
    - ad_table + ad_stats_table: optional; needed for AD drill-down

    All FROM/JOIN/WHERE/GROUP BY plumbing comes from MarketingSourceAdapter — this
    adapter only customizes the cost/conversion field expressions (Meta encodes
    conversions as JSON arrays in `actions` / `action_values`).
    """

    _source_type = NativeMarketingSource.META_ADS

    # Hierarchy column metadata — Meta uses "id" / "name" on entity tables and
    # "<entity>_id" on stats tables.
    _stats_date_column = "date_stop"
    _campaign_pk_column = "id"
    _campaign_name_column = "name"
    _campaign_stats_fk_column = "campaign_id"
    _adset_pk_column = "id"
    _adset_name_column = "name"
    _adset_campaign_fk_column = "campaign_id"
    _adset_stats_fk_column = "adset_id"
    _ad_pk_column = "id"
    _ad_name_column = "name"
    _ad_adset_fk_column = "adset_id"
    _ad_campaign_fk_column = "campaign_id"
    _ad_stats_fk_column = "ad_id"

    @classmethod
    def get_source_identifier_mapping(cls) -> dict[str, list[str]]:
        """Meta Ads campaigns typically use 'meta' as the UTM source"""
        primary = INTEGRATION_PRIMARY_SOURCE[cls._source_type]
        sources = INTEGRATION_DEFAULT_SOURCES[cls._source_type]
        return {primary: list(sources)}

    def get_source_type(self) -> str:
        """Return unique identifier for this source type"""
        return "MetaAds"

    def validate(self) -> ValidationResult:
        """Validate Meta Ads tables and required fields"""
        errors: list[str] = []

        try:
            # Check for expected table name patterns
            if self.config.campaign_table.name and "campaigns" not in self.config.campaign_table.name.lower():
                errors.append(f"Campaign table name '{self.config.campaign_table.name}' doesn't contain 'campaigns'")
            if self.config.stats_table.name and "campaign_stats" not in self.config.stats_table.name.lower():
                errors.append(f"Stats table name '{self.config.stats_table.name}' doesn't contain 'campaign_stats'")

            is_valid = len(errors) == 0
            self._log_validation_errors(errors)

            return ValidationResult(is_valid=is_valid, errors=errors)

        except Exception as e:
            error_msg = f"Validation error: {str(e)}"
            self.logger.exception("Meta Ads validation failed", error=error_msg)
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
        # Meta's campaign / adset / ad stats schemas all expose `account_currency` (see
        # meta_ads/schemas.py), so conversion applies at every drill-down level. The
        # uncoverted fallback only fires for stale tables predating the schema field.
        stats_table = self._level_tables().stats_table
        stats_table_name = stats_table.name

        spend_field = ast.Field(chain=[stats_table_name, "spend"])
        spend_float = ast.Call(
            name="ifNull",
            args=[ast.Call(name="toFloat", args=[spend_field]), ast.Constant(value=0)],
        )

        converted = self._apply_currency_conversion(stats_table, stats_table_name, "account_currency", spend_float)
        if converted:
            return ast.Call(name="SUM", args=[converted])

        return ast.Call(name="SUM", args=[spend_float])

    def _build_action_type_filter(self, action_types: list[str]) -> ast.Expr:
        """Build filter condition for specified action types"""
        return ast.Or(
            exprs=[
                ast.CompareOperation(
                    left=ast.Call(
                        name="JSONExtractString", args=[ast.Field(chain=["x"]), ast.Constant(value="action_type")]
                    ),
                    op=ast.CompareOperationOp.Eq,
                    right=ast.Constant(value=action_type),
                )
                for action_type in action_types
            ]
        )

    def _build_array_sum_for_action_types(self, json_array_expr: ast.Expr, action_types: list[str]) -> ast.Expr:
        """Build arraySum expression for specified action types"""
        return ast.Call(
            name="arraySum",
            args=[
                ast.Lambda(
                    args=["x"],
                    expr=ast.Call(
                        name="JSONExtractFloat",
                        args=[ast.Field(chain=["x"]), ast.Constant(value="value")],
                    ),
                ),
                ast.Call(
                    name="arrayFilter",
                    args=[
                        ast.Lambda(args=["x"], expr=self._build_action_type_filter(action_types)),
                        ast.Call(name="JSONExtractArrayRaw", args=[json_array_expr]),
                    ],
                ),
            ],
        )

    def _build_actions_conversion_sum(self, column_name: str, apply_currency: bool = False) -> ast.Expr:
        """Build a SUM over conversion action types from a JSON array column.

        Uses a 3-tier priority to avoid double counting when users have both
        pixel and server-side (CAPI) events configured:
        1. Omni types (omni_lead, omni_purchase) — fully deduplicated by Meta
        2. Aggregated types (lead, purchase) — already deduplicated across channels
        3. Specific types (offsite_conversion.fb_pixel_lead) — channel-specific breakdowns

        Previously, tiers 2 and 3 were combined into a single fallback, causing
        double counting (e.g. lead=2 + offsite_conversion.fb_pixel_lead=2 = 4 instead of 2).

        Returns 0 if the column doesn't exist in the table.
        """
        stats_table = self._level_tables().stats_table
        stats_table_name = stats_table.name

        if not self._table_has_column(stats_table, column_name):
            return ast.Constant(value=0)

        field = ast.Field(chain=[stats_table_name, column_name])
        field_non_null = ast.Call(name="coalesce", args=[field, ast.Constant(value="[]")])

        omni_sum = self._build_array_sum_for_action_types(field_non_null, META_OMNI_ACTION_TYPES)
        fallback_sum = self._build_array_sum_for_action_types(field_non_null, META_FALLBACK_ACTION_TYPES)
        specific_sum = self._build_array_sum_for_action_types(field_non_null, META_SPECIFIC_ACTION_TYPES)

        # 3-tier priority: omni > aggregated > specific
        # if omni > 0 then omni
        # else if aggregated > 0 then aggregated
        # else specific
        array_sum = ast.Call(
            name="if",
            args=[
                ast.CompareOperation(
                    left=omni_sum,
                    op=ast.CompareOperationOp.Gt,
                    right=ast.Constant(value=0),
                ),
                omni_sum,
                ast.Call(
                    name="if",
                    args=[
                        ast.CompareOperation(
                            left=fallback_sum,
                            op=ast.CompareOperationOp.Gt,
                            right=ast.Constant(value=0),
                        ),
                        fallback_sum,
                        specific_sum,
                    ],
                ),
            ],
        )

        if apply_currency:
            converted = self._apply_currency_conversion(stats_table, stats_table_name, "account_currency", array_sum)
            if converted:
                return ast.Call(name="SUM", args=[converted])

        return ast.Call(name="toFloat", args=[ast.Call(name="SUM", args=[array_sum])])

    def _get_reported_conversion_field(self) -> ast.Expr:
        return self._build_actions_conversion_sum("actions")

    def _get_reported_conversion_value_field(self) -> ast.Expr:
        return self._build_actions_conversion_sum("action_values", apply_currency=True)
