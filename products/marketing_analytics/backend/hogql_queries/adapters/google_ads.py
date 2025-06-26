# Google Ads Marketing Source Adapter

from posthog.hogql import ast
from .base import MarketingSourceAdapter, ValidationResult


class GoogleAdsAdapter(MarketingSourceAdapter):
    """
    Adapter for Google Ads native marketing data.
    Expects config with:
    - campaign_table: DataWarehouse table with campaign data
    - stats_table: DataWarehouse table with campaign stats
    """

    def get_source_type(self) -> str:
        return "GoogleAds"

    def validate(self) -> ValidationResult:
        """Validate Google Ads tables and required fields"""
        errors = []
        warnings = []

        try:
            # Check required config
            campaign_table = self.config.get("campaign_table")
            stats_table = self.config.get("stats_table")

            if not campaign_table:
                errors.append("Missing campaign_table in config")
            if not stats_table:
                errors.append("Missing stats_table in config")

            if errors:
                self._log_validation_errors(errors, warnings)
                return ValidationResult(is_valid=False, errors=errors, warnings=warnings)

            # Validate table structure (basic checks)
            campaign_table_name = getattr(campaign_table, "name", None)
            stats_table_name = getattr(stats_table, "name", None)

            if not campaign_table_name:
                errors.append("Campaign table missing name attribute")
            if not stats_table_name:
                errors.append("Stats table missing name attribute")

            # Check for expected table name patterns
            if campaign_table_name and "campaign" not in campaign_table_name.lower():
                warnings.append(f"Campaign table name '{campaign_table_name}' doesn't contain 'campaign'")
            if stats_table_name and "stats" not in stats_table_name.lower():
                warnings.append(f"Stats table name '{stats_table_name}' doesn't contain 'stats'")

            is_valid = len(errors) == 0
            self._log_validation_errors(errors, warnings)

            return ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)

        except Exception as e:
            error_msg = f"Validation error: {str(e)}"
            self.logger.exception("Google Ads validation failed", error=error_msg)
            return ValidationResult(is_valid=False, errors=[error_msg])

    def _get_campaign_name_field_ast(self) -> ast.Expr:
        campaign_table_name = self.config.get("campaign_table").name
        return ast.Call(name="toString", args=[ast.Field(chain=[campaign_table_name, "campaign_name"])])

    def _get_source_name_field_ast(self) -> ast.Expr:
        return ast.Call(name="toString", args=[ast.Constant(value="google")])

    def _get_impressions_field_ast(self) -> ast.Expr:
        stats_table_name = self.config.get("stats_table").name
        sum_ast = ast.Call(name="SUM", args=[ast.Field(chain=[stats_table_name, "metrics_impressions"])])
        return ast.Call(name="toFloat", args=[sum_ast])

    def _get_clicks_field_ast(self) -> ast.Expr:
        stats_table_name = self.config.get("stats_table").name
        sum_ast = ast.Call(name="SUM", args=[ast.Field(chain=[stats_table_name, "metrics_clicks"])])
        return ast.Call(name="toFloat", args=[sum_ast])

    def _get_cost_field_ast(self) -> ast.Expr:
        stats_table_name = self.config.get("stats_table").name
        sum_ast = ast.Call(name="SUM", args=[ast.Field(chain=[stats_table_name, "metrics_cost_micros"])])
        div_ast = ast.ArithmeticOperation(
            left=sum_ast, op=ast.ArithmeticOperationOp.Div, right=ast.Constant(value=1000000)
        )
        return ast.Call(name="toFloat", args=[div_ast])

    def _get_from_clause(self) -> str:
        campaign_table = self.config.get("campaign_table")
        from_ast = ast.Field(chain=[campaign_table.name])
        return f"FROM {from_ast.to_hogql()}"

    def _get_join_clause(self) -> str:
        stats_table = self.config.get("stats_table")
        campaign_table = self.config.get("campaign_table")

        # Build AST for: campaign_table.campaign_id = stats_table.campaign_id
        left_field = ast.Field(chain=[campaign_table.name, "campaign_id"])
        right_field = ast.Field(chain=[stats_table.name, "campaign_id"])
        join_condition = ast.CompareOperation(left=left_field, op=ast.CompareOperationOp.Eq, right=right_field)

        stats_table_ast = ast.Field(chain=[stats_table.name])
        return f"LEFT JOIN {stats_table_ast.to_hogql()} ON {join_condition.to_hogql()}"

    def _get_where_conditions(self) -> list[str]:
        """Build WHERE conditions for Google Ads query"""
        conditions = []

        # Add date range conditions
        if self.context.date_range:
            stats_table_name = self.config.get("stats_table").name

            # Build AST for date conditions
            date_field = ast.Call(name="toDateTime", args=[ast.Field(chain=[stats_table_name, "segments_date"])])

            # >= condition
            from_date_ast = ast.Call(
                name="toDateTime", args=[ast.Constant(value=self.context.date_range.date_from_str)]
            )
            gte_condition = ast.CompareOperation(left=date_field, op=ast.CompareOperationOp.GtEq, right=from_date_ast)

            # <= condition
            to_date_ast = ast.Call(name="toDateTime", args=[ast.Constant(value=self.context.date_range.date_to_str)])
            lte_condition = ast.CompareOperation(left=date_field, op=ast.CompareOperationOp.LtEq, right=to_date_ast)

            conditions.extend([gte_condition.to_hogql(), lte_condition.to_hogql()])

        # Add global filters
        if self.context.global_filters:
            conditions.extend(self.context.global_filters)

        return conditions

    def _get_group_by_clause(self) -> str:
        campaign_field_ast = self._get_campaign_name_field_ast()
        return f"GROUP BY {campaign_field_ast.to_hogql()}"
