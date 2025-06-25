# Marketing Source Adapter Factory

from typing import Any, Optional
import structlog

from .base import MarketingSourceAdapter, QueryContext
from .google_ads import GoogleAdsAdapter

from .bigquery import BigQueryAdapter
from .self_managed import AWSAdapter, GoogleCloudAdapter, CloudflareR2Adapter, AzureAdapter
from ..constants import (
    VALID_NATIVE_MARKETING_SOURCES,
    VALID_NON_NATIVE_MARKETING_SOURCES,
    VALID_SELF_MANAGED_MARKETING_SOURCES,
    FALLBACK_EMPTY_QUERY,
    UNKNOWN_TABLE_NAME,
    TABLE_PATTERNS,
)
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
    _adapter_registry: dict[str, type[MarketingSourceAdapter]] = {
        # Native adapters
        "GoogleAds": GoogleAdsAdapter,
        # Non-native adapters
        "BigQuery": BigQueryAdapter,
        # Self-managed adapters
        "aws": AWSAdapter,
        "google-cloud": GoogleCloudAdapter,
        "cloudflare-r2": CloudflareR2Adapter,
        "azure": AzureAdapter,
    }

    def __init__(self, team: Any):
        self.team = team
        self.logger = logger.bind(team_id=team.pk if team else None)

    @classmethod
    def register_adapter(cls, source_type: str, adapter_class: type[MarketingSourceAdapter]):
        """Register a new adapter type for a marketing source"""
        cls._adapter_registry[source_type] = adapter_class

    @classmethod
    def register_self_managed_adapter(cls, platform_type: str, adapter_class: type[MarketingSourceAdapter]):
        """Convenience method to register a new self-managed platform adapter"""
        cls.register_adapter(platform_type, adapter_class)
        # Also add to the valid self-managed sources if not already there
        if platform_type not in VALID_SELF_MANAGED_MARKETING_SOURCES:
            VALID_SELF_MANAGED_MARKETING_SOURCES.append(platform_type)

    def create_adapters(self) -> list[MarketingSourceAdapter]:
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

            return adapters

        except Exception as e:
            self.logger.exception("Error creating marketing source adapters", error=str(e))
            return []

    def _create_native_source_adapters(self, datawarehouse_tables) -> list[MarketingSourceAdapter]:
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
            self.logger.exception("Error creating native source adapters", error=str(e))

        return adapters

    def _create_native_source_adapter(self, source, tables) -> Optional[MarketingSourceAdapter]:
        """Create adapter for a specific native source using registry pattern"""
        try:
            # Use registry pattern instead of hardcoded if/elif chains
            adapter_class = self._adapter_registry.get(source.source_type)
            if not adapter_class:
                return None

            # Call source-specific config creation method
            config = self._create_native_adapter_config(source, tables)
            if not config:
                return None

            return adapter_class(team=self.team, config=config)

        except Exception as e:
            self.logger.exception("Error creating native source adapter", source_type=source.source_type, error=str(e))
            return None

    def _create_native_adapter_config(self, source, tables) -> Optional[dict[str, Any]]:
        """Create config for native adapters based on source type using registry pattern"""
        try:
            # Use registry pattern for config builders too
            config_method_name = f"_create_{source.source_type.lower()}_config"
            config_method = getattr(self, config_method_name, None)

            if config_method:
                return config_method(source, tables)
            return None

        except Exception as e:
            self.logger.exception("Error creating native adapter config", source_type=source.source_type, error=str(e))
            return None

    def _create_googleads_config(self, source, tables) -> Optional[dict[str, Any]]:
        """Create Google Ads adapter config with campaign and stats tables"""
        try:
            # Find required tables using pattern matching
            campaign_table = None
            campaign_stats_table = None

            patterns = TABLE_PATTERNS["GoogleAds"]

            for table in tables:
                table_name_parts = getattr(table, "name", "").split(".")
                table_suffix = table_name_parts[-1] if table_name_parts else ""
                table_suffix_lower = table_suffix.lower()

                # Check for campaign table (has campaign keywords but not exclusions)
                if any(keyword in table_suffix_lower for keyword in patterns["campaign_table_keywords"]) and not any(
                    exclusion in table_suffix_lower for exclusion in patterns["campaign_table_exclusions"]
                ):
                    campaign_table = table
                # Check for stats table
                elif any(keyword in table_suffix_lower for keyword in patterns["stats_table_keywords"]):
                    campaign_stats_table = table

            if not campaign_table or not campaign_stats_table:
                return None

            return {"campaign_table": campaign_table, "stats_table": campaign_stats_table, "source_id": source.id}

        except Exception as e:
            self.logger.exception("Error creating Google Ads config", error=str(e))
            return None

    def _create_self_managed_source_adapters(self, datawarehouse_tables, sources_map) -> list[MarketingSourceAdapter]:
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
                self.logger.exception(
                    "Error creating external table adapter",
                    table_name=getattr(table, "name", UNKNOWN_TABLE_NAME),
                    error=str(e),
                )
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

            config = {"table": table, "source_map": source_map, "source_type": source_type, "schema_name": schema_name}

            # Use specific self-managed adapter if it's a self-managed source
            if source_type == "self_managed":
                return self._create_self_managed_adapter(config)
            return None

        except Exception as e:
            self.logger.exception(
                "Error creating external table adapter",
                table_name=getattr(table, "name", UNKNOWN_TABLE_NAME),
                error=str(e),
            )
            return None

    def _create_self_managed_adapter(self, config: dict[str, Any]) -> Optional[MarketingSourceAdapter]:
        """Create appropriate self-managed adapter based on platform detection"""
        try:
            table = config.get("table")

            # Try to detect platform from table metadata or configuration
            # For now, we'll detect based on naming patterns or add metadata later
            platform_type = self._detect_self_managed_platform(table)
            if not platform_type:
                return None

            # Get the appropriate adapter class
            adapter_class = self._adapter_registry.get(platform_type)
            if adapter_class:
                return adapter_class(team=self.team, config=config)
            return None

        except Exception as e:
            self.logger.exception("Error creating self-managed adapter", error=str(e))
            return None

    def _detect_self_managed_platform(self, table) -> Optional[str]:
        """Detect the platform type for self-managed tables based on URL pattern"""
        try:
            # Use the same logic as frontend mapUrlToProvider function
            # from DataWarehouseSourceIcon.tsx
            url_pattern = getattr(table, "url_pattern", "")

            if not url_pattern:
                return None

            # Use the utility function that mirrors frontend logic
            platform = map_url_to_provider(url_pattern)

            return platform

        except Exception as e:
            self.logger.exception("Error detecting self-managed platform from URL pattern", error=str(e))
            return None

    def _get_table_source_config(self, table, sources_map) -> tuple[Optional[dict], str]:
        """Get source map and type for a table (replicating existing logic)"""
        try:
            if table.external_data_source:
                # Managed external table
                external_source = table.external_data_source
                table_id = str(table.id)
                source_id = str(external_source.id)
                schema_id = self._get_schema_id_for_table(table)

                # Find appropriate source map
                source_map = self._find_source_map_for_managed_table(sources_map, schema_id, source_id, table_id)

                return source_map, external_source.source_type
            else:
                # Self-managed table
                table_id = str(table.id)
                source_map = sources_map.get(table_id, None)

                return source_map, "self_managed"

        except Exception as e:
            self.logger.exception("Error getting table source config", error=str(e))
            return None, UNKNOWN_TABLE_NAME

    def get_valid_adapters(self, adapters: list[MarketingSourceAdapter]) -> list[MarketingSourceAdapter]:
        """Filter adapters to only return valid ones"""
        valid_adapters = []

        for adapter in adapters:
            try:
                validation_result = adapter.validate()
                if validation_result.is_valid:
                    valid_adapters.append(adapter)
            except Exception as e:
                self.logger.exception("Error validating adapter", source_type=adapter.get_source_type(), error=str(e))

        return valid_adapters

    def build_union_query(self, adapters: list[MarketingSourceAdapter], context: QueryContext) -> str:
        """Build union query from all valid adapters"""
        queries = []

        for adapter in adapters:
            try:
                query = adapter.build_query(context)
                if query:
                    queries.append(query)
            except Exception as e:
                self.logger.exception(
                    "Error building query for adapter", source_type=adapter.get_source_type(), error=str(e)
                )

        if not queries:
            return FALLBACK_EMPTY_QUERY

        return "\nUNION ALL\n".join(queries)

    # Helper methods that replicate existing data warehouse discovery logic

    def _get_warehouse_table_names(self):
        """Get warehouse table names from HogQL database"""
        from posthog.hogql.database.database import create_hogql_database

        database = create_hogql_database(team=self.team)
        return database.get_warehouse_tables()

    def _get_filtered_warehouse_tables(self, warehouse_table_names):
        """Get filtered DataWarehouseTable objects"""
        from posthog.warehouse.models import DataWarehouseTable

        return DataWarehouseTable.objects.filter(team_id=self.team.pk, deleted=False, name__in=warehouse_table_names)

    def _get_team_sources_map(self):
        """Get sources map from team marketing analytics config"""
        from posthog.models import Team

        team = Team.objects.get(pk=self.team.pk)
        marketing_config = getattr(team, "marketing_analytics_config", None)
        return get_marketing_config_value(marketing_config, "sources_map", {})

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
                        if schema and hasattr(schema, "name"):
                            return schema.name
                    except Exception:
                        pass

                # Fallback to table name for managed tables
                return table.name
            else:
                # For self-managed tables, use table name as schema name
                return table.name

        except Exception as e:
            self.logger.exception(
                "Error getting table schema name", table_name=getattr(table, "name", UNKNOWN_TABLE_NAME), error=str(e)
            )
            return getattr(table, "name", UNKNOWN_TABLE_NAME)

    def _create_non_native_source_adapters(self, datawarehouse_tables, sources_map) -> list[MarketingSourceAdapter]:
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
            self.logger.exception("Error creating non-native source adapters", error=str(e))

        return adapters

    def _create_non_native_source_adapter(self, source, tables, sources_map) -> Optional[list[MarketingSourceAdapter]]:
        """Create adapters for a specific non-native source (can return multiple adapters for BigQuery)"""
        try:
            if source.source_type == "BigQuery":
                return self._create_bigquery_adapters(source, tables, sources_map)

            return None

        except Exception as e:
            self.logger.exception(
                "Error creating non-native source adapter", source_type=source.source_type, error=str(e)
            )
            return None

    def _create_bigquery_adapters(self, source, tables, sources_map) -> Optional[list[BigQueryAdapter]]:
        """Create BigQuery adapters - one per table that has a source map"""
        try:
            adapters = []

            for table in tables:
                # For BigQuery, check if this table has a source map configured
                table_id = str(table.id)
                schema_id = self._get_schema_id_for_table(table)
                source_id = str(source.id)

                # Check if there's a source map for this table
                source_map = self._find_source_map_for_managed_table(sources_map, schema_id, source_id, table_id)

                if source_map:
                    schema_name = self._get_table_schema_name(table)

                    config = {
                        "table": table,
                        "source_map": source_map,
                        "source_type": "BigQuery",
                        "source_id": source.id,
                        "schema_name": schema_name,
                    }

                    adapter = BigQueryAdapter(team=self.team, config=config)
                    adapters.append(adapter)

            if not adapters:
                return None

            return adapters

        except Exception as e:
            self.logger.exception("Error creating BigQuery adapters", error=str(e))
            return None
