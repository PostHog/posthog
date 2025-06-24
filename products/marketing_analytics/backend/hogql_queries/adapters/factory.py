# Marketing Source Adapter Factory

from typing import List, Dict, Any, Optional, Type
import structlog

from .base import MarketingSourceAdapter, QueryContext
from .google_ads import GoogleAdsAdapter

from .meta_ads import MetaAdsAdapter
from .bigquery import BigQueryAdapter
from .self_managed import (
    SelfManagedAdapter, AWSAdapter, GoogleCloudAdapter, 
    CloudflareR2Adapter, AzureAdapter
)
from ..constants import VALID_NATIVE_MARKETING_SOURCES, VALID_NON_NATIVE_MARKETING_SOURCES, VALID_SELF_MANAGED_MARKETING_SOURCES
from ..utils import get_marketing_config_value, map_url_to_provider

logger = structlog.get_logger(__name__)


class MarketingSourceFactory:
    """
    Factory for creating and managing marketing source adapters.
    Responsible for:
    1. Discovering available data sources
    2. Creating appropriate adapters for each source
    3. Validating sources can provide marketing data
    """
    
    # Registry of adapter classes
    _adapter_registry: Dict[str, Type[MarketingSourceAdapter]] = {
        # Native adapters
        'GoogleAds': GoogleAdsAdapter,
        'MetaAds': MetaAdsAdapter,
        # Non-native adapters
        'BigQuery': BigQueryAdapter,
        # Self-managed adapters
        'aws': AWSAdapter,
        'google-cloud': GoogleCloudAdapter,
        'cloudflare-r2': CloudflareR2Adapter,
        'azure': AzureAdapter,
    }
    
    def __init__(self, team: Any):
        self.team = team
        self.logger = logger.bind(team_id=team.pk if team else None)
    
    @classmethod
    def register_adapter(cls, source_type: str, adapter_class: Type[MarketingSourceAdapter]):
        """Register a new adapter type for a marketing source"""
        cls._adapter_registry[source_type] = adapter_class
        logger.info("Registered marketing source adapter", source_type=source_type, adapter_class=adapter_class.__name__)
    
    @classmethod
    def register_self_managed_adapter(cls, platform_type: str, adapter_class: Type[MarketingSourceAdapter]):
        """Convenience method to register a new self-managed platform adapter"""
        cls.register_adapter(platform_type, adapter_class)
        # Also add to the valid self-managed sources if not already there
        from ..constants import VALID_SELF_MANAGED_MARKETING_SOURCES
        if platform_type not in VALID_SELF_MANAGED_MARKETING_SOURCES:
            VALID_SELF_MANAGED_MARKETING_SOURCES.append(platform_type)
            logger.info("Added new self-managed platform", platform_type=platform_type)
    
    def create_adapters(self) -> List[MarketingSourceAdapter]:
        """
        Discover all available marketing sources and create adapters for them.
        This replaces the existing _get_data_warehouse_sources method logic.
        """
        adapters = []
        
        try:
            # Get warehouse data (replicating existing discovery logic)
            warehouse_table_names = self._get_warehouse_table_names()
            datawarehouse_tables = self._get_filtered_warehouse_tables(warehouse_table_names)
            sources_map = self._get_team_sources_map()
            
            # Create adapters for native sources (e.g., Google Ads)
            native_adapters = self._create_native_source_adapters(datawarehouse_tables)
            adapters.extend(native_adapters)
            
            # Create adapters for non-native sources (e.g., BigQuery)
            non_native_adapters = self._create_non_native_source_adapters(datawarehouse_tables, sources_map)
            adapters.extend(non_native_adapters)
            
            # Create adapters for external tables (e.g., AWS, Google Cloud, Cloudflare R2, Azure)
            external_adapters = self._create_self_managed_source_adapters(datawarehouse_tables, sources_map)
            adapters.extend(external_adapters)
            
            self.logger.info(f"Created {len(adapters)} marketing source adapters")
            return adapters
            
        except Exception as e:
            self.logger.error("Error creating marketing source adapters", error=str(e))
            return []
    
    def _create_native_source_adapters(self, datawarehouse_tables) -> List[MarketingSourceAdapter]:
        """Create adapters for native marketing sources (e.g., Google Ads)"""
        adapters = []
        
        try:
            from posthog.warehouse.models import ExternalDataSource
            
            external_data_sources = ExternalDataSource.objects.filter(team_id=self.team.pk)
            
            for source in external_data_sources:
                if source.source_type in VALID_NATIVE_MARKETING_SOURCES:
                    associated_tables = datawarehouse_tables.filter(external_data_source=source)
                    
                    if associated_tables.exists():
                        adapter = self._create_native_source_adapter(source, list(associated_tables))
                        if adapter:
                            adapters.append(adapter)
            
        except Exception as e:
            self.logger.error("Error creating native source adapters", error=str(e))
        
        return adapters
    
    def _create_native_source_adapter(self, source, tables) -> Optional[MarketingSourceAdapter]:
        """Create adapter for a specific native source"""
        try:
            if source.source_type == 'GoogleAds':
                return self._create_google_ads_adapter(source, tables)
            elif source.source_type == 'MetaAds':
                return self._create_meta_ads_adapter(source, tables)
            
            self.logger.warning(f"No adapter available for native source type: {source.source_type}")
            return None
            
        except Exception as e:
            self.logger.error("Error creating native source adapter", source_type=source.source_type, error=str(e))
            return None
    
    def _create_google_ads_adapter(self, source, tables) -> Optional[GoogleAdsAdapter]:
        """Create Google Ads adapter with campaign and stats tables"""
        try:
            # Find required tables (replicating existing logic)
            campaign_table = None
            campaign_stats_table = None
            
            for table in tables:
                table_name_parts = getattr(table, 'name', '').split('.')
                table_suffix = table_name_parts[-1] if table_name_parts else ''
                
                if 'campaign' in table_suffix.lower() and 'stats' not in table_suffix.lower():
                    campaign_table = table
                elif 'campaign_stats' in table_suffix.lower():
                    campaign_stats_table = table
            
            if not campaign_table or not campaign_stats_table:
                self.logger.warning("Google Ads source missing required tables", 
                                   has_campaign=bool(campaign_table), 
                                   has_stats=bool(campaign_stats_table))
                return None
            
            config = {
                'campaign_table': campaign_table,
                'stats_table': campaign_stats_table,
                'source_id': source.id
            }
            
            return GoogleAdsAdapter(team=self.team, config=config)
            
        except Exception as e:
            self.logger.error("Error creating Google Ads adapter", error=str(e))
            return None
    
    def _create_meta_ads_adapter(self, source, tables) -> Optional[MetaAdsAdapter]:
        """Create Meta Ads adapter - example of single table structure"""
        try:
            # Meta Ads typically uses a single table structure
            # Find the main campaign table
            meta_table = None
            
            for table in tables:
                table_name = getattr(table, 'name', '').lower()
                if 'campaign' in table_name or 'ads' in table_name:
                    meta_table = table
                    break
            
            if not meta_table:
                self.logger.warning("Meta Ads source missing campaign table")
                return None
            
            config = {
                'table': meta_table,
                'source_id': source.id
            }
            
            return MetaAdsAdapter(team=self.team, config=config)
            
        except Exception as e:
            self.logger.error("Error creating Meta Ads adapter", error=str(e))
            return None
    
    def _create_self_managed_source_adapters(self, datawarehouse_tables, sources_map) -> List[MarketingSourceAdapter]:
        """Create adapters for self-managed external tables (exclude tables already handled by native/non-native flows)"""
        adapters = []
        
        # Filter out tables that have external_data_source with source_type in VALID_NATIVE_MARKETING_SOURCES or VALID_NON_NATIVE_MARKETING_SOURCES
        # These tables are already handled by the native and non-native flows
        self_managed_tables = []
        excluded_count = 0
        
        for table in datawarehouse_tables:
            if table.external_data_source:
                source_type = table.external_data_source.source_type
                if source_type in VALID_NATIVE_MARKETING_SOURCES or source_type in VALID_NON_NATIVE_MARKETING_SOURCES:
                    excluded_count += 1
                    continue
            self_managed_tables.append(table)
        
        for table in self_managed_tables:
            try:
                adapter = self._create_external_table_adapter(table, sources_map)
                if adapter:
                    adapters.append(adapter)
            except Exception as e:
                self.logger.error("Error creating external table adapter", 
                                 table_name=getattr(table, 'name', 'unknown'), 
                                 error=str(e))
        return adapters
    
    def _create_external_table_adapter(self, table, sources_map) -> Optional[MarketingSourceAdapter]:
        """Create adapter for a specific external table"""
        try:
            # Get source map and type (replicating existing logic)
            source_map, source_type = self._get_table_source_config(table, sources_map)
            
            if not source_map:
                return None
            
            # Determine schema name for the table
            schema_name = self._get_table_schema_name(table)
            
            config = {
                'table': table,
                'source_map': source_map,
                'source_type': source_type,
                'schema_name': schema_name
            }
            
            # Use specific self-managed adapter if it's a self-managed source
            if source_type == 'self_managed':
                return self._create_self_managed_adapter(config)
            else:
                # No fallback - only support explicitly configured adapters
                self.logger.warning(f"No adapter available for external source type: {source_type}")
                return None
            
        except Exception as e:
            self.logger.error("Error creating external table adapter", 
                             table_name=getattr(table, 'name', 'unknown'), 
                             error=str(e))
            return None
    
    def _create_self_managed_adapter(self, config: Dict[str, Any]) -> Optional[MarketingSourceAdapter]:
        """Create appropriate self-managed adapter based on platform detection"""
        try:
            table = config.get('table')
            table_name = getattr(table, 'name', '').lower()
            
            # Try to detect platform from table metadata or configuration
            # For now, we'll detect based on naming patterns or add metadata later
            platform_type = self._detect_self_managed_platform(table)
            
            # Get the appropriate adapter class
            adapter_class = self._adapter_registry.get(platform_type)
            if adapter_class:
                self.logger.info(f"Creating {platform_type} adapter for self-managed table: {table_name}")
                return adapter_class(team=self.team, config=config)
            else:
                # Fallback to generic self-managed adapter
                self.logger.warning(f"No specific adapter for platform {platform_type}, using generic self-managed adapter")
                return SelfManagedAdapter(team=self.team, config=config)
                
        except Exception as e:
            self.logger.error("Error creating self-managed adapter", error=str(e))
            return None
    
    def _detect_self_managed_platform(self, table) -> str:
        """Detect the platform type for self-managed tables based on URL pattern"""
        try:
            # Use the same logic as frontend mapUrlToProvider function
            # from DataWarehouseSourceIcon.tsx
            url_pattern = getattr(table, 'url_pattern', '')
            
            if not url_pattern:
                self.logger.warning("No url_pattern found for self-managed table", table_name=getattr(table, 'name', 'unknown'))
                return 'aws'  # Safe default
            
            # Use the utility function that mirrors frontend logic
            platform = map_url_to_provider(url_pattern)
            
            # Handle unknown platform (BlushingHog in frontend)
            if platform == 'BlushingHog':
                self.logger.info(f"Unknown URL pattern, defaulting to AWS", url_pattern=url_pattern, table_name=getattr(table, 'name', 'unknown'))
                return 'aws'
            
            self.logger.info(f"Detected platform from URL pattern", platform=platform, url_pattern=url_pattern, table_name=getattr(table, 'name', 'unknown'))
            return platform
            
        except Exception as e:
            self.logger.error("Error detecting self-managed platform from URL pattern", error=str(e))
            return 'aws'  # Safe default
    
    def _get_table_source_config(self, table, sources_map) -> tuple[Optional[Dict], str]:
        """Get source map and type for a table (replicating existing logic)"""
        try:
            if table.external_data_source:
                # Managed external table
                external_source = table.external_data_source
                table_id = str(table.id)
                source_id = str(external_source.id)
                schema_id = self._get_schema_id_for_table(table)
                
                # Frontend logic: table.schema?.id || table.source?.id || table.id
                source_map_id = schema_id or source_id or table_id
                
                # Find appropriate source map
                source_map = self._find_source_map_for_managed_table(
                    sources_map, schema_id, source_id, table_id
                )
                
                return source_map, external_source.source_type
            else:
                # Self-managed table
                table_id = str(table.id)
                source_map = sources_map.get(table_id, None)
                
                return source_map, 'self_managed'
                
        except Exception as e:
            self.logger.error("Error getting table source config", error=str(e))
            return None, 'unknown'
    
    def get_valid_adapters(self, adapters: List[MarketingSourceAdapter]) -> List[MarketingSourceAdapter]:
        """Filter adapters to only return valid ones"""
        valid_adapters = []
        
        for adapter in adapters:
            try:
                validation_result = adapter.validate()
                if validation_result.is_valid:
                    valid_adapters.append(adapter)
                else:
                    self.logger.warning("Adapter validation failed", 
                                       source_type=adapter.get_source_type(),
                                       errors=validation_result.errors)
            except Exception as e:
                self.logger.error("Error validating adapter", 
                                 source_type=adapter.get_source_type(),
                                 error=str(e))
        
        return valid_adapters
    
    def build_union_query(self, adapters: List[MarketingSourceAdapter], context: QueryContext) -> str:
        """Build union query from all valid adapters"""
        queries = []
        
        for adapter in adapters:
            try:
                query = adapter.build_query(context)
                if query:
                    queries.append(query)
            except Exception as e:
                self.logger.error("Error building query for adapter", 
                                 source_type=adapter.get_source_type(),
                                 error=str(e))
        
        if not queries:
            self.logger.warning("No valid queries generated from adapters")
            return "SELECT 'No Campaign' as campaign_name, 'No Source' as source_name, 0.0 as impressions, 0.0 as clicks, 0.0 as cost WHERE 1=0"
        
        return '\nUNION ALL\n'.join(queries)
    
    # Helper methods that replicate existing data warehouse discovery logic
    
    def _get_warehouse_table_names(self):
        """Get warehouse table names from HogQL database"""
        from posthog.hogql.database.database import create_hogql_database
        database = create_hogql_database(team=self.team)
        return database.get_warehouse_tables()

    def _get_filtered_warehouse_tables(self, warehouse_table_names):
        """Get filtered DataWarehouseTable objects"""
        from posthog.warehouse.models import DataWarehouseTable
        return DataWarehouseTable.objects.filter(
            team_id=self.team.pk,
            deleted=False,
            name__in=warehouse_table_names
        )

    def _get_team_sources_map(self):
        """Get sources map from team marketing analytics config"""
        from posthog.models import Team
        team = Team.objects.get(pk=self.team.pk)
        marketing_config = getattr(team, 'marketing_analytics_config', None)
        return get_marketing_config_value(marketing_config, 'sources_map', {})

    def _get_schema_id_for_table(self, table):
        """Get schema ID for a warehouse table"""
        try:
            from posthog.warehouse.models import ExternalDataSchema
            schema = ExternalDataSchema.objects.filter(table_id=table.id).first()
            return str(schema.id) if schema else None
        except Exception:
            return None

    def _find_source_map_for_managed_table(self, sources_map, schema_id, source_id, table_id):
        """Find appropriate source map for managed external table"""
        if schema_id and schema_id in sources_map:
            return sources_map[schema_id]
        elif table_id in sources_map:
            return sources_map[table_id]
        elif source_id in sources_map:
            return sources_map[source_id]
        return None
    
    def _get_table_schema_name(self, table) -> str:
        """Get schema name for a table (replicating original logic)"""
        try:
            # For managed tables with external data source, try to get schema name
            if table.external_data_source:
                # Try to get the schema from external data schema
                schema_id = self._get_schema_id_for_table(table)
                if schema_id:
                    try:
                        from posthog.warehouse.models import ExternalDataSchema
                        schema = ExternalDataSchema.objects.filter(id=schema_id).first()
                        if schema and hasattr(schema, 'name'):
                            return schema.name
                    except Exception:
                        pass
                
                # Fallback to table name for managed tables
                return table.name
            else:
                # For self-managed tables, use table name as schema name
                return table.name
                
        except Exception as e:
            self.logger.error("Error getting table schema name", table_name=getattr(table, 'name', 'unknown'), error=str(e))
            return getattr(table, 'name', 'unknown')
    
    def _create_non_native_source_adapters(self, datawarehouse_tables, sources_map) -> List[MarketingSourceAdapter]:
        """Create adapters for non-native marketing sources (e.g., BigQuery)"""
        adapters = []
        
        try:
            from posthog.warehouse.models import ExternalDataSource
            
            external_data_sources = ExternalDataSource.objects.filter(team_id=self.team.pk)
            
            for source in external_data_sources:
                if source.source_type in VALID_NON_NATIVE_MARKETING_SOURCES:
                    associated_tables = datawarehouse_tables.filter(external_data_source=source)
                    
                    if associated_tables.exists():
                        result = self._create_non_native_source_adapter(source, list(associated_tables), sources_map)
                        if result:
                            # Handle both single adapter and list of adapters
                            if isinstance(result, list):
                                adapters.extend(result)
                            else:
                                adapters.append(result)
            
        except Exception as e:
            self.logger.error("Error creating non-native source adapters", error=str(e))
        
        return adapters
    
    def _create_non_native_source_adapter(self, source, tables, sources_map) -> Optional[List[MarketingSourceAdapter]]:
        """Create adapters for a specific non-native source (can return multiple adapters for BigQuery)"""
        try:
            if source.source_type == 'BigQuery':
                return self._create_bigquery_adapters(source, tables, sources_map)
            
            self.logger.warning(f"No adapter available for non-native source type: {source.source_type}")
            return None
            
        except Exception as e:
            self.logger.error("Error creating non-native source adapter", source_type=source.source_type, error=str(e))
            return None
    
    def _create_bigquery_adapters(self, source, tables, sources_map) -> Optional[List[BigQueryAdapter]]:
        """Create BigQuery adapters - one per table that has a source map"""
        try:
            adapters = []
            
            for table in tables:
                # For BigQuery, check if this table has a source map configured
                table_id = str(table.id)
                schema_id = self._get_schema_id_for_table(table)
                source_id = str(source.id)
                
                # Check if there's a source map for this table
                source_map = self._find_source_map_for_managed_table(
                    sources_map, schema_id, source_id, table_id
                )
                
                if source_map:
                    schema_name = self._get_table_schema_name(table)
                    
                    config = {
                        'table': table,
                        'source_map': source_map,
                        'source_type': 'BigQuery',
                        'source_id': source.id,
                        'schema_name': schema_name
                    }
                    
                    adapter = BigQueryAdapter(team=self.team, config=config)
                    adapters.append(adapter)
                    self.logger.info(f"JFBW: Created BigQuery adapter for table {table.name}")
                else:
                    self.logger.info(f"JFBW: No source map found for BigQuery table {table.name}")
            
            if not adapters:
                self.logger.warning("BigQuery source has no configured tables with source maps")
                return None
            
            self.logger.info(f"JFBW: Created {len(adapters)} BigQuery adapters for source {source.id}")
            return adapters
            
        except Exception as e:
            self.logger.error("Error creating BigQuery adapters", error=str(e))
            return None 