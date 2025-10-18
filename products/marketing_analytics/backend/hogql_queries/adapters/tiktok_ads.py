# TikTok Ads Marketing Source Adapter

from posthog.hogql import ast

from .base import MarketingSourceAdapter, TikTokAdsConfig, ValidationResult


class TikTokAdsAdapter(MarketingSourceAdapter[TikTokAdsConfig]):
    """
    Adapter for TikTok Ads native marketing data.
    Expects config with:
    - campaign_table: DataWarehouse table with campaign data
    - stats_table: DataWarehouse table with campaign stats
    """

    @classmethod
    def get_source_identifier_mapping(cls) -> dict[str, list[str]]:
        """TikTok Ads campaigns typically use 'tiktok' as the UTM source"""
        return {"tiktok": ["tiktok"]}

    def get_source_type(self) -> str:
        return "TikTokAds"

    def validate(self) -> ValidationResult:
        """Validate TikTok Ads tables and required fields"""
        errors: list[str] = []

        try:
            # Check for expected table name patterns
            if self.config.campaign_table.name and "campaigns" not in self.config.campaign_table.name.lower():
                errors.append(f"Campaign table name '{self.config.campaign_table.name}' doesn't contain 'campaigns'")
            if self.config.stats_table.name and "campaign_report" not in self.config.stats_table.name.lower():
                errors.append(f"Stats table name '{self.config.stats_table.name}' doesn't contain 'campaign_report'")

            is_valid = len(errors) == 0
            self._log_validation_errors(errors)

            return ValidationResult(is_valid=is_valid, errors=errors)

        except Exception as e:
            error_msg = f"Validation error: {str(e)}"
            self.logger.exception("TikTok Ads validation failed", error=error_msg)
            return ValidationResult(is_valid=False, errors=[error_msg])

    def _get_campaign_name_field(self) -> ast.Expr:
        campaign_table_name = self.config.campaign_table.name
        return ast.Call(name="toString", args=[ast.Field(chain=[campaign_table_name, "campaign_name"])])

    def _get_source_name_field(self) -> ast.Expr:
        return ast.Call(name="toString", args=[ast.Constant(value="tiktok")])

    def _get_impressions_field(self) -> ast.Expr:
        stats_table_name = self.config.stats_table.name
        sum = ast.Call(
            name="SUM", args=[ast.Call(name="toFloatOrZero", args=[ast.Field(chain=[stats_table_name, "impressions"])])]
        )
        return ast.Call(name="toFloat", args=[sum])

    def _get_clicks_field(self) -> ast.Expr:
        stats_table_name = self.config.stats_table.name
        sum = ast.Call(
            name="SUM", args=[ast.Call(name="toFloatOrZero", args=[ast.Field(chain=[stats_table_name, "clicks"])])]
        )
        return ast.Call(name="toFloat", args=[sum])

    def _get_cost_field(self) -> ast.Expr:
        stats_table_name = self.config.stats_table.name
        sum = ast.Call(
            name="SUM", args=[ast.Call(name="toFloatOrZero", args=[ast.Field(chain=[stats_table_name, "spend"])])]
        )
        return ast.Call(name="toFloat", args=[sum])

    def _get_reported_conversion_field(self) -> ast.Expr:
        stats_table_name = self.config.stats_table.name
        sum = ast.Call(
            name="SUM", args=[ast.Call(name="toFloatOrZero", args=[ast.Field(chain=[stats_table_name, "conversion"])])]
        )
        return ast.Call(name="toFloat", args=[sum])

    def _get_from(self) -> ast.JoinExpr:
        """Build FROM and JOIN clauses"""
        campaign_table_name = self.config.campaign_table.name
        stats_table_name = self.config.stats_table.name

        # Create base table
        campaign_table = ast.Field(chain=[campaign_table_name])

        # Create joined table with join condition
        stats_table = ast.Field(chain=[stats_table_name])

        # Build join condition: campaign_table.campaign_id = stats_table.campaign_id
        left_field = ast.Field(chain=[campaign_table_name, "campaign_id"])
        right_field = ast.Field(chain=[stats_table_name, "campaign_id"])
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

            # Build for date field
            date_field = ast.Call(name="toDateTime", args=[ast.Field(chain=[stats_table_name, "stat_time_day"])])

            # >= condition
            from_date = ast.Call(name="toDateTime", args=[ast.Constant(value=self.context.date_range.date_from_str)])
            gte_condition = ast.CompareOperation(left=date_field, op=ast.CompareOperationOp.GtEq, right=from_date)

            # <= condition
            to_date = ast.Call(name="toDateTime", args=[ast.Constant(value=self.context.date_range.date_to_str)])
            lte_condition = ast.CompareOperation(left=date_field, op=ast.CompareOperationOp.LtEq, right=to_date)

            conditions.extend([gte_condition, lte_condition])

        return conditions

    def _get_group_by(self) -> list[ast.Expr]:
        """Build GROUP BY expressions"""
        return [self._get_campaign_name_field()]
