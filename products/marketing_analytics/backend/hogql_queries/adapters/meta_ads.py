# Meta Ads Marketing Source Adapter

from posthog.schema import NativeMarketingSource

from posthog.hogql import ast

from ..constants import INTEGRATION_DEFAULT_SOURCES, INTEGRATION_FIELD_NAMES, INTEGRATION_PRIMARY_SOURCE
from .base import MarketingSourceAdapter, MetaAdsConfig, ValidationResult

# Omni action types are preferred as they're comprehensive metrics that include all channels.
# We fallback to individual action types only if omni types return no results.
META_OMNI_ACTION_TYPES = [
    "omni_purchase",
    "omni_lead",
    "omni_complete_registration",
    "omni_app_install",
    "omni_subscribe",
]

# Fallback action types for accounts without omnichannel tracking or older data
META_FALLBACK_ACTION_TYPES = [
    # Purchase
    "purchase",
    "offsite_conversion.fb_pixel_purchase",
    "app_custom_event.fb_mobile_purchase",
    # Lead
    "lead",
    "offsite_conversion.fb_pixel_lead",
    "onsite_conversion.lead_grouped",
    # Registration
    "complete_registration",
    "offsite_conversion.fb_pixel_complete_registration",
    "app_custom_event.fb_mobile_complete_registration",
    "offsite_complete_registration_add_meta_leads",
    # App install
    "app_install",
    "mobile_app_install",
    # Subscribe
    "subscribe",
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

    def _get_reported_conversion_field(self) -> ast.Expr:
        stats_table_name = self.config.stats_table.name

        # Check if conversions column exists in the table schema. The field exists in Meta Ads but
        # if it's not used, it won't be in the response, therefore, won't be saved in the table and the column
        # won't be created in the table.
        try:
            columns = getattr(self.config.stats_table, "columns", None)
            if columns and hasattr(columns, "__contains__") and "actions" in columns:
                actions_field = ast.Field(chain=[stats_table_name, "actions"])
                # Use coalesce to convert Nullable(String) to String, defaulting to empty array '[]'
                actions_non_null = ast.Call(name="coalesce", args=[actions_field, ast.Constant(value="[]")])

                # Prefer omni action types (comprehensive metrics), fallback to individual types
                omni_sum = self._build_array_sum_for_action_types(actions_non_null, META_OMNI_ACTION_TYPES)
                fallback_sum = self._build_array_sum_for_action_types(actions_non_null, META_FALLBACK_ACTION_TYPES)

                # Use IF to prefer omni, fallback if omni returns 0
                array_sum = ast.Call(
                    name="if",
                    args=[
                        ast.CompareOperation(
                            left=omni_sum,
                            op=ast.CompareOperationOp.Gt,
                            right=ast.Constant(value=0),
                        ),
                        omni_sum,
                        fallback_sum,
                    ],
                )

                sum_result = ast.Call(name="SUM", args=[array_sum])
                return ast.Call(name="toFloat", args=[sum_result])
        except (TypeError, AttributeError, KeyError):
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
                action_values_non_null = ast.Call(name="coalesce", args=[action_values_field, ast.Constant(value="[]")])

                # Prefer omni action types (comprehensive metrics), fallback to individual types
                omni_sum = self._build_array_sum_for_action_types(action_values_non_null, META_OMNI_ACTION_TYPES)
                fallback_sum = self._build_array_sum_for_action_types(
                    action_values_non_null, META_FALLBACK_ACTION_TYPES
                )

                # Use IF to prefer omni, fallback if omni returns 0
                array_sum = ast.Call(
                    name="if",
                    args=[
                        ast.CompareOperation(
                            left=omni_sum,
                            op=ast.CompareOperationOp.Gt,
                            right=ast.Constant(value=0),
                        ),
                        omni_sum,
                        fallback_sum,
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
