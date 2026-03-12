# Pinterest Ads Marketing Source Adapter

from posthog.schema import NativeMarketingSource

from posthog.hogql import ast

from ..constants import INTEGRATION_DEFAULT_SOURCES, INTEGRATION_FIELD_NAMES, INTEGRATION_PRIMARY_SOURCE
from .base import MarketingSourceAdapter, PinterestAdsConfig, ValidationResult


class PinterestAdsAdapter(MarketingSourceAdapter[PinterestAdsConfig]):
    """
    Adapter for Pinterest Ads native marketing data.
    Expects config with:
    - campaign_table: DataWarehouse table with campaign data
    - stats_table: DataWarehouse table with campaign stats (campaign_analytics)
    """

    _source_type = NativeMarketingSource.PINTEREST_ADS

    @classmethod
    def get_source_identifier_mapping(cls) -> dict[str, list[str]]:
        """Pinterest Ads campaigns typically use 'pinterest' as the UTM source"""
        primary = INTEGRATION_PRIMARY_SOURCE[cls._source_type]
        sources = INTEGRATION_DEFAULT_SOURCES[cls._source_type]
        return {primary: list(sources)}

    def get_source_type(self) -> str:
        """Return unique identifier for this source type"""
        return "PinterestAds"

    def validate(self) -> ValidationResult:
        """Validate Pinterest Ads tables and required fields"""
        errors: list[str] = []

        try:
            if self.config.campaign_table.name and "campaigns" not in self.config.campaign_table.name.lower():
                errors.append(f"Campaign table name '{self.config.campaign_table.name}' doesn't contain 'campaigns'")
            if self.config.stats_table.name and "campaign_analytics" not in self.config.stats_table.name.lower():
                errors.append(f"Stats table name '{self.config.stats_table.name}' doesn't contain 'campaign_analytics'")

            if not self._has_stats_column("currency"):
                self.logger.warning(
                    "Pinterest Ads stats table missing currency column, monetary values may be inaccurate",
                    stats_table=self.config.stats_table.name,
                )

            is_valid = len(errors) == 0
            self._log_validation_errors(errors)

            return ValidationResult(is_valid=is_valid, errors=errors)

        except Exception as e:
            error_msg = f"Validation error: {str(e)}"
            self.logger.exception("Pinterest Ads validation failed", error=error_msg)
            return ValidationResult(is_valid=False, errors=[error_msg])

    def _get_campaign_name_field(self) -> ast.Expr:
        campaign_table_name = self.config.campaign_table.name
        field_name = INTEGRATION_FIELD_NAMES[self._source_type]["name_field"]
        return ast.Call(name="toString", args=[ast.Field(chain=[campaign_table_name, field_name])])

    def _get_campaign_id_field(self) -> ast.Expr:
        campaign_table_name = self.config.campaign_table.name
        field_name = INTEGRATION_FIELD_NAMES[self._source_type]["id_field"]
        field_expr = ast.Field(chain=[campaign_table_name, field_name])
        return ast.Call(name="toString", args=[field_expr])

    def _get_impressions_field(self) -> ast.Expr:
        stats_table_name = self.config.stats_table.name
        field_as_float = ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, "total_impression"])]),
                ast.Constant(value=0),
            ],
        )
        sum = ast.Call(name="SUM", args=[field_as_float])
        return ast.Call(name="toFloat", args=[sum])

    def _get_clicks_field(self) -> ast.Expr:
        stats_table_name = self.config.stats_table.name
        field_as_float = ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, "total_clickthrough"])]),
                ast.Constant(value=0),
            ],
        )
        sum = ast.Call(name="SUM", args=[field_as_float])
        return ast.Call(name="toFloat", args=[sum])

    def _get_cost_field(self) -> ast.Expr:
        stats_table_name = self.config.stats_table.name

        # Pinterest spend_in_dollar is already in standard dollar units (no micro conversion needed)
        spend_field = ast.Field(chain=[stats_table_name, "spend_in_dollar"])
        cost_float = ast.Call(name="toFloat", args=[spend_field])

        converted = self._apply_currency_conversion(self.config.stats_table, stats_table_name, "currency", cost_float)
        if converted:
            return ast.Call(name="SUM", args=[converted])

        return ast.Call(name="SUM", args=[cost_float])

    def _has_stats_column(self, column_name: str) -> bool:
        columns = getattr(self.config.stats_table, "columns", None)
        if not columns or not hasattr(columns, "__contains__") or column_name not in columns:
            return False
        # Column metadata can be a dict with valid: false for non-queryable columns
        col_meta = columns[column_name]
        if isinstance(col_meta, dict) and not col_meta.get("valid", True):
            return False
        return True

    def _get_reported_conversion_field(self) -> ast.Expr:
        """Get conversion count (total_conversions) — optional, not all accounts have conversion tracking"""
        if not self._has_stats_column("total_conversions"):
            return ast.Call(name="toFloat", args=[ast.Constant(value=0)])

        stats_table_name = self.config.stats_table.name
        field_as_float = ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, "total_conversions"])]),
                ast.Constant(value=0),
            ],
        )
        sum = ast.Call(name="SUM", args=[field_as_float])
        return ast.Call(name="toFloat", args=[sum])

    def _get_reported_conversion_value_field(self) -> ast.Expr:
        """Get conversion value (total_checkout_value_in_micro_dollar) — optional, not all accounts have conversion tracking"""
        if not self._has_stats_column("total_checkout_value_in_micro_dollar"):
            return ast.Call(name="toFloat", args=[ast.Constant(value=0)])

        stats_table_name = self.config.stats_table.name

        # total_checkout_value_in_micro_dollar is in micro dollars, divide by 1,000,000
        checkout_value_field = ast.Call(
            name="ifNull",
            args=[
                ast.ArithmeticOperation(
                    left=ast.Call(
                        name="toFloat",
                        args=[ast.Field(chain=[stats_table_name, "total_checkout_value_in_micro_dollar"])],
                    ),
                    op=ast.ArithmeticOperationOp.Div,
                    right=ast.Constant(value=1000000),
                ),
                ast.Constant(value=0),
            ],
        )

        converted = self._apply_currency_conversion(
            self.config.stats_table, stats_table_name, "currency", checkout_value_field
        )
        if converted:
            return ast.Call(name="SUM", args=[converted])

        sum = ast.Call(name="SUM", args=[checkout_value_field])
        return ast.Call(name="toFloat", args=[sum])

    def _get_from(self) -> ast.JoinExpr:
        """Build FROM and JOIN clauses"""
        campaign_table_name = self.config.campaign_table.name
        stats_table_name = self.config.stats_table.name

        campaign_table = ast.Field(chain=[campaign_table_name])
        stats_table = ast.Field(chain=[stats_table_name])

        # Build join condition: campaigns.id = campaign_analytics.campaign_id
        left_field = ast.Field(chain=[campaign_table_name, "id"])
        right_field = ast.Field(chain=[stats_table_name, "campaign_id"])
        join_condition_expr = ast.CompareOperation(left=left_field, op=ast.CompareOperationOp.Eq, right=right_field)

        join_constraint = ast.JoinConstraint(expr=join_condition_expr, constraint_type="ON")

        join_expr = ast.JoinExpr(
            table=campaign_table,
            next_join=ast.JoinExpr(table=stats_table, join_type="LEFT JOIN", constraint=join_constraint),
        )

        return join_expr

    def _get_where_conditions(self) -> list[ast.Expr]:
        """Build WHERE conditions"""
        conditions: list[ast.Expr] = []

        if self.context.date_range:
            stats_table_name = self.config.stats_table.name

            date_field = ast.Call(name="toDateTime", args=[ast.Field(chain=[stats_table_name, "date"])])

            from_date = ast.Call(name="toDateTime", args=[ast.Constant(value=self.context.date_range.date_from_str)])
            gte_condition = ast.CompareOperation(left=date_field, op=ast.CompareOperationOp.GtEq, right=from_date)

            to_date = ast.Call(name="toDateTime", args=[ast.Constant(value=self.context.date_range.date_to_str)])
            lte_condition = ast.CompareOperation(left=date_field, op=ast.CompareOperationOp.LtEq, right=to_date)

            conditions.extend([gte_condition, lte_condition])

        return conditions

    def _get_group_by(self) -> list[ast.Expr]:
        """Build GROUP BY expressions - group by both name and ID"""
        return [self._get_campaign_name_field(), self._get_campaign_id_field()]
