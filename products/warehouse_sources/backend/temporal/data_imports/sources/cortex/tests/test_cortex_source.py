from unittest import mock

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.cortex.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.cortex.source import CortexSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cortex import CortexSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestCortexSource:
    def setup_method(self) -> None:
        self.source = CortexSource()
        self.team_id = 123
        self.config = CortexSourceConfig(api_key="cx_key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.CORTEX

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Cortex"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/cortex"

    def test_source_is_released_not_hidden(self) -> None:
        # A finished source must be visible: `unreleasedSource` hides it from every user.
        assert not self.source.get_source_config.unreleasedSource

    def test_source_config_fields(self) -> None:
        config = self.source.get_source_config
        input_fields = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert input_fields == ["api_key"]

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_are_all_full_refresh(self) -> None:
        # Cortex exposes no server-side updated-since cursor, so no stream is incremental.
        for schema in self.source.get_schemas(self.config, self.team_id):
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["entities"])
        assert [s.name for s in schemas] == ["entities"]

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — powers the public docs table list.
        assert self.source.lists_tables_without_credentials is True

    def test_canonical_descriptions_cover_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.getcortexapp.com/api/v1/catalog"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.getcortexapp.com/api/v1/catalog"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_non_retryable_errors_ignore_transient(self) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(
            key in "503 Server Error for url: https://api.getcortexapp.com/api/v1/catalog" for key in non_retryable
        )

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cortex.source.validate_cortex_credentials"
    )
    def test_validate_credentials_plumbs_arguments(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)
        result = self.source.validate_credentials(self.config, self.team_id, schema_name="entities")

        assert result == (True, None)
        mock_validate.assert_called_once_with("cx_key", schema_name="entities")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.cortex.source.cortex_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_cortex_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "scorecard_scores"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"

        self.source.source_for_pipeline(self.config, inputs)

        kwargs = mock_cortex_source.call_args.kwargs
        assert kwargs["api_key"] == "cx_key"
        assert kwargs["endpoint"] == "scorecard_scores"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["job_id"] == "job-1"
