import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.twenty import TwentySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.twenty.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.twenty.source import TwentySource
from products.warehouse_sources.backend.temporal.data_imports.sources.twenty.twenty import TwentyResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestTwentySource:
    def setup_method(self):
        self.source = TwentySource()
        self.team_id = 123
        self.config = TwentySourceConfig(api_key="tok", base_url=None)

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.TWENTY

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Twenty"
        assert config.label == "Twenty"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/twenty.svg"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/twenty"
        assert config.unreleasedSource is None

        field_names = [f.name for f in config.fields]
        assert field_names == ["api_key", "base_url"]

        api_key_field, base_url_field = config.fields
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

        assert isinstance(base_url_field, SourceFieldInputConfig)
        assert base_url_field.type == SourceFieldInputConfigType.TEXT
        assert base_url_field.secret is False
        assert base_url_field.required is False

    def test_connection_host_fields_force_secret_reentry(self):
        # The API key is sent to base_url, so retargeting it must re-require the key.
        assert self.source.connection_host_fields == ["base_url"]

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_all_schemas_support_incremental_on_updated_and_created_at(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        for schema in schemas:
            assert schema.supports_incremental is True
            assert schema.supports_append is True
            assert {f["field"] for f in schema.incremental_fields} == {"updatedAt", "createdAt"}

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["companies"])
        assert len(schemas) == 1
        assert schemas[0].name == "companies"

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected",
        [
            ((True, None), (True, None)),
            ((False, "Invalid Twenty API key"), (False, "Invalid Twenty API key")),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.twenty.source.validate_twenty_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected):
        mock_validate.return_value = mock_return

        result = self.source.validate_credentials(self.config, self.team_id, schema_name="companies")

        assert result == expected
        mock_validate.assert_called_once_with(self.config.base_url, self.config.api_key, self.team_id, "companies")

    def test_get_resumable_source_manager(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is TwentyResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.twenty.source.twenty_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_twenty_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "companies"
        inputs.team_id = 42
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00.000Z"
        inputs.incremental_field = "updatedAt"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_twenty_source.assert_called_once()
        kwargs = mock_twenty_source.call_args.kwargs
        assert kwargs["base_url"] == self.config.base_url
        assert kwargs["api_key"] == "tok"
        assert kwargs["endpoint"] == "companies"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == 42
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00.000Z"
        assert kwargs["incremental_field"] == "updatedAt"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.twenty.source.twenty_source")
    def test_source_for_pipeline_omits_watermark_on_full_refresh(self, mock_twenty_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "companies"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00.000Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_twenty_source.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_core_tables(self):
        descriptions = self.source.get_canonical_descriptions()
        # Curated docs only describe endpoints we actually expose.
        assert set(descriptions).issubset(set(ENDPOINTS))
        assert "companies" in descriptions
        assert "people" in descriptions
        assert "opportunities" in descriptions
