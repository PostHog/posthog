# Google Ads Marketing Source Adapter

from posthog.schema import MarketingAnalyticsDrillDownLevel, NativeMarketingSource

from posthog.hogql import ast

from ..constants import INTEGRATION_DEFAULT_SOURCES, INTEGRATION_PRIMARY_SOURCE
from .base import GoogleAdsConfig, MarketingSourceAdapter, ValidationResult


class GoogleAdsAdapter(MarketingSourceAdapter[GoogleAdsConfig]):
    """
    Adapter for Google Ads native marketing data.
    Expects config with:
    - campaign_table + stats_table: always required
    - ad_group_table + ad_group_stats_table: optional; needed for AD_GROUP drill-down
    - ad_table + ad_stats_table: optional; needed for AD drill-down

    Google Ads flattens the API's dotted field names with underscores: `campaign.id`
    becomes `campaign_id`, `ad_group_ad.ad.id` becomes `ad_group_ad_ad_id`, etc.
    """

    _source_type = NativeMarketingSource.GOOGLE_ADS

    # Google Ads' dotted source field names are flattened with underscores at import.
    _stats_date_column = "segments_date"
    _campaign_pk_column = "campaign_id"
    _campaign_name_column = "campaign_name"
    _campaign_stats_fk_column = "campaign_id"
    _adset_pk_column = "ad_group_id"
    _adset_name_column = "ad_group_name"
    _adset_campaign_fk_column = "campaign_id"
    _adset_stats_fk_column = "ad_group_id"
    _ad_pk_column = "ad_group_ad_ad_id"
    _ad_name_column = "ad_group_ad_ad_name"
    _ad_adset_fk_column = "ad_group_id"
    _ad_campaign_fk_column = "campaign_id"
    _ad_stats_fk_column = "ad_group_ad_ad_id"

    @classmethod
    def get_source_identifier_mapping(cls) -> dict[str, list[str]]:
        primary = INTEGRATION_PRIMARY_SOURCE[cls._source_type]
        sources = INTEGRATION_DEFAULT_SOURCES[cls._source_type]
        return {primary: list(sources)}

    def get_source_type(self) -> str:
        return "GoogleAds"

    def validate(self) -> ValidationResult:
        """Validate Google Ads tables and required fields"""
        errors: list[str] = []

        try:
            if self.config.campaign_table.name and "campaign" not in self.config.campaign_table.name.lower():
                errors.append(f"Campaign table name '{self.config.campaign_table.name}' doesn't contain 'campaign'")
            if self.config.stats_table.name and "stats" not in self.config.stats_table.name.lower():
                errors.append(f"Stats table name '{self.config.stats_table.name}' doesn't contain 'stats'")

            is_valid = len(errors) == 0
            self._log_validation_errors(errors)

            return ValidationResult(is_valid=is_valid, errors=errors)

        except Exception as e:
            error_msg = f"Validation error: {str(e)}"
            self.logger.exception("Google Ads validation failed", error=error_msg)
            return ValidationResult(is_valid=False, errors=[error_msg])

    def _get_impressions_field(self) -> ast.Expr:
        stats_table_name = self._level_tables().stats_table.name
        field_as_float = ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, "metrics_impressions"])]),
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
                ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, "metrics_clicks"])]),
                ast.Constant(value=0),
            ],
        )
        sum = ast.Call(name="SUM", args=[field_as_float])
        return ast.Call(name="toFloat", args=[sum])

    def _get_reported_conversion_field(self) -> ast.Expr:
        stats_table_name = self._level_tables().stats_table.name
        field_as_float = ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, "metrics_conversions"])]),
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
                ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, "metrics_conversions_value"])]),
                ast.Constant(value=0),
            ],
        )

        converted = self._apply_currency_conversion(
            stats_table, stats_table_name, "customer_currency_code", field_as_float
        )
        if converted:
            return ast.Call(name="SUM", args=[converted])

        sum = ast.Call(name="SUM", args=[field_as_float])
        return ast.Call(name="toFloat", args=[sum])

    def _get_cost_field(self) -> ast.Expr:
        stats_table = self._level_tables().stats_table
        stats_table_name = stats_table.name

        # Google reports cost in micros (millionths of the account currency).
        cost_micros = ast.Field(chain=[stats_table_name, "metrics_cost_micros"])
        cost_standard = ast.ArithmeticOperation(
            left=cost_micros, op=ast.ArithmeticOperationOp.Div, right=ast.Constant(value=1000000)
        )
        cost_float = ast.Call(name="toFloat", args=[cost_standard])

        converted = self._apply_currency_conversion(stats_table, stats_table_name, "customer_currency_code", cost_float)
        if converted:
            return ast.Call(name="SUM", args=[converted])

        sum_cost = ast.Call(name="SUM", args=[cost_float])
        return ast.Call(name="toFloat", args=[sum_cost])

    # Plain-string columns that may hold a human-readable ad label, in priority
    # order. Google only sets `ad.name` for a few legacy display ad types — for
    # search / responsive / image ads it is always empty — so we fall back to
    # the type-specific headline columns. Responsive search ads keep their
    # headlines in a separate JSON column, handled after this loop.
    # `_ad_name_column` leads the chain so the two stay in sync if it changes.
    _AD_NAME_FALLBACK_COLUMNS = (
        _ad_name_column,
        "ad_group_ad_ad_expanded_text_ad_headline_part1",
        "ad_group_ad_ad_text_ad_headline",
        "ad_group_ad_ad_image_ad_name",
    )

    # Responsive search ad headlines: a String column holding double-encoded
    # JSON — an array of strings, each string itself a JSON object
    # `{"text": "...", ...}`. The first headline's `text` is the ad's label.
    _RSA_HEADLINES_COLUMN = "ad_group_ad_ad_responsive_search_ad_headlines"

    def _get_ad_name_field(self) -> ast.Expr:
        """Ad label for Google. `ad_group_ad.ad.name` is empty for the vast
        majority of ads (Google only populates it for some legacy display
        types), so coalesce across the type-specific headline columns and fall
        back to the ad ID so the column is never blank."""
        # Only AD drill-down reads ad-level columns, and `ad_table` is set only
        # on hierarchical native configs — NULL elsewhere mirrors the base
        # adapter's contract for hierarchy fields.
        if self.config.ad_table is None or self.context.drill_down_level != MarketingAnalyticsDrillDownLevel.AD:
            return ast.Constant(value=None)

        table = self.config.ad_table
        candidates: list[ast.Expr] = []
        for column in self._AD_NAME_FALLBACK_COLUMNS:
            if self._table_has_column(table, column):
                candidates.append(
                    ast.Call(
                        name="nullif",
                        args=[
                            ast.Call(name="toString", args=[ast.Field(chain=[table.name, column])]),
                            ast.Constant(value=""),
                        ],
                    )
                )

        # Responsive search ads: the headlines column is double-encoded JSON
        # (a string → array of strings → each string a JSON object). The inner
        # JSONExtractString(col, 1) takes the first array element (`1` is a
        # 1-based index); the outer one reads its `text` key. Verified against
        # ClickHouse. Returns a scalar String, so no Array involved.
        if self._table_has_column(table, self._RSA_HEADLINES_COLUMN):
            candidates.append(
                ast.Call(
                    name="nullif",
                    args=[
                        ast.Call(
                            name="JSONExtractString",
                            args=[
                                ast.Call(
                                    name="JSONExtractString",
                                    args=[
                                        ast.Field(chain=[table.name, self._RSA_HEADLINES_COLUMN]),
                                        ast.Constant(value=1),
                                    ],
                                ),
                                ast.Constant(value="text"),
                            ],
                        ),
                        ast.Constant(value=""),
                    ],
                )
            )

        # Always-available last resort so the Ad column is never empty.
        candidates.append(ast.Call(name="toString", args=[ast.Field(chain=[table.name, self._ad_pk_column])]))

        if len(candidates) == 1:
            return candidates[0]
        return ast.Call(name="coalesce", args=candidates)
