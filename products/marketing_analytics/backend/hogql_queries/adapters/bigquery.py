# BigQuery Marketing Source Adapter

from typing import Optional, Dict, Any, List
from .base import MarketingSourceAdapter, ValidationResult, QueryContext
from ..constants import (
    TABLE_COLUMNS, MARKETING_ANALYTICS_SCHEMA, DEFAULT_CURRENCY
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
            
            # BigQuery-specific validation
            bigquery_errors, bigquery_warnings = self._validate_bigquery_specific(table, source_map)
            errors.extend(bigquery_errors)
            warnings.extend(bigquery_warnings)
            
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
            self.logger.error("BigQuery table validation failed", error=error_msg)
            return ValidationResult(is_valid=False, errors=[error_msg])
    
    def _validate_bigquery_specific(self, table, source_map) -> tuple[List[str], List[str]]:
        """BigQuery-specific validation checks"""
        errors = []
        warnings = []
        
        # Check if table name follows BigQuery naming patterns
        table_name = getattr(table, 'name', '')
        if '.' in table_name:
            # BigQuery tables often have format: project.dataset.table
            parts = table_name.split('.')
            if len(parts) < 2:
                warnings.append("BigQuery table name doesn't follow project.dataset.table format")
        
        # Check for BigQuery-specific data types in field mappings
        # BigQuery typically uses different column naming conventions
        date_field = get_source_map_field(source_map, 'date')
        if date_field and 'timestamp' in date_field.lower():
            warnings.append("BigQuery timestamp fields may need special date conversion")
        
        # Check for potential BigQuery cost fields (often in different formats)
        cost_field = get_source_map_field(source_map, 'total_cost')
        if cost_field and any(keyword in cost_field.lower() for keyword in ['spend', 'cost_micros']):
            warnings.append("BigQuery cost field may need unit conversion (micros to standard currency)")
        
        return errors, warnings
    
    def build_query(self, context: QueryContext) -> Optional[str]:
        """
        Build BigQuery marketing data query.
        Similar to external table but with BigQuery-specific optimizations.
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
                f"'{schema_name}'"  # Use schema name, not hardcoded 'BigQuery'
            )
            
            campaign_name_field = (
                get_source_map_field(source_map, 'utm_campaign_name') or 
                get_source_map_field(source_map, 'campaign_name')
            )
            
            if not campaign_name_field:
                self._log_query_generation(False, "Missing campaign name field")
                return None
            
            # Handle currency conversion with BigQuery-specific logic
            total_cost_field = get_source_map_field(source_map, 'total_cost')
            currency_field = get_source_map_field(source_map, 'currency')
            base_currency = context.base_currency or DEFAULT_CURRENCY
            
            # BigQuery often stores costs in micros, handle conversion
            cost_select = self._build_bigquery_cost_select(
                total_cost_field, currency_field, base_currency
            )
            
            # Get other field mappings
            impressions_field = get_source_map_field(source_map, 'impressions', '0')
            clicks_field = get_source_map_field(source_map, 'clicks', '0')
            date_field = get_source_map_field(source_map, 'date')
            
            if not date_field:
                self._log_query_generation(False, "Missing date field")
                return None
            
            # Build WHERE conditions with BigQuery optimizations
            where_conditions = self._build_bigquery_where_conditions(context, date_field)
            
            # Build the query with BigQuery-specific optimizations
            if where_conditions:
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
            else:
                query = f"""
SELECT 
    toString({campaign_name_field}) as {TABLE_COLUMNS['campaign_name']},
    toString({source_name_field}) as {TABLE_COLUMNS['source_name']},
    toFloat(coalesce({impressions_field}, 0)) as {TABLE_COLUMNS['impressions']},
    toFloat(coalesce({clicks_field}, 0)) as {TABLE_COLUMNS['clicks']},
    {cost_select} as {TABLE_COLUMNS['cost']}
FROM {table_name}
                """.strip()
            
            self._log_query_generation(True)
            return query
            
        except Exception as e:
            error_msg = f"Query generation error: {str(e)}"
            self._log_query_generation(False, error_msg)
            return None
    
    def _build_bigquery_cost_select(self, total_cost_field: str, currency_field: str, base_currency: str) -> str:
        """Build cost SELECT with BigQuery-specific handling"""
        if not total_cost_field:
            return "0"
        
        # Check if field name suggests micros (common in BigQuery marketing data)
        is_micros = 'micros' in total_cost_field.lower()
        
        if currency_field and total_cost_field:
            # Handle currency conversion with potential micros
            if is_micros:
                cost_select = f"toFloat(convertCurrency('{currency_field}', '{base_currency}', toFloat(coalesce({total_cost_field}, 0)) / 1000000))"
            else:
                cost_select = f"toFloat(convertCurrency('{currency_field}', '{base_currency}', toFloat(coalesce({total_cost_field}, 0))))"
        elif total_cost_field:
            # No currency conversion needed
            if is_micros:
                cost_select = f"toFloat(coalesce({total_cost_field}, 0)) / 1000000"
            else:
                cost_select = f"toFloat(coalesce({total_cost_field}, 0))"
        else:
            cost_select = "0"
        
        return cost_select
    
    def _build_bigquery_where_conditions(self, context: QueryContext, date_field: str) -> List[str]:
        """Build WHERE conditions optimized for BigQuery"""
        conditions = []
        
        # Add date range conditions with BigQuery-specific date handling
        if context.date_range:
            # BigQuery might have different date field formats
            if 'timestamp' in date_field.lower():
                # Handle timestamp fields
                date_cast = f"toDateTime({date_field})"
            elif 'date' in date_field.lower():
                # Handle date fields
                date_cast = f"toDateTime({date_field})"
            else:
                # Default handling
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
        """BigQuery requires access to BigQuery tables and potentially Google Cloud credentials"""
        return ['read_datawarehouse_tables', 'bigquery_access']
    
    def get_description(self) -> str:
        table_name = getattr(self.config.get('table'), 'name', 'unknown')
        return f"BigQuery marketing data table '{table_name}'" 