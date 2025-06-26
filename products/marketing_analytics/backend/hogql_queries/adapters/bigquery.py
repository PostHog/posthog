# BigQuery Marketing Source Adapter

from .base import MarketingSourceAdapter, ValidationResult
from ..constants import (
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
from ..utils import get_source_map_field


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
        """Validate BigQuery table schema and required fields"""
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

    def _get_campaign_name_field(self) -> str:
        campaign_name_field = get_source_map_field(
            self.config.get("source_map"), SOURCE_MAP_UTM_CAMPAIGN_NAME
        ) or get_source_map_field(self.config.get("source_map"), SOURCE_MAP_CAMPAIGN_NAME)
        return f"toString({campaign_name_field})"

    def _get_source_name_field(self) -> str:
        source_name_field = (
            get_source_map_field(self.config.get("source_map"), SOURCE_MAP_UTM_SOURCE_NAME)
            or get_source_map_field(self.config.get("source_map"), SOURCE_MAP_SOURCE_NAME)
            or f"'{self.config.get('schema_name')}'"
        )
        return f"toString({source_name_field})"

    def _get_impressions_field(self) -> str:
        return (
            f"toFloat(coalesce({get_source_map_field(self.config.get('source_map'), SOURCE_MAP_IMPRESSIONS, '0')}, 0))"
        )

    def _get_clicks_field(self) -> str:
        return f"toFloat(coalesce({get_source_map_field(self.config.get('source_map'), SOURCE_MAP_CLICKS, '0')}, 0))"

    def _get_cost_field(self) -> str:
        # Handle currency conversion (exactly matching existing logic)
        total_cost_field = get_source_map_field(self.config.get("source_map"), SOURCE_MAP_TOTAL_COST)
        currency_field = get_source_map_field(self.config.get("source_map"), SOURCE_MAP_CURRENCY)
        base_currency = self.context.base_currency

        if currency_field and total_cost_field:
            cost_select = f"toFloat(convertCurrency('{currency_field}', '{base_currency}', toFloat(coalesce({total_cost_field}, 0))))"
        elif total_cost_field:
            cost_select = f"toFloat(coalesce({total_cost_field}, 0))"
        else:
            cost_select = "0"

        return cost_select

    def _get_from_clause(self) -> str:
        return f"FROM {self.config.get('table').name}"

    def _get_join_clause(self) -> str:
        return ""

    def _get_group_by_clause(self) -> str:
        return ""

    def _get_where_conditions(self) -> list[str]:
        """Build WHERE conditions optimized for BigQuery"""
        date_field = get_source_map_field(self.config.get("source_map"), SOURCE_MAP_DATE)
        conditions = []

        # Add date range conditions
        if self.context.date_range:
            date_cast = f"toDateTime({date_field})" if date_field != "timestamp" else date_field
            conditions.extend(
                [
                    f"{date_cast} >= toDateTime('{self.context.date_range.date_from_str}')",
                    f"{date_cast} <= toDateTime('{self.context.date_range.date_to_str}')",
                ]
            )

        # Add global filters
        if self.context.global_filters:
            conditions.extend(self.context.global_filters)

        return "WHERE " + " AND ".join(conditions) if conditions else ""
