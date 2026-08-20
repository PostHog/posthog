import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sigmacomputing import (
    SigmaComputingSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sigma_computing.settings import (
    ENDPOINTS,
    REGION_HOSTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sigma_computing.sigma_computing import (
    SigmaComputingResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sigma_computing.source import (
    REGION_OPTIONS,
    SigmaComputingSource,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestSigmaComputingSource:
    def setup_method(self) -> None:
        self.source = SigmaComputingSource()
        self.team_id = 123
        self.config = SigmaComputingSourceConfig(client_id="client-id", client_secret="client-secret", region="gcp_us")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SIGMACOMPUTING

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "SigmaComputing"
        assert config.label == "Sigma Computing"
        assert config.category == DataWarehouseSourceCategory.ANALYTICS
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # The source ships visible: unreleasedSource hides the connector from every user.
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/sigma_computing.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/sigma-computing"

    def test_connection_host_fields(self) -> None:
        # `region` picks the host the client secret is sent to, so retargeting it must
        # re-require the secret.
        assert self.source.connection_host_fields == ["region"]

    def test_region_field_options_cover_every_declared_host(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldSelectConfig) and f.name == "region")
        assert {option.value for option in field.options} == set(REGION_HOSTS)
        assert field.required is True
        assert field.defaultValue == "gcp_us"

    def test_region_options_constant_matches_settings(self) -> None:
        assert {option.value for option in REGION_OPTIONS} == set(REGION_HOSTS)

    def test_client_secret_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "client_secret")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_client_id_field_is_not_secret(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "client_id")
        assert field.secret is False
        assert field.required is True

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_are_full_refresh_only(self) -> None:
        # Sigma's list endpoints expose no server-side updated-since filter.
        schemas = self.source.get_schemas(self.config, self.team_id)
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Workbooks"])
        assert len(schemas) == 1
        assert schemas[0].name == "Workbooks"

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.sigmacomputing.com/v2/workbooks",
            "403 Client Error: Forbidden for url: https://api.sigmacomputing.com/v2/workbooks",
            "Sigma rejected the API client credentials (HTTP 401)",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_non_retryable_errors_ignore_transient_failures(self) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(
            key in "500 Server Error for url: https://api.sigmacomputing.com/v2/workbooks" for key in non_retryable
        )

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.sigma_computing.source.validate_sigma_computing_credentials"
    )
    def test_validate_credentials_plumbs_arguments(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)

        result = self.source.validate_credentials(self.config, self.team_id, schema_name="Workbooks")

        assert result == (True, None)
        mock_validate.assert_called_once_with(
            region="gcp_us",
            client_id="client-id",
            client_secret="client-secret",
            schema_name="Workbooks",
        )

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SigmaComputingResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.sigma_computing.source.sigma_computing_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_sigma_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "WorkbookElements"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_sigma_source.call_args.kwargs
        assert kwargs["region"] == "gcp_us"
        assert kwargs["client_id"] == "client-id"
        assert kwargs["client_secret"] == "client-secret"
        assert kwargs["endpoint"] == "WorkbookElements"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager

    def test_canonical_descriptions_cover_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
