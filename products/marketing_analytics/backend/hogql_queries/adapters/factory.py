# Marketing Source Adapter Factory

from typing import Optional

import structlog

from posthog.schema import SourceMap

from posthog.hogql.database.database import Database

from products.data_warehouse.backend.models import DataWarehouseTable, ExternalDataSource
from products.marketing_analytics.backend.hogql_queries.adapters.linkedin_ads import LinkedinAdsAdapter
from products.marketing_analytics.backend.hogql_queries.adapters.meta_ads import MetaAdsAdapter
from products.marketing_analytics.backend.hogql_queries.adapters.reddit_ads import RedditAdsAdapter
from products.marketing_analytics.backend.hogql_queries.adapters.tiktok_ads import TikTokAdsAdapter

from ..constants import (
    FALLBACK_EMPTY_QUERY,
    TABLE_PATTERNS,
    VALID_NATIVE_MARKETING_SOURCES,
    VALID_NON_NATIVE_MARKETING_SOURCES,
)
from ..utils import map_url_to_provider
from .base import (
    ExternalConfig,
    GoogleAdsConfig,
    LinkedinAdsConfig,
    MarketingSourceAdapter,
    MetaAdsConfig,
    QueryContext,
    RedditAdsConfig,
    TikTokAdsConfig,
)
from .bigquery import BigQueryAdapter
from .google_ads import GoogleAdsAdapter
from .self_managed import AWSAdapter, AzureAdapter, CloudflareR2Adapter, GoogleCloudAdapter

logger = structlog.get_logger(__name__)


class MarketingSourceFactory:
    """Factory for creating and managing marketing source adapters."""

    # Registry of adapter classes
    _adapter_registry: dict[str, type[MarketingSourceAdapter]] = {
        # Native adapters
        "GoogleAds": GoogleAdsAdapter,
        "LinkedinAds": LinkedinAdsAdapter,
        "RedditAds": RedditAdsAdapter,
        "MetaAds": MetaAdsAdapter,
        "TikTokAds": TikTokAdsAdapter,
        # Non-native adapters
        "BigQuery": BigQueryAdapter,
        # Self-managed adapters
        "aws": AWSAdapter,
        "google-cloud": GoogleCloudAdapter,
        "cloudflare-r2": CloudflareR2Adapter,
        "azure": AzureAdapter,
    }

    # Config builders for native sources
    _config_builders = {
        "GoogleAds": "_create_googleads_config",
        "LinkedinAds": "_create_linkedinads_config",
        "RedditAds": "_create_redditads_config",
        "MetaAds": "_create_metaads_config",
        "TikTokAds": "_create_tiktokads_config",
    }

    @classmethod
    def get_all_source_identifier_mappings(cls) -> dict[str, list[str]]:
        """
        Collect source identifier mappings from all registered adapters.
        Returns a combined dictionary of {primary_source: [all_utm_sources]}.
        """
        combined_mappings: dict[str, list[str]] = {}
        for adapter_class in cls._adapter_registry.values():
            mapping = adapter_class.get_source_identifier_mapping()
            if mapping:
                combined_mappings.update(mapping)
        return combined_mappings

    def __init__(self, context: QueryContext):
        self.context = context
        self.logger = logger.bind(team_id=self.context.team.pk if self.context.team else None)

        # Cache warehouse data to avoid repeated queries
        database = Database.create_for(team=self.context.team)
        self._warehouse_tables = DataWarehouseTable.objects.filter(
            team_id=self.context.team.pk, deleted=False, name__in=database.get_warehouse_table_names()
        ).prefetch_related("externaldataschema_set")
        self._sources_map = self.context.team.marketing_analytics_config.sources_map_typed

    @classmethod
    def register_adapter(cls, source_type: str, adapter_class: type[MarketingSourceAdapter]):
        """Register a new adapter type for a marketing source"""
        cls._adapter_registry[source_type] = adapter_class

    def create_adapters(self) -> list[MarketingSourceAdapter]:
        """Discover all available marketing sources and create adapters for them."""
        try:
            adapters = []
            adapters.extend(self._create_native_adapters())
            adapters.extend(self._create_external_adapters())
            adapters.extend(self._create_self_managed_adapters())

            return adapters

        except Exception as e:
            self.logger.exception("Error creating marketing source adapters", error=str(e))
            return []

    def _create_native_adapters(self) -> list[MarketingSourceAdapter]:
        """Create adapters for native marketing sources"""

        adapters = []
        external_sources = ExternalDataSource.objects.filter(team_id=self.context.team.pk)

        for source in external_sources:
            if source.source_type not in VALID_NATIVE_MARKETING_SOURCES:
                continue

            tables = list(self._warehouse_tables.filter(external_data_source=source))
            if not tables:
                continue

            adapter_class = self._adapter_registry.get(source.source_type)
            if not adapter_class:
                continue
            config_method_name = self._config_builders.get(source.source_type)
            if not config_method_name:
                continue
            config_method = getattr(self, config_method_name, None)
            if not config_method:
                continue
            config = config_method(source, tables)
            adapters.append(adapter_class(config=config, context=self.context))

        return adapters

    def _create_googleads_config(
        self, source: ExternalDataSource, tables: list[DataWarehouseTable]
    ) -> Optional[GoogleAdsConfig]:
        """Create Google Ads adapter config with campaign and stats tables"""
        patterns = TABLE_PATTERNS["GoogleAds"]
        campaign_table = None
        campaign_stats_table = None

        for table in tables:
            table_suffix = table.name.split(".")[-1].lower()

            # Check for campaign table
            if any(kw in table_suffix for kw in patterns["campaign_table_keywords"]) and not any(
                ex in table_suffix for ex in patterns["campaign_table_exclusions"]
            ):
                campaign_table = table
            # Check for stats table
            elif any(kw in table_suffix for kw in patterns["stats_table_keywords"]):
                campaign_stats_table = table

        if not (campaign_table and campaign_stats_table):
            return None

        config = GoogleAdsConfig(
            source_type=source.source_type,
            campaign_table=campaign_table,
            stats_table=campaign_stats_table,
            source_id=str(source.id),
        )

        return config

    def _create_linkedinads_config(
        self, source: ExternalDataSource, tables: list[DataWarehouseTable]
    ) -> Optional[LinkedinAdsConfig]:
        """Create LinkedIn Ads adapter config with campaign and stats tables"""
        patterns = TABLE_PATTERNS["LinkedinAds"]
        campaign_table = None
        campaign_stats_table = None

        for table in tables:
            table_suffix = table.name.split(".")[-1].lower()

            # Check for campaign table
            if any(kw in table_suffix for kw in patterns["campaign_table_keywords"]) and not any(
                ex in table_suffix for ex in patterns["campaign_table_exclusions"]
            ):
                campaign_table = table
            # Check for stats table
            elif any(kw in table_suffix for kw in patterns["stats_table_keywords"]):
                campaign_stats_table = table

        if not (campaign_table and campaign_stats_table):
            return None

        config = LinkedinAdsConfig(
            source_type=source.source_type,
            campaign_table=campaign_table,
            stats_table=campaign_stats_table,
            source_id=str(source.id),
        )

        return config

    def _create_redditads_config(
        self, source: ExternalDataSource, tables: list[DataWarehouseTable]
    ) -> Optional[RedditAdsConfig]:
        """Create Reddit Ads adapter config with campaign and stats tables"""
        patterns = TABLE_PATTERNS["RedditAds"]
        campaign_table = None
        campaign_stats_table = None

        for table in tables:
            table_suffix = table.name.split(".")[-1].lower()

            # Check for campaign table
            if any(kw in table_suffix for kw in patterns["campaign_table_keywords"]) and not any(
                ex in table_suffix for ex in patterns["campaign_table_exclusions"]
            ):
                campaign_table = table
            # Check for stats table
            elif any(kw in table_suffix for kw in patterns["stats_table_keywords"]):
                campaign_stats_table = table

        if not (campaign_table and campaign_stats_table):
            return None

        config = RedditAdsConfig(
            source_type=source.source_type,
            campaign_table=campaign_table,
            stats_table=campaign_stats_table,
            source_id=str(source.id),
        )

        return config

    def _create_metaads_config(
        self, source: ExternalDataSource, tables: list[DataWarehouseTable]
    ) -> Optional[MetaAdsConfig]:
        """Create Meta Ads adapter config with campaign and stats tables"""
        patterns = TABLE_PATTERNS["MetaAds"]
        campaign_table = None
        campaign_stats_table = None

        for table in tables:
            table_suffix = table.name.split(".")[-1].lower()

            # Check for campaign table
            if any(kw in table_suffix for kw in patterns["campaign_table_keywords"]) and not any(
                ex in table_suffix for ex in patterns["campaign_table_exclusions"]
            ):
                campaign_table = table
            # Check for stats table
            elif any(kw in table_suffix for kw in patterns["stats_table_keywords"]):
                campaign_stats_table = table

        if not (campaign_table and campaign_stats_table):
            return None

        config = MetaAdsConfig(
            source_type=source.source_type,
            campaign_table=campaign_table,
            stats_table=campaign_stats_table,
            source_id=str(source.id),
        )

        return config

    def _create_tiktokads_config(
        self, source: ExternalDataSource, tables: list[DataWarehouseTable]
    ) -> Optional[TikTokAdsConfig]:
        """Create TikTok Ads adapter config with campaign and stats tables"""
        patterns = TABLE_PATTERNS["TikTokAds"]
        campaign_table = None
        campaign_stats_table = None

        for table in tables:
            table_suffix = table.name.split(".")[-1].lower()

            # Check for campaign table
            if any(kw in table_suffix for kw in patterns["campaign_table_keywords"]) and not any(
                ex in table_suffix for ex in patterns["campaign_table_exclusions"]
            ):
                campaign_table = table
            # Check for stats table
            elif any(kw in table_suffix for kw in patterns["stats_table_keywords"]):
                campaign_stats_table = table

        if not (campaign_table and campaign_stats_table):
            return None

        config = TikTokAdsConfig(
            source_type=source.source_type,
            campaign_table=campaign_table,
            stats_table=campaign_stats_table,
            source_id=str(source.id),
        )

        return config

    def _create_external_adapters(self) -> list[MarketingSourceAdapter]:
        """Create adapters for non-native marketing sources"""
        adapters = []
        external_sources = ExternalDataSource.objects.filter(team_id=self.context.team.pk)

        for source in external_sources:
            if source.source_type not in VALID_NON_NATIVE_MARKETING_SOURCES:
                continue
            adapter_class = self._adapter_registry.get(source.source_type)
            if not adapter_class:
                continue

            tables = list(self._warehouse_tables.filter(external_data_source=source))
            if not tables:
                continue

            for table in tables:
                source_map = self._get_source_map_for_table(table, str(source.id))
                if not source_map:
                    continue

                # For non-native: use schema ID to match frontend (table.schema?.id || table.source?.id || table.id)
                schema = table.externaldataschema_set.first()
                source_id = str(schema.id) if schema else str(table.id)

                config = ExternalConfig(
                    table=table,
                    source_map=source_map,
                    source_type=source.source_type,
                    source_id=source_id,
                    schema_name=self._get_table_schema_name(table),
                )
                adapters.append(adapter_class(config=config, context=self.context))

        return adapters

    def _create_self_managed_adapters(self) -> list[MarketingSourceAdapter]:
        """Create adapters for self-managed external tables"""
        adapters = []

        # Filter out tables already handled by native/non-native flows
        self_managed_tables = [
            table
            for table in self._warehouse_tables
            if not (
                table.external_data_source
                and table.external_data_source.source_type
                in VALID_NATIVE_MARKETING_SOURCES + VALID_NON_NATIVE_MARKETING_SOURCES
            )
        ]

        for table in self_managed_tables:
            source_map = self._get_source_map_for_table(table)
            if not source_map:
                continue

            platform_type = map_url_to_provider(table.url_pattern)
            if not platform_type:
                continue

            adapter_class = self._adapter_registry.get(platform_type)
            if not adapter_class:
                continue

            config = ExternalConfig(
                table=table,
                source_map=source_map,
                source_type="self_managed",
                source_id=str(table.id),
                schema_name=self._get_table_schema_name(table),
            )
            adapters.append(adapter_class(config=config, context=self.context))

        return adapters

    def _get_source_map_for_table(self, table: DataWarehouseTable, source_id: str | None = None) -> Optional[SourceMap]:
        """Get source map for a table"""
        if source_id and table.external_data_source and table.external_data_source.source_type:
            # Managed table
            table_id = str(table.id)
            schema_id = self._get_schema_id_for_table(table)

            # Try schema_id, table_id, then source_id
            for key in [schema_id, table_id, source_id]:
                if key and key in self._sources_map:
                    return self._sources_map[key]
        else:
            if str(table.id) in self._sources_map:
                # Self-managed table
                return self._sources_map[str(table.id)]
            else:
                return None

        return None

    def get_valid_adapters(self, adapters: list[MarketingSourceAdapter]) -> list[MarketingSourceAdapter]:
        """Filter adapters to only return valid ones"""
        valid_adapters = []
        for adapter in adapters:
            try:
                if adapter.validate().is_valid:
                    valid_adapters.append(adapter)
            except Exception as e:
                self.logger.exception("Error validating adapter", source_type=adapter.get_source_type(), error=str(e))
        return valid_adapters

    def build_union_query(self, adapters: list[MarketingSourceAdapter]) -> str:
        """Build union query from all valid adapters"""
        # Sort adapters by source_id to ensure deterministic UNION ALL ordering
        # This prevents flaky tests where query optimizer reorders UNION ALL clauses
        sorted_adapters = sorted(adapters, key=lambda adapter: adapter.config.source_id)

        queries = []
        for adapter in sorted_adapters:
            try:
                query = adapter.build_query_string()
                if query:
                    queries.append(query)
            except Exception as e:
                self.logger.exception(
                    "Error building query for adapter", source_type=adapter.get_source_type(), error=str(e)
                )

        return "\nUNION ALL\n".join(queries) if queries else FALLBACK_EMPTY_QUERY

    def _get_schema_id_for_table(self, table: DataWarehouseTable) -> str | None:
        """Get schema ID for a warehouse table"""
        try:
            # Use prefetched data to avoid N+1 queries
            schema = next((s for s in table.externaldataschema_set.all() if s.table_id == table.id), None)
            return str(schema.id) if schema else None
        except Exception:
            return None

    def _get_table_schema_name(self, table: DataWarehouseTable) -> str:
        """Get schema name for a table"""
        if table.external_data_source and table.external_data_source.source_type:
            schema_id = self._get_schema_id_for_table(table)
            if schema_id:
                try:
                    # Use prefetched data to avoid additional queries
                    schema = next((s for s in table.externaldataschema_set.all() if str(s.id) == schema_id), None)
                    if schema and hasattr(schema, "name"):
                        return schema.name
                except Exception:
                    pass
            return table.name
        return table.name
