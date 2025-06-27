# Self-Managed Marketing Source Adapters

from posthog.hogql import ast
from .base import MarketingSourceAdapter, ValidationResult, ExternalConfig
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
    UNKNOWN_CAMPAIGN,
)
from products.marketing_analytics.backend.hogql_queries.utils import get_source_map_field


class SelfManagedAdapter(MarketingSourceAdapter[ExternalConfig]):
    """
    Base adapter for self-managed marketing sources.
    Self-managed sources are data warehouse tables that users manually upload
    and configure field mappings for marketing analytics.
    """

    def __init__(self, config: ExternalConfig, context):
        super().__init__(config, context)

    def get_source_type(self) -> str:
        return f"self_managed_{self.config.source_type}"

    def validate(self) -> ValidationResult:
        """Validate self-managed table schema and required fields"""
        errors: list[str] = []
        warnings: list[str] = []

        try:
            # Validate required schema fields
            missing_required_fields = []
            for field_name, field_config in MARKETING_ANALYTICS_SCHEMA.items():
                if field_config["required"]:
                    field_value = get_source_map_field(self.config.source_map, field_name)
                    if not field_value or (isinstance(field_value, str) and field_value.strip() == ""):
                        missing_required_fields.append(field_name)

            if missing_required_fields:
                errors.extend([f"Missing required field: {field}" for field in missing_required_fields])

            # Must have either campaign_name or utm_campaign_name
            campaign_field = get_source_map_field(
                self.config.source_map, SOURCE_MAP_UTM_CAMPAIGN_NAME
            ) or get_source_map_field(self.config.source_map, SOURCE_MAP_CAMPAIGN_NAME)
            if not campaign_field:
                errors.append("Missing campaign name field (utm_campaign_name or campaign_name)")

            # Check for date field
            date_field = get_source_map_field(self.config.source_map, SOURCE_MAP_DATE)
            if not date_field:
                errors.append("Missing date field in source_map")

            is_valid = len(errors) == 0
            self._log_validation_errors(errors, warnings)

            return ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)

        except Exception as e:
            error_msg = f"Validation error: {str(e)}"
            self.logger.exception("Self-managed table validation failed", error=error_msg)
            return ValidationResult(is_valid=False, errors=[error_msg])

    def _get_campaign_name_field(self) -> ast.Expr:
        campaign_name_field = get_source_map_field(
            self.config.source_map, SOURCE_MAP_UTM_CAMPAIGN_NAME
        ) or get_source_map_field(self.config.source_map, SOURCE_MAP_CAMPAIGN_NAME)

        if not campaign_name_field:
            # Fallback if no campaign field is found
            return ast.Call(name="toString", args=[ast.Constant(value=UNKNOWN_CAMPAIGN)])

        return ast.Call(name="toString", args=[ast.Field(chain=[campaign_name_field])])

    def _get_source_name_field(self) -> ast.Expr:
        source_name_field = (
            get_source_map_field(self.config.source_map, SOURCE_MAP_UTM_SOURCE_NAME)
            or get_source_map_field(self.config.source_map, SOURCE_MAP_SOURCE_NAME)
            or self.config.schema_name
        )

        # Always treat as a constant value since it's likely a hardcoded schema name
        return ast.Call(name="toString", args=[ast.Constant(value=source_name_field)])

    def _get_cost_field(self) -> ast.Expr:
        # Handle currency conversion
        total_cost_field = get_source_map_field(self.config.source_map, SOURCE_MAP_TOTAL_COST)
        currency_field = get_source_map_field(self.config.source_map, SOURCE_MAP_CURRENCY)
        base_currency = self.context.base_currency

        if currency_field and total_cost_field:
            # toFloat(convertCurrency('currency_field', 'base_currency', toFloat(coalesce(total_cost_field, 0))))
            coalesce = ast.Call(name="coalesce", args=[ast.Field(chain=[total_cost_field]), ast.Constant(value=0)])
            inner_toFloat = ast.Call(name="toFloat", args=[coalesce])
            convert_currency = ast.Call(
                name="convertCurrency",
                args=[ast.Constant(value=currency_field), ast.Constant(value=base_currency), inner_toFloat],
            )
            return ast.Call(name="toFloat", args=[convert_currency])
        elif total_cost_field:
            # toFloat(coalesce(total_cost_field, 0))
            coalesce = ast.Call(name="coalesce", args=[ast.Field(chain=[total_cost_field]), ast.Constant(value=0)])
            return ast.Call(name="toFloat", args=[coalesce])
        else:
            # 0
            return ast.Constant(value=0)

    def _get_impressions_field(self) -> ast.Expr:
        impressions_field = get_source_map_field(self.config.source_map, SOURCE_MAP_IMPRESSIONS)

        inner_expr: ast.Expr
        if impressions_field is None:
            inner_expr = ast.Constant(value=0)
        else:
            inner_expr = ast.Field(chain=[impressions_field])

        coalesce = ast.Call(name="coalesce", args=[inner_expr, ast.Constant(value=0)])
        return ast.Call(name="toFloat", args=[coalesce])

    def _get_clicks_field(self) -> ast.Expr:
        clicks_field = get_source_map_field(self.config.source_map, SOURCE_MAP_CLICKS)

        inner_expr: ast.Expr
        if clicks_field is None:
            inner_expr = ast.Constant(value=0)
        else:
            inner_expr = ast.Field(chain=[clicks_field])

        coalesce = ast.Call(name="coalesce", args=[inner_expr, ast.Constant(value=0)])
        return ast.Call(name="toFloat", args=[coalesce])

    def _get_from(self) -> ast.JoinExpr:
        """Build FROM clause"""
        table_name: str = self.config.table.name
        table = ast.Field(chain=[table_name])
        return ast.JoinExpr(table=table)

    def _get_where_conditions(self) -> list[ast.Expr]:
        """Build WHERE conditions"""
        date_field = get_source_map_field(self.config.source_map, SOURCE_MAP_DATE)
        conditions: list[ast.Expr] = []
        date_cast: ast.Expr

        # Add date range filter
        if self.context.date_range and date_field:
            if date_field != "timestamp":
                # toDateTime(date_field) >= toDateTime('date_from')
                date_cast = ast.Call(name="toDateTime", args=[ast.Field(chain=[date_field])])
            else:
                date_cast = ast.Field(chain=[date_field])

            # Build >= condition
            from_date = ast.Call(name="toDateTime", args=[ast.Constant(value=self.context.date_range.date_from_str)])
            gte_condition = ast.CompareOperation(left=date_cast, op=ast.CompareOperationOp.GtEq, right=from_date)

            # Build <= condition
            to_date = ast.Call(name="toDateTime", args=[ast.Constant(value=self.context.date_range.date_to_str)])
            lte_condition = ast.CompareOperation(left=date_cast, op=ast.CompareOperationOp.LtEq, right=to_date)

            conditions.extend([gte_condition, lte_condition])

        return conditions

    def _get_group_by(self) -> list[ast.Expr]:
        """Build GROUP BY expressions"""
        # Self-managed tables typically don't need grouping
        return []


class AWSAdapter(SelfManagedAdapter):
    """Adapter for AWS S3-based self-managed marketing data"""

    def get_platform_type(self) -> str:
        return "aws"


class GoogleCloudAdapter(SelfManagedAdapter):
    """Adapter for Google Cloud Storage-based self-managed marketing data"""

    def get_platform_type(self) -> str:
        return "google_cloud"


class CloudflareR2Adapter(SelfManagedAdapter):
    """Adapter for Cloudflare R2-based self-managed marketing data"""

    def get_platform_type(self) -> str:
        return "cloudflare_r2"


class AzureAdapter(SelfManagedAdapter):
    """Adapter for Azure Blob Storage-based self-managed marketing data"""

    def get_platform_type(self) -> str:
        return "azure"
