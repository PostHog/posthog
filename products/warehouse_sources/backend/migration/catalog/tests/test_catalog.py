from parameterized import parameterized

from products.warehouse_sources.backend.migration.catalog import match_destination, match_source
from products.warehouse_sources.backend.migration.catalog.fivetran_sources import FIVETRAN_SOURCE_TYPES
from products.warehouse_sources.backend.models.external_data_destination import ExternalDataDestination
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestCatalog:
    def test_every_fivetran_source_match_is_a_registered_source(self) -> None:
        registered = set(SourceRegistry.get_all_sources())
        unregistered = {
            service: str(source_type)
            for service, source_type in FIVETRAN_SOURCE_TYPES.items()
            if source_type not in registered
        }
        assert unregistered == {}

    @parameterized.expand(
        [
            ("name_match", "fivetran", "google_ads", ExternalDataSourceType.GOOGLEADS),
            ("managed_database_flavor", "fivetran", "postgres_rds", ExternalDataSourceType.POSTGRES),
            ("rejected_name_match", "fivetran", "light_speed_retail", None),
            ("unknown_service", "fivetran", "not_a_service", None),
            ("unknown_provider", "airbyte", "postgres", None),
        ]
    )
    def test_match_source(
        self, _name: str, provider: str, service: str, expected: ExternalDataSourceType | None
    ) -> None:
        match = match_source(provider, service)
        assert (match.source_type if match else None) == expected

    @parameterized.expand(
        [
            ("bigquery_variant", "fivetran", "managed_big_query", ExternalDataDestination.Type.BIGQUERY),
            ("postgres_variant", "fivetran", "postgres_rds_warehouse", ExternalDataDestination.Type.POSTGRES),
            ("no_posthog_destination", "fivetran", "clickhouse", None),
            ("unknown_provider", "airbyte", "snowflake", None),
        ]
    )
    def test_match_destination(
        self, _name: str, provider: str, service: str, expected: ExternalDataDestination.Type | None
    ) -> None:
        assert match_destination(provider, service) == expected
