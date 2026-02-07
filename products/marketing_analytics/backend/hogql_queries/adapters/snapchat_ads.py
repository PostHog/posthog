# Snapchat Ads Marketing Source Adapter

from posthog.schema import NativeMarketingSource

from posthog.hogql import ast

from ..constants import (
    INTEGRATION_DEFAULT_SOURCES,
    INTEGRATION_FIELD_NAMES,
    INTEGRATION_PRIMARY_SOURCE,
    SNAPCHAT_CONVERSION_FIELDS,
    SNAPCHAT_CONVERSION_VALUE_FIELDS,
)
from .base import MarketingSourceAdapter, SnapchatAdsConfig, ValidationResult


class SnapchatAdsAdapter(MarketingSourceAdapter[SnapchatAdsConfig]):
    """
    Adapter for Snapchat Ads native marketing data.
    Expects config with:
    - campaign_table: DataWarehouse table with campaign data
    - stats_table: DataWarehouse table with campaign stats
    """

    _source_type = NativeMarketingSource.SNAPCHAT_ADS

    @classmethod
    def get_source_identifier_mapping(cls) -> dict[str, list[str]]:
        """Snapchat Ads campaigns typically use 'snapchat' as the UTM source"""
        primary = INTEGRATION_PRIMARY_SOURCE[cls._source_type]
        sources = INTEGRATION_DEFAULT_SOURCES[cls._source_type]
        return {primary: list(sources)}

    def get_source_type(self) -> str:
        return "SnapchatAds"

    def validate(self) -> ValidationResult:
        """Validate Snapchat Ads tables and required fields"""
        errors: list[str] = []

        try:
            # Check for expected table name patterns
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

    def _get_campaign_name_field(self) -> ast.Expr:
        campaign_table_name = self.config.campaign_table.name
        field_name = INTEGRATION_FIELD_NAMES[self._source_type]["name_field"]
        return ast.Call(name="toString", args=[ast.Field(chain=[campaign_table_name, field_name])])

    def _get_campaign_id_field(self) -> ast.Expr:
        campaign_table_name = self.config.campaign_table.name
        field_name = INTEGRATION_FIELD_NAMES[self._source_type]["id_field"]
        field_expr = ast.Field(chain=[campaign_table_name, field_name])
        return ast.Call(name="toString", args=[field_expr])

    def _get_source_name_field(self) -> ast.Expr:
        return ast.Call(name="toString", args=[ast.Constant(value="snapchat")])

    def _get_impressions_field(self) -> ast.Expr:
        stats_table_name = self.config.stats_table.name
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
        stats_table_name = self.config.stats_table.name
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
        stats_table_name = self.config.stats_table.name
        base_currency = self.context.base_currency

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

        # Check if currency column exists in stats table
        try:
            columns = getattr(self.config.stats_table, "columns", None)
            if columns and hasattr(columns, "__contains__") and "currency" in columns:
                currency_field = ast.Field(chain=[stats_table_name, "currency"])
                currency_with_fallback = ast.Call(
                    name="coalesce", args=[currency_field, ast.Constant(value=base_currency)]
                )
                convert_currency = ast.Call(
                    name="convertCurrency",
                    args=[currency_with_fallback, ast.Constant(value=base_currency), spend_float],
                )
                convert_to_float = ast.Call(name="toFloat", args=[convert_currency])
                return ast.Call(name="SUM", args=[convert_to_float])
        except (TypeError, AttributeError, KeyError):
            pass

        # Currency column doesn't exist, return cost without conversion
        return ast.Call(name="SUM", args=[spend_float])

    def _get_reported_conversion_field(self) -> ast.Expr:
        stats_table_name = self.config.stats_table.name

        # Sum all available conversion fields that exist in the table
        # Similar to Meta's approach of summing multiple action types
        conversion_exprs: list[ast.Expr] = []

        try:
            columns = getattr(self.config.stats_table, "columns", None)
            if columns and hasattr(columns, "__contains__"):
                for field_name in SNAPCHAT_CONVERSION_FIELDS:
                    if field_name in columns:
                        field_as_float = ast.Call(
                            name="ifNull",
                            args=[
                                ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, field_name])]),
                                ast.Constant(value=0),
                            ],
                        )
                        conversion_exprs.append(field_as_float)
        except (TypeError, AttributeError, KeyError):
            pass

        # If no conversion columns found, fallback to conversion_purchases
        if not conversion_exprs:
            field_as_float = ast.Call(
                name="ifNull",
                args=[
                    ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, "conversion_purchases"])]),
                    ast.Constant(value=0),
                ],
            )
            conversion_exprs.append(field_as_float)

        # Sum all conversion fields
        if len(conversion_exprs) == 1:
            total_conversions = conversion_exprs[0]
        else:
            total_conversions = ast.Call(name="plus", args=[conversion_exprs[0], conversion_exprs[1]])
            for expr in conversion_exprs[2:]:
                total_conversions = ast.Call(name="plus", args=[total_conversions, expr])

        sum_result = ast.Call(name="SUM", args=[total_conversions])
        return ast.Call(name="toFloat", args=[sum_result])

    def _get_reported_conversion_value_field(self) -> ast.Expr:
        stats_table_name = self.config.stats_table.name

        # Sum all available conversion value fields that exist in the table
        # Similar to Meta's approach of summing multiple action value types
        conversion_value_exprs: list[ast.Expr] = []

        try:
            columns = getattr(self.config.stats_table, "columns", None)
            if columns and hasattr(columns, "__contains__"):
                for field_name in SNAPCHAT_CONVERSION_VALUE_FIELDS:
                    if field_name in columns:
                        field_as_float = ast.Call(
                            name="ifNull",
                            args=[
                                ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, field_name])]),
                                ast.Constant(value=0),
                            ],
                        )
                        conversion_value_exprs.append(field_as_float)
        except (TypeError, AttributeError, KeyError):
            pass

        # If no conversion value columns found, return 0
        if not conversion_value_exprs:
            return ast.Constant(value=0)

        # Sum all conversion value fields
        if len(conversion_value_exprs) == 1:
            total_value = conversion_value_exprs[0]
        else:
            total_value = ast.Call(name="plus", args=[conversion_value_exprs[0], conversion_value_exprs[1]])
            for expr in conversion_value_exprs[2:]:
                total_value = ast.Call(name="plus", args=[total_value, expr])

        sum_result = ast.Call(name="SUM", args=[total_value])
        return ast.Call(name="toFloat", args=[sum_result])

    def _get_from(self) -> ast.JoinExpr:
        """Build FROM and JOIN clauses"""
        campaign_table_name = self.config.campaign_table.name
        stats_table_name = self.config.stats_table.name

        # Create base table
        campaign_table = ast.Field(chain=[campaign_table_name])

        # Create joined table with join condition
        stats_table = ast.Field(chain=[stats_table_name])

        # Build join condition: campaign_table.id = stats_table.id
        left_field = ast.Field(chain=[campaign_table_name, "id"])
        right_field = ast.Field(chain=[stats_table_name, "id"])
        join_condition_expr = ast.CompareOperation(left=left_field, op=ast.CompareOperationOp.Eq, right=right_field)

        # Create JoinConstraint
        join_constraint = ast.JoinConstraint(expr=join_condition_expr, constraint_type="ON")

        # Create LEFT JOIN
        join_expr = ast.JoinExpr(
            table=campaign_table,
            next_join=ast.JoinExpr(table=stats_table, join_type="LEFT JOIN", constraint=join_constraint),
        )

        return join_expr

    def _get_where_conditions(self) -> list[ast.Expr]:
        """Build WHERE conditions"""
        conditions: list[ast.Expr] = []

        # Add date range conditions
        if self.context.date_range:
            stats_table_name = self.config.stats_table.name

            # Build for date field - Snapchat uses start_time
            date_field = ast.Call(name="toDateTime", args=[ast.Field(chain=[stats_table_name, "start_time"])])

            # >= condition
            from_date = ast.Call(name="toDateTime", args=[ast.Constant(value=self.context.date_range.date_from_str)])
            gte_condition = ast.CompareOperation(left=date_field, op=ast.CompareOperationOp.GtEq, right=from_date)

            # <= condition
            to_date = ast.Call(name="toDateTime", args=[ast.Constant(value=self.context.date_range.date_to_str)])
            lte_condition = ast.CompareOperation(left=date_field, op=ast.CompareOperationOp.LtEq, right=to_date)

            conditions.extend([gte_condition, lte_condition])

        return conditions

    def _get_group_by(self) -> list[ast.Expr]:
        """Build GROUP BY expressions - group by both name and ID"""
        return [self._get_campaign_name_field(), self._get_campaign_id_field()]
