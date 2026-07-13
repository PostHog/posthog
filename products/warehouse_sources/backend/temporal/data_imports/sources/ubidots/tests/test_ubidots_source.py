import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import UbidotsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ubidots.settings import ENDPOINTS, VALUES_ENDPOINT
from products.warehouse_sources.backend.temporal.data_imports.sources.ubidots.source import UbidotsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.ubidots.ubidots import UbidotsResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestUbidotsSource:
    def setup_method(self) -> None:
        self.source = UbidotsSource()
        self.team_id = 123
        self.config = UbidotsSourceConfig(api_token="BBUS-token")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.UBIDOTS

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Ubidots"
        assert config.label == "Ubidots"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # Deliberately still gated while the source lands across PRs.
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/ubidots"

        field_names = [f.name for f in config.fields]
        assert field_names == ["api_token", "api_base_url"]

    def test_api_token_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_only_values_is_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert set(schemas) == set(ENDPOINTS)

        values = schemas[VALUES_ENDPOINT]
        assert values.supports_incremental is True
        assert [f["field"] for f in values.incremental_fields] == ["timestamp"]

        for name, schema in schemas.items():
            if name == VALUES_ENDPOINT:
                continue
            assert schema.supports_incremental is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["devices"])
        assert len(schemas) == 1
        assert schemas[0].name == "devices"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://industrial.api.ubidots.com/api/v2.0/devices/",),
            ("403 Client Error: Forbidden for url: https://industrial.api.ubidots.com/api/v2.0/variables/",),
            ("401 Client Error: Unauthorized for url: https://things.ubidots.com/api/v1.6/variables/abc/values",),
            ("403 Client Error: Forbidden for url: https://things.ubidots.com/api/v2.0/events/",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://industrial.api.ubidots.com/api/v2.0/devices/",),
            ("429 Client Error: Too Many Requests for url: https://things.ubidots.com/api/v2.0/variables/",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.ubidots.source.validate_credentials")
    def test_validate_credentials_delegates_to_shared_helper(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (False, "Invalid Ubidots API token")
        result = self.source.validate_credentials(self.config, self.team_id)
        assert result == (False, "Invalid Ubidots API token")
        mock_validate.assert_called_once_with("BBUS-token", "https://industrial.api.ubidots.com")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is UbidotsResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.ubidots.source.ubidots_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = VALUES_ENDPOINT
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000000
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "BBUS-token"
        assert kwargs["api_base_url"] == "https://industrial.api.ubidots.com"
        assert kwargs["endpoint"] == VALUES_ENDPOINT
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000000

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Ubidots schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
