import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.plunk import PlunkSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.plunk.plunk import PlunkResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.plunk.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.plunk.source import PlunkSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestPlunkSource:
    def setup_method(self):
        self.source = PlunkSource()
        self.team_id = 123
        self.config = PlunkSourceConfig(api_key="sk_test", base_url=None)

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.PLUNK

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Plunk"
        assert config.label == "Plunk"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/plunk.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/plunk"

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
        # The secret key is sent to base_url, so retargeting it must re-require the key.
        assert self.source.connection_host_fields == ["base_url"]

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints_full_refresh(self):
        # No Plunk list endpoint accepts a server-side timestamp filter, so every stream must
        # ship full-refresh only — flipping one to incremental would corrupt sync watermarks.
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    @pytest.mark.parametrize(
        "names, expected",
        [
            (["contacts"], {"contacts"}),
            (["nope"], set()),
        ],
    )
    def test_get_schemas_filtered_by_names(self, names, expected):
        assert {s.name for s in self.source.get_schemas(self.config, self.team_id, names=names)} == expected

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.plunk.source.validate_plunk_credentials"
    )
    def test_validate_credentials_plumbs_arguments(self, mock_validate):
        mock_validate.return_value = (True, None)

        result = self.source.validate_credentials(self.config, self.team_id, schema_name="contacts")

        assert result == (True, None)
        mock_validate.assert_called_once_with(self.config.base_url, self.config.api_key, "contacts", self.team_id)

    def test_get_resumable_source_manager(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is PlunkResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.plunk.source.plunk_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_plunk_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "contacts"
        inputs.team_id = 42
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_plunk_source.assert_called_once()
        kwargs = mock_plunk_source.call_args.kwargs
        assert kwargs["base_url"] == self.config.base_url
        assert kwargs["api_key"] == "sk_test"
        assert kwargs["endpoint"] == "contacts"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == 42

    def test_canonical_descriptions_match_endpoint_catalog(self):
        # Descriptions are keyed by schema name; a rename in settings.py must not silently
        # orphan the curated docs.
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions) == set(ENDPOINTS)
