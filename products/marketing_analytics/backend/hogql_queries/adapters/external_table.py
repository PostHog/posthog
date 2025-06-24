# External Table Marketing Source Adapter

from typing import Optional, Dict, Any, List
from .base import MarketingSourceAdapter, ValidationResult, QueryContext
from ..constants import (
    TABLE_COLUMNS, MARKETING_ANALYTICS_SCHEMA, DEFAULT_CURRENCY
)
from ..utils import get_source_map_field


class ExternalTableAdapter(MarketingSourceAdapter):
    """
    Adapter for external tables (both managed and self-managed).
    Expects config with:
    - table: DataWarehouse table object
    - source_map: Field mapping configuration
    - source_type: Type of external source (e.g., 'self_managed', 'GoogleAds', etc.)
    """
    
    def get_source_type(self) -> str:
        return f"external_table_{self.config.get('source_type', 'unknown')}"
    
    def validate(self) -> ValidationResult:
        """Validate external table schema and required fields"""
        errors = []
        warnings = []
        
        try:
            # Check required config
            table = self.config.get('table')
            source_map = self.config.get('source_map')
            
            if not table:
                errors.append("Missing table in config")
            if not source_map:
                errors.append("Missing source_map in config")
                
            if errors:
                self._log_validation_errors(errors, warnings)
                return ValidationResult(is_valid=False, errors=errors, warnings=warnings)
            
            # Validate table attributes
            table_name = getattr(table, 'name', None)
            if not table_name:
                errors.append("Table missing name attribute")
            
            # Validate required schema fields
            missing_required_fields = []
            for field_name, field_config in MARKETING_ANALYTICS_SCHEMA.items():
                if field_config['required']:
                    field_value = get_source_map_field(source_map, field_name)
                    if not field_value or (isinstance(field_value, str) and field_value.strip() == ''):
                        missing_required_fields.append(field_name)
            
            if missing_required_fields:
                errors.extend([f"Missing required field: {field}" for field in missing_required_fields])
            
            # Must have either campaign_name or utm_campaign_name
            campaign_field = (
                get_source_map_field(source_map, 'utm_campaign_name') or 
                get_source_map_field(source_map, 'campaign_name')
            )
            if not campaign_field:
                errors.append("Missing campaign name field (utm_campaign_name or campaign_name)")
            
            # Check for date field
            date_field = get_source_map_field(source_map, 'date')
            if not date_field:
                errors.append("Missing date field in source_map")
            
            is_valid = len(errors) == 0
            self._log_validation_errors(errors, warnings)
            
            return ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)
            
        except Exception as e:
            error_msg = f"Validation error: {str(e)}"
            self.logger.error("External table validation failed", error=error_msg)
            return ValidationResult(is_valid=False, errors=[error_msg])
    
    def build_query(self, context: QueryContext) -> Optional[str]:
        """
        Build external table query that matches the existing implementation.
        This preserves the exact same query logic from _union_non_native_queries.
        """
        try:
            table = self.config.get('table')
            source_map = self.config.get('source_map')
            
            if not table or not source_map:
                self._log_query_generation(False, "Missing required table or source_map")
                return None
            
            table_name = getattr(table, 'name', '')
            schema_name = self.config.get('schema_name', getattr(table, 'name', ''))
            
            # Get field mappings (exactly matching existing logic)
            source_name_field = (
                get_source_map_field(source_map, 'utm_source_name') or 
                get_source_map_field(source_map, 'source_name') or 
                f"'{schema_name}'"
            )
            
            campaign_name_field = (
                get_source_map_field(source_map, 'utm_campaign_name') or 
                get_source_map_field(source_map, 'campaign_name')
            )
            
            if not campaign_name_field:
                self._log_query_generation(False, "Missing campaign name field")
                return None
            
            # Handle currency conversion (exactly matching existing logic)
            total_cost_field = get_source_map_field(source_map, 'total_cost')
            currency_field = get_source_map_field(source_map, 'currency')
            base_currency = context.base_currency or DEFAULT_CURRENCY
            
            if currency_field and total_cost_field:
                cost_select = f"toFloat(convertCurrency('{currency_field}', '{base_currency}', toFloat(coalesce({total_cost_field}, 0))))"
            elif total_cost_field:
                cost_select = f"toFloat(coalesce({total_cost_field}, 0))"
            else:
                cost_select = "0"
            
            # Get other field mappings
            impressions_field = get_source_map_field(source_map, 'impressions', '0')
            clicks_field = get_source_map_field(source_map, 'clicks', '0')
            date_field = get_source_map_field(source_map, 'date')
            
            if not date_field:
                self._log_query_generation(False, "Missing date field")
                return None
            
            # Build WHERE conditions (exactly matching existing logic)
            where_conditions = self._build_where_conditions(context, date_field)
            
            # This query exactly matches the existing _union_non_native_queries implementation
            query = f"""
SELECT 
    toString({campaign_name_field}) as {TABLE_COLUMNS['campaign_name']},
    toString({source_name_field}) as {TABLE_COLUMNS['source_name']},
    toFloat(coalesce({impressions_field}, 0)) as {TABLE_COLUMNS['impressions']},
    toFloat(coalesce({clicks_field}, 0)) as {TABLE_COLUMNS['clicks']},
    {cost_select} as {TABLE_COLUMNS['cost']}
FROM {table_name}
WHERE {' AND '.join(where_conditions)}
            """.strip()
            
            self._log_query_generation(True)
            return query
            
        except Exception as e:
            error_msg = f"Query generation error: {str(e)}"
            self._log_query_generation(False, error_msg)
            return None
    
    def _build_where_conditions(self, context: QueryContext, date_field: str) -> List[str]:
        """Build WHERE conditions for external table query"""
        conditions = []
        
        # Add date range conditions
        if context.date_range:
            date_cast = f"toDateTime({date_field})" if date_field != 'timestamp' else date_field
            conditions.extend([
                f"{date_cast} >= toDateTime('{context.date_range.date_from_str}')",
                f"{date_cast} <= toDateTime('{context.date_range.date_to_str}')"
            ])
        
        # Add global filters
        if context.global_filters:
            conditions.extend(context.global_filters)
        
        return conditions
    
    def get_required_permissions(self) -> List[str]:
        """External tables require access to warehouse tables"""
        return ['read_datawarehouse_tables']
    
    def get_description(self) -> str:
        source_type = self.config.get('source_type', 'unknown')
        table_name = getattr(self.config.get('table'), 'name', 'unknown')
        return f"External table '{table_name}' ({source_type})" 