from posthog.schema import NativeMarketingSource

from posthog.hogql import ast

from ..constants import INTEGRATION_DEFAULT_SOURCES, INTEGRATION_FIELD_NAMES, INTEGRATION_PRIMARY_SOURCE
from .base import MarketingSourceAdapter, StackAdaptAdsConfig, ValidationResult


class StackAdaptAdsAdapter(MarketingSourceAdapter[StackAdaptAdsConfig]):
    _source_type = NativeMarketingSource.STACK_ADAPT_ADS

    @classmethod
    def get_source_identifier_mapping(cls) -> dict[str, list[str]]:
        primary = INTEGRATION_PRIMARY_SOURCE[cls._source_type]
        sources = INTEGRATION_DEFAULT_SOURCES[cls._source_type]
        return {primary: list(sources)}

    def get_source_type(self) -> str:
        return "StackAdaptAds"

    def validate(self) -> ValidationResult:
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
            self.logger.exception("StackAdapt Ads validation failed", error=error_msg)
            return ValidationResult(is_valid=False, errors=[error_msg])

    def _get_campaign_name_field(self) -> ast.Expr:
        campaign_table_name = self.config.campaign_table.name
        field_name = INTEGRATION_FIELD_NAMES[self._source_type]["name_field"]
        return ast.Call(name="toString", args=[ast.Field(chain=[campaign_table_name, field_name])])

    def _get_campaign_id_field(self) -> ast.Expr:
        campaign_table_name = self.config.campaign_table.name
        field_name = INTEGRATION_FIELD_NAMES[self._source_type]["id_field"]
        return ast.Call(name="toString", args=[ast.Field(chain=[campaign_table_name, field_name])])

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
        stats_table_name = self.config.stats_table.name
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
        stats_table_name = self.config.stats_table.name
        base_currency = self.context.base_currency

        # StackAdapt cost is in standard units (not micros)
        spend_field = ast.Field(chain=[stats_table_name, "cost"])
        cost_float = ast.Call(name="toFloat", args=[spend_field])

        try:
            columns = getattr(self.config.stats_table, "columns", None)
            if columns and hasattr(columns, "__contains__") and "currency" in columns:
                currency_field = ast.Field(chain=[stats_table_name, "currency"])
                currency_with_fallback = ast.Call(
                    name="coalesce", args=[currency_field, ast.Constant(value=base_currency)]
                )
                convert_currency = ast.Call(
                    name="convertCurrency", args=[currency_with_fallback, ast.Constant(value=base_currency), cost_float]
                )
                convert_to_float = ast.Call(name="toFloat", args=[convert_currency])
                return ast.Call(name="SUM", args=[convert_to_float])
        except (TypeError, AttributeError, KeyError):
            pass

        return ast.Call(name="SUM", args=[cost_float])

    def _get_reported_conversion_field(self) -> ast.Expr:
        stats_table_name = self.config.stats_table.name
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
        stats_table_name = self.config.stats_table.name
        field_as_float = ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, "conversionRevenue"])]),
                ast.Constant(value=0),
            ],
        )
        sum = ast.Call(name="SUM", args=[field_as_float])
        return ast.Call(name="toFloat", args=[sum])

    def _get_from(self) -> ast.JoinExpr:
        campaign_table_name = self.config.campaign_table.name
        stats_table_name = self.config.stats_table.name

        campaign_table = ast.Field(chain=[campaign_table_name])
        stats_table = ast.Field(chain=[stats_table_name])

        # Join: campaigns.id = campaign_stats_daily.campaign_id
        left_field = ast.Field(chain=[campaign_table_name, "id"])
        right_field = ast.Field(chain=[stats_table_name, "campaign_id"])
        join_condition_expr = ast.CompareOperation(left=left_field, op=ast.CompareOperationOp.Eq, right=right_field)
        join_constraint = ast.JoinConstraint(expr=join_condition_expr, constraint_type="ON")

        return ast.JoinExpr(
            table=campaign_table,
            next_join=ast.JoinExpr(table=stats_table, join_type="LEFT JOIN", constraint=join_constraint),
        )

    def _get_where_conditions(self) -> list[ast.Expr]:
        conditions: list[ast.Expr] = []

        if self.context.date_range:
            stats_table_name = self.config.stats_table.name
            date_field = ast.Call(name="toDateTime", args=[ast.Field(chain=[stats_table_name, "date"])])
            from_date = ast.Call(name="toDateTime", args=[ast.Constant(value=self.context.date_range.date_from_str)])
            to_date = ast.Call(name="toDateTime", args=[ast.Constant(value=self.context.date_range.date_to_str)])
            conditions.append(ast.CompareOperation(left=date_field, op=ast.CompareOperationOp.GtEq, right=from_date))
            conditions.append(ast.CompareOperation(left=date_field, op=ast.CompareOperationOp.LtEq, right=to_date))

        return conditions

    def _get_group_by(self) -> list[ast.Expr]:
        return [self._get_campaign_name_field(), self._get_campaign_id_field()]
