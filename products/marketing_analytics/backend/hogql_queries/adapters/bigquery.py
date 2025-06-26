# BigQuery Marketing Source Adapter

from typing import Optional
from posthog.hogql import ast
from .base import MarketingSourceAdapter, ValidationResult
from products.marketing_analytics.backend.hogql_queries.constants import (
    MARKETING_ANALYTICS_SCHEMA,
    SOURCE_MAP_CAMPAIGN_NAME,
    SOURCE_MAP_CLICKS,
    SOURCE_MAP_CURRENCY,
    SOURCE_MAP_DATE,
    SOURCE_MAP_IMPRESSIONS,
    SOURCE_MAP_SOURCE_NAME,
    SOURCE_MAP_TOTAL_COST,
    SOURCE_MAP_UTM_CAMPAIGN_NAME,
    SOURCE_MAP_UTM_SOURCE_NAME,
)
from products.marketing_analytics.backend.hogql_queries.utils import get_source_map_field


class BigQueryAdapter(MarketingSourceAdapter):
    """
    Adapter for BigQuery external marketing data.
    BigQuery is a "non-native" managed external source - it connects to Google BigQuery
    tables that users configure with field mappings for marketing analytics.

    Expects config with:
    - table: DataWarehouse table object (BigQuery table)
    - source_map: Field mapping configuration
    - source_type: Should be 'BigQuery'
    """

    def get_source_type(self) -> str:
        return "BigQuery"

    def validate(self) -> ValidationResult:
        """Validate BigQuery table and required field mappings"""
        errors = []
        warnings = []

        try:
            if not self.config:
                errors.append("Missing config in BigQuery adapter")

            if not self.config.get("source_map"):
                errors.append("Missing source_map in config")

            if not self.config.get("source_type"):
                errors.append("Missing source_type in config")

            if not self.config.get("table"):
                errors.append("Missing table in config")

            if not self.config.get("table").name:
                errors.append("Missing table name in config")

            if not self.config.get("schema_name"):
                errors.append("Missing schema_name in config")

            if errors:
                self._log_validation_errors(errors, warnings)
                return ValidationResult(is_valid=False, errors=errors, warnings=warnings)

            # BigQuery-specific validation
            bigquery_errors, bigquery_warnings = self._validate_bigquery_specific()
            errors.extend(bigquery_errors)
            warnings.extend(bigquery_warnings)

            # Validate required schema fields
            missing_required_fields = []
            for field_name, field_config in MARKETING_ANALYTICS_SCHEMA.items():
                if field_config["required"]:
                    field_value = get_source_map_field(self.config.get("source_map"), field_name)
                    if not field_value or (isinstance(field_value, str) and field_value.strip() == ""):
                        missing_required_fields.append(field_name)

            if missing_required_fields:
                errors.extend([f"Missing required field: {field}" for field in missing_required_fields])

            # Must have either campaign_name or utm_campaign_name
            campaign_field = get_source_map_field(
                self.config.get("source_map"), SOURCE_MAP_UTM_CAMPAIGN_NAME
            ) or get_source_map_field(self.config.get("source_map"), SOURCE_MAP_CAMPAIGN_NAME)
            if not campaign_field:
                errors.append("Missing campaign name field (utm_campaign_name or campaign_name)")

            # Check for date field
            date_field = get_source_map_field(self.config.get("source_map"), SOURCE_MAP_DATE)
            if not date_field:
                errors.append("Missing date field in source_map")

            is_valid = len(errors) == 0
            self._log_validation_errors(errors, warnings)

            return ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)

        except Exception as e:
            error_msg = f"Validation error: {str(e)}"
            self.logger.exception("BigQuery table validation failed", error=error_msg)
            return ValidationResult(is_valid=False, errors=[error_msg])

    def _validate_bigquery_specific(self) -> tuple[list[str], list[str]]:
        """BigQuery-specific validation checks"""
        errors = []
        warnings = []

        # Check for BigQuery-specific data types in field mappings
        # BigQuery typically uses different column naming conventions
        date_field = get_source_map_field(self.config.get("source_map"), SOURCE_MAP_DATE)
        if date_field and "timestamp" in date_field.lower():
            warnings.append("BigQuery timestamp fields may need special date conversion")

        # Check for potential BigQuery cost fields (often in different formats)
        cost_field = get_source_map_field(self.config.get("source_map"), SOURCE_MAP_TOTAL_COST)
        if cost_field and any(keyword in cost_field.lower() for keyword in ["spend", "cost_micros"]):
            warnings.append("BigQuery cost field may need unit conversion (micros to standard currency)")

        return errors, warnings

    def _get_campaign_name_field_ast(self) -> ast.Expr:
        campaign_name_field = get_source_map_field(
            self.config.get("source_map"), SOURCE_MAP_UTM_CAMPAIGN_NAME
        ) or get_source_map_field(self.config.get("source_map"), SOURCE_MAP_CAMPAIGN_NAME)
        
        return ast.Call(name="toString", args=[ast.Field(chain=[campaign_name_field])])

    def _get_source_name_field_ast(self) -> ast.Expr:
        source_name_field = (
            get_source_map_field(self.config.get("source_map"), SOURCE_MAP_UTM_SOURCE_NAME)
            or get_source_map_field(self.config.get("source_map"), SOURCE_MAP_SOURCE_NAME)
            or f"'{self.config.get('schema_name')}'"
        )
        
        if source_name_field.startswith("'") and source_name_field.endswith("'"):
            # It's a literal string
            inner_expr = ast.Constant(value=source_name_field[1:-1])
        else:
            # It's a field reference
            inner_expr = ast.Field(chain=[source_name_field])
            
        return ast.Call(name="toString", args=[inner_expr])

    def _get_impressions_field_ast(self) -> ast.Expr:
        impressions_field = get_source_map_field(self.config.get("source_map"), SOURCE_MAP_IMPRESSIONS, "0")
        
        if impressions_field == "0":
            inner_expr = ast.Constant(value=0)
        else:
            inner_expr = ast.Field(chain=[impressions_field])
            
        coalesce_ast = ast.Call(name="coalesce", args=[inner_expr, ast.Constant(value=0)])
        return ast.Call(name="toFloat", args=[coalesce_ast])

    def _get_clicks_field_ast(self) -> ast.Expr:
        clicks_field = get_source_map_field(self.config.get("source_map"), SOURCE_MAP_CLICKS, "0")
        
        if clicks_field == "0":
            inner_expr = ast.Constant(value=0)
        else:
            inner_expr = ast.Field(chain=[clicks_field])
            
        coalesce_ast = ast.Call(name="coalesce", args=[inner_expr, ast.Constant(value=0)])
        return ast.Call(name="toFloat", args=[coalesce_ast])

    def _get_cost_field_ast(self) -> ast.Expr:
        # Handle currency conversion
        total_cost_field = get_source_map_field(self.config.get("source_map"), SOURCE_MAP_TOTAL_COST)
        currency_field = get_source_map_field(self.config.get("source_map"), SOURCE_MAP_CURRENCY)
        base_currency = self.context.base_currency

        if currency_field and total_cost_field:
            # toFloat(convertCurrency('currency_field', 'base_currency', toFloat(coalesce(total_cost_field, 0))))
            coalesce_ast = ast.Call(name="coalesce", args=[ast.Field(chain=[total_cost_field]), ast.Constant(value=0)])
            inner_toFloat_ast = ast.Call(name="toFloat", args=[coalesce_ast])
            convert_currency_ast = ast.Call(
                name="convertCurrency",
                args=[ast.Constant(value=currency_field), ast.Constant(value=base_currency), inner_toFloat_ast],
            )
            return ast.Call(name="toFloat", args=[convert_currency_ast])
        elif total_cost_field:
            # toFloat(coalesce(total_cost_field, 0))
            coalesce_ast = ast.Call(name="coalesce", args=[ast.Field(chain=[total_cost_field]), ast.Constant(value=0)])
            return ast.Call(name="toFloat", args=[coalesce_ast])
        else:
            # 0
            return ast.Constant(value=0)

    def _get_from_ast(self) -> ast.JoinExpr:
        """Build FROM clause as AST JoinExpr"""
        table_name = self.config.get("table").name
        table_ast = ast.Field(chain=[table_name])
        return ast.JoinExpr(table=table_ast)

    def _get_where_conditions_ast(self) -> list[ast.Expr]:
        """Build WHERE conditions as AST expressions optimized for BigQuery"""
        date_field = get_source_map_field(self.config.get("source_map"), SOURCE_MAP_DATE)
        conditions = []

        # Add date range conditions
        if self.context.date_range:
            if date_field != "timestamp":
                # toDateTime(date_field) >= toDateTime('date_from')
                date_cast_ast = ast.Call(name="toDateTime", args=[ast.Field(chain=[date_field])])
            else:
                date_cast_ast = ast.Field(chain=[date_field])
                
            # Build >= condition
            from_date_ast = ast.Call(
                name="toDateTime", args=[ast.Constant(value=self.context.date_range.date_from_str)]
            )
            gte_condition = ast.CompareOperation(
                left=date_cast_ast, op=ast.CompareOperationOp.GtEq, right=from_date_ast
            )
            
            # Build <= condition
            to_date_ast = ast.Call(name="toDateTime", args=[ast.Constant(value=self.context.date_range.date_to_str)])
            lte_condition = ast.CompareOperation(left=date_cast_ast, op=ast.CompareOperationOp.LtEq, right=to_date_ast)
            
            conditions.extend([gte_condition, lte_condition])

        return conditions

    def _get_group_by_ast(self) -> list[ast.Expr]:
        """Build GROUP BY expressions as AST"""
        # BigQuery tables typically don't need grouping
        return []
