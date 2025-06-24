# Marketing Source Adapter Factory

from typing import List, Dict, Any, Optional, Type
import structlog

from .base import MarketingSourceAdapter, ValidationResult, QueryContext
from .google_ads import GoogleAdsAdapter
from .external_table import ExternalTableAdapter
from .meta_ads import MetaAdsAdapter
from ..constants import VALID_NATIVE_MARKETING_SOURCES

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
        'GoogleAds': GoogleAdsAdapter,
        'MetaAds': MetaAdsAdapter,
        'external_table': ExternalTableAdapter,
    }
    
    def __init__(self, team: Any):
        self.team = team
        self.logger = logger.bind(team_id=team.pk if team else None)
    
    @classmethod
    def register_adapter(cls, source_type: str, adapter_class: Type[MarketingSourceAdapter]):
        """Register a new adapter type for a marketing source"""
        cls._adapter_registry[source_type] = adapter_class
        logger.info("Registered marketing source adapter", source_type=source_type, adapter_class=adapter_class.__name__)
    
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
            
            # Create adapters for external tables
            external_adapters = self._create_external_table_adapters(datawarehouse_tables, sources_map)
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
    
    def _create_external_table_adapters(self, datawarehouse_tables, sources_map) -> List[MarketingSourceAdapter]:
        """Create adapters for external tables"""
        adapters = []
        
        for table in datawarehouse_tables:
            try:
                adapter = self._create_external_table_adapter(table, sources_map)
                if adapter:
                    adapters.append(adapter)
            except Exception as e:
                self.logger.error("Error creating external table adapter", 
                                 table_name=getattr(table, 'name', 'unknown'), 
                                 error=str(e))
        
        return adapters
    
    def _create_external_table_adapter(self, table, sources_map) -> Optional[ExternalTableAdapter]:
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
                'schema_name': schema_name  # Add schema_name to config
            }
            
            return ExternalTableAdapter(team=self.team, config=config)
            
        except Exception as e:
            self.logger.error("Error creating external table adapter", 
                             table_name=getattr(table, 'name', 'unknown'), 
                             error=str(e))
            return None
    
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
        from ..utils import get_marketing_config_value
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