from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.settings import (
    APPLE_SEARCH_ADS_ENDPOINTS,
    ENDPOINTS,
    REPORT_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.source import (
    AppleSearchAdsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.applesearchads import (
    AppleSearchAdsSourceConfig,
)

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.source"

REPORT_ENDPOINTS = tuple(name for name, config in APPLE_SEARCH_ADS_ENDPOINTS.items() if config.partition_key)
ENTITY_ENDPOINTS = tuple(name for name, config in APPLE_SEARCH_ADS_ENDPOINTS.items() if not config.partition_key)


class TestAppleSearchAdsSource:
    def setup_method(self) -> None:
        self.source = AppleSearchAdsSource()
        self.team_id = 123
        self.config = AppleSearchAdsSourceConfig(
            org_id="555",
            client_id="SEARCHADS.client",
            apple_team_id="SEARCHADS.team",
            key_id="key-1",
            private_key="-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
            start_date="2026-01-01",
        )

    def test_api_version_metadata(self) -> None:
        assert self.source.supported_versions == ("v5",)
        assert self.source.default_version == "v5"
        assert self.source.api_docs_url.startswith("https://")

    @parameterized.expand([(endpoint,) for endpoint in REPORT_ENDPOINTS])
    def test_report_tables_are_incremental_on_date_with_a_lookback(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)

        assert schema.supports_incremental is True
        assert [f["field"] for f in schema.incremental_fields] == ["date"]
        assert schema.default_incremental_lookback_seconds == REPORT_LOOKBACK_SECONDS
        # The lookback re-reads already-imported days, so appending would duplicate them.
        assert schema.supports_append is False

    @parameterized.expand([(endpoint,) for endpoint in ENTITY_ENDPOINTS])
    def test_entity_tables_are_full_refresh_only(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)

        # Apple's entity endpoints have no updated-since filter, so there is nothing to track.
        assert schema.supports_incremental is False
        assert schema.incremental_fields == []
        assert schema.default_incremental_lookback_seconds is None

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert descriptions is CANONICAL_DESCRIPTIONS
        assert set(descriptions) == set(ENDPOINTS)
        for endpoint, entry in descriptions.items():
            primary_keys = APPLE_SEARCH_ADS_ENDPOINTS[endpoint].primary_keys
            assert set(primary_keys) <= set(entry.get("columns", {})), endpoint
