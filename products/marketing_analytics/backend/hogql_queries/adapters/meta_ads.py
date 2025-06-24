# Meta Ads Marketing Source Adapter (Example)

from typing import Optional, Dict, Any, List
from .base import MarketingSourceAdapter, ValidationResult, QueryContext
from ..constants import TABLE_COLUMNS


class MetaAdsAdapter(MarketingSourceAdapter):
    """
    Example adapter for Meta Ads marketing data.
    This demonstrates how easy it is to add new marketing sources.
    
    Expects config with:
    - table: DataWarehouse table with Meta Ads data (single table structure)
    - source_id: Source identifier
    """
    
    def get_source_type(self) -> str:
        return "MetaAds"
    
    def validate(self) -> ValidationResult:
        """Validate Meta Ads table and required fields"""
        errors = []
        warnings = []
        
        try:
            # Check required config
            table = self.config.get('table')
            
            if not table:
                errors.append("Missing table in config")
                self._log_validation_errors(errors, warnings)
                return ValidationResult(is_valid=False, errors=errors, warnings=warnings)
            
            # Validate table structure
            table_name = getattr(table, 'name', None)
            if not table_name:
                errors.append("Table missing name attribute")
            
            # Check for expected table name pattern
            if table_name and 'meta' not in table_name.lower() and 'facebook' not in table_name.lower():
                warnings.append(f"Table name '{table_name}' doesn't contain 'meta' or 'facebook'")
            
            is_valid = len(errors) == 0
            self._log_validation_errors(errors, warnings)
            
            return ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)
            
        except Exception as e:
            error_msg = f"Validation error: {str(e)}"
            self.logger.error("Meta Ads validation failed", error=error_msg)
            return ValidationResult(is_valid=False, errors=[error_msg])
    
    def build_query(self, context: QueryContext) -> Optional[str]:
        """
        Build Meta Ads query for single table structure.
        Meta Ads typically has all data in one table unlike Google Ads.
        """
        try:
            table = self.config.get('table')
            
            if not table:
                self._log_query_generation(False, "Missing required table")
                return None
            
            table_name = getattr(table, 'name', '')
            
            # Build WHERE conditions
            where_conditions = self._build_where_conditions(context)
            
            # Meta Ads query - assumes single table with all campaign data
            query = f"""
SELECT
    toString(campaign_name) as {TABLE_COLUMNS['campaign_name']},
    toString('meta') as {TABLE_COLUMNS['source_name']},
    toFloat(SUM(impressions)) AS {TABLE_COLUMNS['impressions']},
    toFloat(SUM(clicks)) AS {TABLE_COLUMNS['clicks']},
    toFloat(SUM(spend)) AS {TABLE_COLUMNS['cost']}
FROM
    {table_name}
WHERE
    {' AND '.join(where_conditions)}
GROUP BY
    campaign_name
            """.strip()
            
            self._log_query_generation(True)
            return query
            
        except Exception as e:
            error_msg = f"Query generation error: {str(e)}"
            self._log_query_generation(False, error_msg)
            return None
    
    def _build_where_conditions(self, context: QueryContext) -> List[str]:
        """Build WHERE conditions for Meta Ads query"""
        conditions = []
        
        # Add date range conditions - Meta typically uses 'date_start' field
        if context.date_range:
            conditions.extend([
                f"toDateTime(date_start) >= toDateTime('{context.date_range.date_from_str}')",
                f"toDateTime(date_start) <= toDateTime('{context.date_range.date_to_str}')"
            ])
        
        # Add global filters
        if context.global_filters:
            conditions.extend(context.global_filters)
        
        return conditions
    
    def get_required_permissions(self) -> List[str]:
        """Meta Ads requires access to campaign table"""
        return ['read_datawarehouse_tables']
    
    def get_description(self) -> str:
        return "Meta Ads marketing data source with single table structure" 