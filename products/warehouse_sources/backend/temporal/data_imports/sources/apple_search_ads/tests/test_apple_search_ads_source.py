from typing import Any, cast

from unittest import mock

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.apple_search_ads import (
    AppleSearchAdsCredentials,
    AppleSearchAdsResumeConfig,
)
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.applesearchads import (
    AppleSearchAdsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

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

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.APPLESEARCHADS

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "AppleSearchAds"
        assert config.label == "Apple Search Ads"
        assert config.category == DataWarehouseSourceCategory.ADVERTISING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/apple_search_ads.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/apple-search-ads"

    @parameterized.expand(
        [
            ("org_id", SourceFieldInputConfigType.TEXT, True, False),
            ("client_id", SourceFieldInputConfigType.TEXT, True, False),
            ("apple_team_id", SourceFieldInputConfigType.TEXT, True, False),
            ("key_id", SourceFieldInputConfigType.TEXT, True, False),
            ("private_key", SourceFieldInputConfigType.TEXTAREA, True, True),
            ("start_date", SourceFieldInputConfigType.TEXT, False, False),
        ]
    )
    def test_source_fields(
        self, name: str, field_type: SourceFieldInputConfigType, required: bool, secret: bool
    ) -> None:
        fields = {
            field.name: field
            for field in self.source.get_source_config.fields
            if isinstance(field, SourceFieldInputConfig)
        }

        assert set(fields) == {"org_id", "client_id", "apple_team_id", "key_id", "private_key", "start_date"}
        field = fields[name]
        assert field.type == field_type
        assert field.required is required
        assert field.secret is secret

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

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert descriptions is CANONICAL_DESCRIPTIONS
        assert set(descriptions) == set(ENDPOINTS)
        for endpoint, entry in descriptions.items():
            primary_keys = APPLE_SEARCH_ADS_ENDPOINTS[endpoint].primary_keys
            assert set(primary_keys) <= set(entry.get("columns", {})), endpoint

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_non_retryable_errors_cover_auth_failures(self, _name: str, status: int) -> None:
        errors = self.source.get_non_retryable_errors()

        assert any(str(status) in key and "searchads.apple.com" in key for key in errors)
        assert all(message for message in errors.values())

    def test_validate_credentials_maps_the_config_onto_apple_credentials(self) -> None:
        with mock.patch(f"{SOURCE_MODULE}.validate_apple_search_ads_credentials") as mock_validate:
            mock_validate.return_value = (True, None)

            assert self.source.validate_credentials(self.config, self.team_id) == (True, None)

        credentials, api_version, schema_name = mock_validate.call_args.args
        assert credentials == AppleSearchAdsCredentials(
            org_id="555",
            client_id="SEARCHADS.client",
            team_id="SEARCHADS.team",
            key_id="key-1",
            private_key=self.config.private_key,
        )
        assert api_version == "v5"
        assert schema_name is None

    def test_validate_credentials_honors_a_pinned_api_version(self) -> None:
        with mock.patch(f"{SOURCE_MODULE}.validate_apple_search_ads_credentials") as mock_validate:
            mock_validate.return_value = (True, None)
            self.source.validate_credentials(self.config, self.team_id, api_version="v4")

        assert mock_validate.call_args.args[1] == "v4"

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
