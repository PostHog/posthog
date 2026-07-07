import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PipedriveSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.pipedrive import PipedriveResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.source import PipedriveSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestPipedriveSource:
    def setup_method(self) -> None:
        self.source = PipedriveSource()
        self.team_id = 123
        self.config = PipedriveSourceConfig(company_domain="acme", api_token="token")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.PIPEDRIVE

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Pipedrive"
        assert config.label == "Pipedrive"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/pipedrive.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["company_domain", "api_token"]

    def test_api_token_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    def test_company_domain_is_connection_host_field(self) -> None:
        assert self.source.connection_host_fields == ["company_domain"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://acme.pipedrive.com/api/v2/deals?limit=500",
            "403 Client Error: Forbidden for url: https://acme.pipedrive.com/api/v1/activities?limit=500&start=0",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://acme.pipedrive.com/api/v2/deals",
            "500 Server Error for url: https://acme.pipedrive.com/api/v1/notes",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient(self, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_lists_all_endpoints_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["deals"])
        assert len(schemas) == 1
        assert schemas[0].name == "deals"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "status, schema_name, expected_valid, expected_message",
        [
            (200, None, True, None),
            (200, "deals", True, None),
            (403, None, True, None),
            (403, "deals", False, "Invalid Pipedrive API token or insufficient permissions"),
            (401, None, False, "Invalid Pipedrive API token or insufficient permissions"),
            (500, None, False, "Could not validate Pipedrive credentials"),
            (None, None, False, "Could not validate Pipedrive credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.source.validate_pipedrive_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        status: int | None,
        schema_name: str | None,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = status

        is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name)

        assert is_valid is expected_valid
        assert message == expected_message
        mock_validate.assert_called_once_with("acme", "token")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.source.validate_pipedrive_credentials"
    )
    def test_validate_credentials_rejects_invalid_domain(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.side_effect = ValueError("Invalid Pipedrive company domain: 'evil.com'")
        is_valid, message = self.source.validate_credentials(
            PipedriveSourceConfig(company_domain="evil.com", api_token="token"), self.team_id
        )
        assert is_valid is False
        assert message is not None and "Invalid Pipedrive company domain" in message

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is PipedriveResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.source.pipedrive_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_pipedrive_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "deals"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_pipedrive_source.assert_called_once()
        kwargs = mock_pipedrive_source.call_args.kwargs
        assert kwargs["company_domain"] == "acme"
        assert kwargs["api_token"] == "token"
        assert kwargs["endpoint"] == "deals"
        assert kwargs["resumable_source_manager"] is manager

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.source.pipedrive_source")
    def test_source_for_pipeline_normalizes_company_domain(self, mock_pipedrive_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "deals"

        self.source.source_for_pipeline(
            PipedriveSourceConfig(company_domain="https://Acme.pipedrive.com", api_token="token"),
            mock.MagicMock(),
            inputs,
        )

        assert mock_pipedrive_source.call_args.kwargs["company_domain"] == "acme"
