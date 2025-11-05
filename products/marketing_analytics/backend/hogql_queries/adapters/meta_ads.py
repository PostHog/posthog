# Meta Ads Marketing Source Adapter

from posthog.hogql import ast

from .base import MarketingSourceAdapter, MetaAdsConfig, ValidationResult


class MetaAdsAdapter(MarketingSourceAdapter[MetaAdsConfig]):
    """
    Adapter for Meta Ads native marketing data.
    Expects config with:
    - campaign_table: DataWarehouse table with campaign data
    - stats_table: DataWarehouse table with campaign stats
    """

    @classmethod
    def get_source_identifier_mapping(cls) -> dict[str, list[str]]:
        """Meta Ads campaigns typically use 'meta' as the UTM source"""
        return {
            "meta": [
                "meta",
                "facebook",
                "instagram",
                "messenger",
                "fb",
                "whatsapp",
                "audience_network",
                "facebook_marketplace",
                "threads",
            ]
        }

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

    def _get_campaign_name_field(self) -> ast.Expr:
        campaign_table_name = self.config.campaign_table.name
        return ast.Call(name="toString", args=[ast.Field(chain=[campaign_table_name, "name"])])

    def _get_impressions_field(self) -> ast.Expr:
        stats_table_name = self.config.stats_table.name
        sum = ast.Call(
            name="SUM", args=[ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, "impressions"])])]
        )
        return ast.Call(name="toFloat", args=[sum])

    def _get_clicks_field(self) -> ast.Expr:
        stats_table_name = self.config.stats_table.name
        sum = ast.Call(
            name="SUM", args=[ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, "clicks"])])]
        )
        return ast.Call(name="toFloat", args=[sum])

    def _get_cost_field(self) -> ast.Expr:
        stats_table_name = self.config.stats_table.name
        base_currency = self.context.base_currency

        # Get cost
        spend_field = ast.Field(chain=[stats_table_name, "spend"])
        spend_float = ast.Call(name="toFloat", args=[spend_field])

        # Check if currency column exists in stats table
        try:
            columns = getattr(self.config.stats_table, "columns", None)
            if columns and hasattr(columns, "__contains__") and "account_currency" in columns:
                # Convert each row's spend, then sum
                # Use coalesce to handle NULL currency values - fallback to base_currency
                currency_field = ast.Field(chain=[stats_table_name, "account_currency"])
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

        # Check if conversions column exists in the table schema. The field exists in Meta Ads but
        # if it's not used, it won't be in the response, therefore, won't be saved in the table and the column
        # won't be created in the table.
        try:
            # Try to check if conversions column exists
            columns = getattr(self.config.stats_table, "columns", None)
            if columns and hasattr(columns, "__contains__") and "conversions" in columns:
                sum = ast.Call(
                    name="SUM",
                    args=[ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, "conversions"])])],
                )
                return ast.Call(name="toFloat", args=[sum])
        except (TypeError, AttributeError, KeyError):
            # If columns is not iterable, doesn't exist, or has unexpected structure, fall back to 0
            pass
        # Column doesn't exist or can't be checked, return 0
        return ast.Constant(value=0)

    def _get_from(self) -> ast.JoinExpr:
        """Build FROM and JOIN clauses"""
        campaign_table_name = self.config.campaign_table.name
        stats_table_name = self.config.stats_table.name

        # Create base table
        campaign_table = ast.Field(chain=[campaign_table_name])

        # Create joined table with join condition
        stats_table = ast.Field(chain=[stats_table_name])

        # Build join condition: campaign_table.campaign_id = stats_table.campaign_id
        left_field = ast.Field(chain=[campaign_table_name, "id"])
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
            date_field = ast.Call(name="toDateTime", args=[ast.Field(chain=[stats_table_name, "date_stop"])])

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
