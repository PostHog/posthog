# Meta Ads Marketing Source Adapter

from posthog.schema import NativeMarketingSource

from posthog.hogql import ast

from ..constants import INTEGRATION_DEFAULT_SOURCES, INTEGRATION_FIELD_NAMES, INTEGRATION_PRIMARY_SOURCE
from .base import MarketingSourceAdapter, MetaAdsConfig, ValidationResult

# Conversion action types to extract from Meta's actions array (counts)
# Includes all meaningful conversion events: standard, omni (cross-channel), and offsite pixel events
META_CONVERSION_ACTION_TYPES = [
    # Purchase
    "purchase",
    "omni_purchase",
    "offsite_conversion.fb_pixel_purchase",
    # Lead
    "lead",
    "omni_lead",
    "offsite_conversion.fb_pixel_lead",
    # Registration
    "complete_registration",
    "omni_complete_registration",
    "offsite_conversion.fb_pixel_complete_registration",
    # Add to cart
    "add_to_cart",
    "omni_add_to_cart",
    "offsite_conversion.fb_pixel_add_to_cart",
    # Initiate checkout
    "initiate_checkout",
    "omni_initiate_checkout",
    "offsite_conversion.fb_pixel_initiate_checkout",
    # App install
    "app_install",
    "omni_app_install",
    "mobile_app_install",
    # Subscribe
    "subscribe",
    "omni_subscribe",
    "offsite_conversion.fb_pixel_subscribe",
    # Add payment info
    "add_payment_info",
    "omni_add_payment_info",
    "offsite_conversion.fb_pixel_add_payment_info",
]

# Action types that have meaningful monetary values (for action_values array)
# Limited to purchase/transaction events that carry revenue data
META_CONVERSION_VALUE_ACTION_TYPES = [
    # Purchase (primary revenue events)
    "purchase",
    "omni_purchase",
    "offsite_conversion.fb_pixel_purchase",
    # Subscribe (recurring revenue)
    "subscribe",
    "omni_subscribe",
    "offsite_conversion.fb_pixel_subscribe",
]


class MetaAdsAdapter(MarketingSourceAdapter[MetaAdsConfig]):
    """
    Adapter for Meta Ads native marketing data.
    Expects config with:
    - campaign_table: DataWarehouse table with campaign data
    - stats_table: DataWarehouse table with campaign stats
    """

    _source_type = NativeMarketingSource.META_ADS

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

        # Get cost - use ifNull(toFloat(...), 0) to handle both numeric types and NULLs
        spend_field = ast.Field(chain=[stats_table_name, "spend"])
        spend_float = ast.Call(
            name="ifNull",
            args=[ast.Call(name="toFloat", args=[spend_field]), ast.Constant(value=0)],
        )

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

    def _get_reported_conversion_field(self) -> ast.Expr:
        stats_table_name = self.config.stats_table.name

        # Check if conversions column exists in the table schema. The field exists in Meta Ads but
        # if it's not used, it won't be in the response, therefore, won't be saved in the table and the column
        # won't be created in the table.
        try:
            # Try to check if conversions column exists
            columns = getattr(self.config.stats_table, "columns", None)
            if columns and hasattr(columns, "__contains__") and "actions" in columns:
                actions_field = ast.Field(chain=[stats_table_name, "actions"])
                # Use coalesce to convert Nullable(String) to String, defaulting to empty array '[]'
                # This prevents "Nested type Array(String) cannot be inside Nullable type" error
                actions_non_null = ast.Call(name="coalesce", args=[actions_field, ast.Constant(value="[]")])

                array_sum = ast.Call(
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
                                ast.Lambda(
                                    args=["x"], expr=self._build_action_type_filter(META_CONVERSION_ACTION_TYPES)
                                ),
                                ast.Call(name="JSONExtractArrayRaw", args=[actions_non_null]),
                            ],
                        ),
                    ],
                )
                sum_result = ast.Call(name="SUM", args=[array_sum])
                return ast.Call(name="toFloat", args=[sum_result])
        except (TypeError, AttributeError, KeyError):
            # If columns is not iterable, doesn't exist, or has unexpected structure, fall back to 0
            pass
        # Column doesn't exist or can't be checked, return 0
        return ast.Constant(value=0)

    def _get_reported_conversion_value_field(self) -> ast.Expr:
        stats_table_name = self.config.stats_table.name

        # Check if conversion_values column exists in the table schema. Similar to conversions,
        # this field may not exist if no conversion values were tracked.
        try:
            columns = getattr(self.config.stats_table, "columns", None)
            if columns and hasattr(columns, "__contains__") and "action_values" in columns:
                action_values_field = ast.Field(chain=[stats_table_name, "action_values"])
                # Use coalesce to convert Nullable(String) to String, defaulting to empty array '[]'
                # This prevents "Nested type Array(String) cannot be inside Nullable type" error
                action_values_non_null = ast.Call(name="coalesce", args=[action_values_field, ast.Constant(value="[]")])

                array_sum = ast.Call(
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
                                ast.Lambda(
                                    args=["x"], expr=self._build_action_type_filter(META_CONVERSION_VALUE_ACTION_TYPES)
                                ),
                                ast.Call(name="JSONExtractArrayRaw", args=[action_values_non_null]),
                            ],
                        ),
                    ],
                )
                sum_result = ast.Call(name="SUM", args=[array_sum])
                return ast.Call(name="toFloat", args=[sum_result])
        except (TypeError, AttributeError, KeyError):
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
        """Build GROUP BY expressions - group by both name and ID"""
        return [self._get_campaign_name_field(), self._get_campaign_id_field()]
