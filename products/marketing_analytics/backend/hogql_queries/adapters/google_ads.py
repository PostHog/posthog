# Google Ads Marketing Source Adapter

from typing import Optional
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

    def _get_campaign_name_field(self) -> str:
        return f"toString({self.config.get('campaign_table').name}.campaign_name)"

    def _get_source_name_field(self) -> str:
        return f"toString('google')"

    def _get_impressions_field(self) -> str:
        return f"toFloat(SUM({self.config.get('stats_table').name}.metrics_impressions))"

    def _get_clicks_field(self) -> str:
        return f"toFloat(SUM({self.config.get('stats_table').name}.metrics_clicks))"

    def _get_cost_field(self) -> str:
        return f"toFloat(SUM({self.config.get('stats_table').name}.metrics_cost_micros) / 1000000)"

    def _get_from_clause(self) -> str:
        campaign_table = self.config.get("campaign_table")
        return f"FROM {campaign_table.name}"

    def _get_join_clause(self) -> str:
        stats_table = self.config.get("stats_table")
        campaign_table = self.config.get("campaign_table")
        return f"LEFT JOIN {stats_table.name} ON {campaign_table.name}.campaign_id = {stats_table.name}.campaign_id"

    def _get_where_conditions(self) -> list[str]:
        """Build WHERE conditions for Google Ads query"""
        conditions = []

        # Add date range conditions
        if self.context.date_range:
            conditions.extend(
                [
                    f"toDateTime({self.config.get('stats_table').name}.segments_date) >= toDateTime('{self.context.date_range.date_from_str}')",
                    f"toDateTime({self.config.get('stats_table').name}.segments_date) <= toDateTime('{self.context.date_range.date_to_str}')",
                ]
            )

        # Add global filters
        if self.context.global_filters:
            conditions.extend(self.context.global_filters)

        return "WHERE " + " AND ".join(conditions) if conditions else ""

    def _get_group_by_clause(self) -> str:
        return f"GROUP BY {self._get_campaign_name_field()}"

    def build_query(self) -> Optional[str]:
        """
        Build Google Ads query that matches the existing implementation.
        This preserves the exact same query logic from _build_google_ads_query_with_tables.
        """
        try:
            # This query exactly matches the existing _build_google_ads_query_with_tables implementation
            query = f"""
SELECT
    {self._get_campaign_name_field()} as {self.campaign_name_field},
    {self._get_source_name_field()} as {self.source_name_field},
    {self._get_impressions_field()} as {self.impressions_field},
    {self._get_clicks_field()} as {self.clicks_field},
    {self._get_cost_field()} as {self.cost_field}
{self._get_from_clause()}
{self._get_join_clause()}
{self._get_where_conditions()}
{self._get_group_by_clause()}
"""

            self._log_query_generation(True)
            return query

        except Exception as e:
            error_msg = f"Query generation error: {str(e)}"
            self._log_query_generation(False, error_msg)
            return None
