from typing import Any, cast

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.apple_search_ads import (
    AppleSearchAdsResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.settings import (
    APPLE_SEARCH_ADS_ENDPOINTS,
    ENDPOINTS,
    REPORT_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.source import (
    AppleSearchAdsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
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

    def test_lists_tables_without_credentials(self) -> None:
        # `get_schemas` walks a static catalog, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_the_endpoint_catalog(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        assert all(schema.description for schema in schemas)

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["campaigns", "campaign_report"])

        assert {schema.name for schema in schemas} == {"campaigns", "campaign_report"}

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

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_non_retryable_errors_cover_auth_failures(self, _name: str, status: int) -> None:
        errors = self.source.get_non_retryable_errors()

        assert any(str(status) in key and "searchads.apple.com" in key for key in errors)
        assert all(message for message in errors.values())

    def test_get_resumable_source_manager_is_namespaced_per_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "campaign_report"

        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AppleSearchAdsResumeConfig
        # Entity and report checkpoints have incompatible shapes, so they must not share a slot.
        assert manager._namespace == "campaign_report"

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "campaign_report"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-05-01"
        inputs.api_version = None
        manager = mock.MagicMock()

        with mock.patch(f"{SOURCE_MODULE}.apple_search_ads_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = cast("dict[str, Any]", mock_source.call_args.kwargs)
        assert kwargs["endpoint"] == "campaign_report"
        assert kwargs["api_version"] == "v5"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-05-01"
        assert kwargs["start_date"] == "2026-01-01"
        assert kwargs["credentials"].org_id == "555"
