# Google Ads Marketing Source Adapter

from typing import Optional, Dict, Any, List
from .base import MarketingSourceAdapter, ValidationResult, QueryContext
from ..constants import TABLE_COLUMNS


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
            campaign_table = self.config.get('campaign_table')
            stats_table = self.config.get('stats_table')
            
            if not campaign_table:
                errors.append("Missing campaign_table in config")
            if not stats_table:
                errors.append("Missing stats_table in config")
                
            if errors:
                self._log_validation_errors(errors, warnings)
                return ValidationResult(is_valid=False, errors=errors, warnings=warnings)
            
            # Validate table structure (basic checks)
            campaign_table_name = getattr(campaign_table, 'name', None)
            stats_table_name = getattr(stats_table, 'name', None)
            
            if not campaign_table_name:
                errors.append("Campaign table missing name attribute")
            if not stats_table_name:
                errors.append("Stats table missing name attribute")
            
            # Check for expected table name patterns
            if campaign_table_name and 'campaign' not in campaign_table_name.lower():
                warnings.append(f"Campaign table name '{campaign_table_name}' doesn't contain 'campaign'")
            if stats_table_name and 'stats' not in stats_table_name.lower():
                warnings.append(f"Stats table name '{stats_table_name}' doesn't contain 'stats'")
            
            is_valid = len(errors) == 0
            self._log_validation_errors(errors, warnings)
            
            return ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)
            
        except Exception as e:
            error_msg = f"Validation error: {str(e)}"
            self.logger.error("Google Ads validation failed", error=error_msg)
            return ValidationResult(is_valid=False, errors=[error_msg])
    
    def build_query(self, context: QueryContext) -> Optional[str]:
        """
        Build Google Ads query that matches the existing implementation.
        This preserves the exact same query logic from _build_google_ads_query_with_tables.
        """
        try:
            campaign_table = self.config.get('campaign_table')
            stats_table = self.config.get('stats_table')
            
            if not campaign_table or not stats_table:
                self._log_query_generation(False, "Missing required tables")
                return None
            
            campaign_table_name = getattr(campaign_table, 'name', '')
            stats_table_name = getattr(stats_table, 'name', '')
            
            # Build WHERE conditions (replicating existing logic)
            where_conditions = self._build_where_conditions(context)
            
            # This query exactly matches the existing _build_google_ads_query_with_tables implementation
            query = f"""
SELECT
    toString(c.campaign_name) as {TABLE_COLUMNS['campaign_name']},
    toString('google') as {TABLE_COLUMNS['source_name']},
    toFloat(SUM(cs.metrics_impressions)) AS {TABLE_COLUMNS['impressions']},
    toFloat(SUM(cs.metrics_clicks)) AS {TABLE_COLUMNS['clicks']},
    toFloat(SUM(cs.metrics_cost_micros) / 1000000) AS {TABLE_COLUMNS['cost']}
FROM
    {campaign_table_name} c
LEFT JOIN
    {stats_table_name} cs ON cs.campaign_id = c.campaign_id
WHERE
    {' AND '.join(where_conditions)}
GROUP BY
    c.campaign_name
            """.strip()
            
            self._log_query_generation(True)
            return query
            
        except Exception as e:
            error_msg = f"Query generation error: {str(e)}"
            self._log_query_generation(False, error_msg)
            return None
    
    def _build_where_conditions(self, context: QueryContext) -> List[str]:
        """Build WHERE conditions for Google Ads query"""
        conditions = []
        
        # Add date range conditions
        if context.date_range:
            conditions.extend([
                f"toDateTime(cs.segments_date) >= toDateTime('{context.date_range.date_from_str}')",
                f"toDateTime(cs.segments_date) <= toDateTime('{context.date_range.date_to_str}')"
            ])
        
        # Add global filters
        if context.global_filters:
            conditions.extend(context.global_filters)
        
        return conditions
    
    def get_required_permissions(self) -> List[str]:
        """Google Ads requires access to campaign and stats tables"""
        return ['read_datawarehouse_tables']
    
    def get_description(self) -> str:
        return "Google Ads native marketing data source with campaign and stats tables" 