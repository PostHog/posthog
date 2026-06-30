import pytest
from unittest import mock

from posthog.schema import SourceFieldOauthConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import IntercomSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.intercom.settings import INTERCOM_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.intercom.source import IntercomSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

INCREMENTAL_ENDPOINTS = {"contacts", "conversations", "tickets", "activity_logs", "conversation_parts"}


class TestIntercomSource:
    def setup_method(self):
        self.source = IntercomSource()
        self.team_id = 123
        self.config = IntercomSourceConfig(intercom_integration_id=456)

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.INTERCOM

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Intercom"
        assert config.releaseStatus == "beta"
        assert not config.unreleasedSource

        oauth_field = config.fields[0]
        assert isinstance(oauth_field, SourceFieldOauthConfig)
        assert oauth_field.name == "intercom_integration_id"
        assert oauth_field.kind == "intercom"
        assert oauth_field.required is True

    @pytest.mark.parametrize(
        "key",
        [
            "401 Client Error",
            "403 Client Error",
            "Missing integration ID",
            "Integration not found",
            "Intercom access token not found",
        ],
    )
    def test_get_non_retryable_errors(self, key):
        assert key in self.source.get_non_retryable_errors()

    @pytest.mark.parametrize(
        "error_msg",
        [
            "Integration not found: 172567",
            "Missing integration ID",
            "Intercom access token not found for job job-123",
        ],
    )
    def test_oauth_config_errors_are_non_retryable(self, error_msg):
        # Matching in import_data_sync is substring-based, so the curated keys must be stable
        # prefixes of the raised messages (the integration ID / job ID are volatile).
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in error_msg for key in non_retryable_errors)

    def test_get_schemas_covers_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(INTERCOM_ENDPOINTS.keys())

    def test_get_schemas_incremental_flags(self):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        for name, schema in schemas.items():
            expected = name in INCREMENTAL_ENDPOINTS
            assert schema.supports_incremental is expected, name
            assert schema.supports_append is expected, name

    def test_get_schemas_names_filter(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["contacts", "companies"])

        assert {s.name for s in schemas} == {"contacts", "companies"}

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.intercom.source.validate_intercom_credentials"
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.intercom.source.IntercomSource.get_oauth_integration"
    )
    def test_validate_credentials_success(self, mock_get_integration, mock_validate):
        mock_get_integration.return_value = mock.MagicMock(access_token="token")
        mock_validate.return_value = (True, None)

        is_valid, error = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error is None
        mock_get_integration.assert_called_once_with(self.config.intercom_integration_id, self.team_id)
        mock_validate.assert_called_once_with("token", schema_name=None)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.intercom.source.IntercomSource.get_oauth_integration"
    )
    def test_validate_credentials_integration_value_error(self, mock_get_integration):
        mock_get_integration.side_effect = ValueError("integration not found")

        is_valid, error = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error == "integration not found"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.intercom.source.IntercomSource.get_oauth_integration"
    )
    def test_validate_credentials_no_access_token(self, mock_get_integration):
        mock_get_integration.return_value = mock.MagicMock(access_token=None)

        is_valid, error = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error is not None and "no access token" in error

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.intercom.source.intercom_source")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.intercom.source.IntercomSource.get_oauth_integration"
    )
    def test_source_for_pipeline_plumbing(self, mock_get_integration, mock_intercom_source):
        mock_get_integration.return_value = mock.MagicMock(access_token="token")
        sentinel = mock.MagicMock()
        mock_intercom_source.return_value = sentinel

        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.schema_name = "contacts"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "updated_at"
        inputs.db_incremental_field_last_value = "1700000000"

        result = self.source.source_for_pipeline(self.config, inputs)

        assert result is sentinel
        mock_intercom_source.assert_called_once_with(
            access_token="token",
            endpoint="contacts",
            team_id=self.team_id,
            job_id="job-1",
            should_use_incremental_field=True,
            incremental_field="updated_at",
            db_incremental_field_last_value="1700000000",
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.intercom.source.intercom_source")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.intercom.source.IntercomSource.get_oauth_integration"
    )
    def test_source_for_pipeline_drops_incremental_args_when_not_incremental(
        self, mock_get_integration, mock_intercom_source
    ):
        mock_get_integration.return_value = mock.MagicMock(access_token="token")

        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.schema_name = "companies"
        inputs.should_use_incremental_field = False
        inputs.incremental_field = "updated_at"
        inputs.db_incremental_field_last_value = "1700000000"

        self.source.source_for_pipeline(self.config, inputs)

        _, kwargs = mock_intercom_source.call_args
        assert kwargs["incremental_field"] is None
        assert kwargs["db_incremental_field_last_value"] is None

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.intercom.source.IntercomSource.get_oauth_integration"
    )
    def test_source_for_pipeline_no_access_token_raises(self, mock_get_integration):
        mock_get_integration.return_value = mock.MagicMock(access_token=None)

        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.schema_name = "contacts"

        with pytest.raises(ValueError, match="Intercom access token not found for job job-1"):
            self.source.source_for_pipeline(self.config, inputs)
