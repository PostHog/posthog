import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.babelforce import (
    BabelforceResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.source import BabelforceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BabelforceSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestBabelforceSource:
    def setup_method(self):
        self.source = BabelforceSource()
        self.team_id = 123
        self.config = BabelforceSourceConfig(environment="services", access_id="access-id", access_token="token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.BABELFORCE

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Babelforce"
        assert config.label == "Babelforce"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/babelforce.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["environment", "access_id", "access_token"]

    def test_access_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "access_token"
        )
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    def test_environment_is_a_connection_host_field(self):
        # `environment` decides which host receives the stored token; changing it must force
        # the editor to re-enter the token or the credential could be exfiltrated.
        assert self.source.connection_host_fields == ["environment"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://services.babelforce.com/api/v2/calls/reporting?max=100",
            "403 Client Error: Forbidden for url: https://us-east.babelforce.com/api/v2/agents",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_non_retryable_errors_does_not_match_server_errors(self):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(
            key in "500 Server Error for url: https://services.babelforce.com/api/v2/calls/reporting"
            for key in non_retryable_errors
        )

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only call reporting documents a server-side dateCreated filter.
        assert incremental == {"calls"}

    def test_incremental_schemas_advertise_their_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["calls"].incremental_fields == INCREMENTAL_FIELDS["calls"]
        assert schemas["agents"].incremental_fields == []
        assert schemas["agents"].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["calls"])
        assert len(schemas) == 1
        assert schemas[0].name == "calls"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Babelforce API credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.source.validate_babelforce_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.environment, self.config.access_id, self.config.access_token)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.source.validate_babelforce_credentials"
    )
    def test_validate_credentials_rejects_bad_environment_without_probing(self, mock_validate):
        config = BabelforceSourceConfig(environment="evil.example.com", access_id="id", access_token="token")

        is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error_message is not None
        mock_validate.assert_not_called()

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is BabelforceResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.source.babelforce_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_babelforce_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "calls"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2023-11-14T22:13:20.000Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_babelforce_source.assert_called_once()
        kwargs = mock_babelforce_source.call_args.kwargs
        assert kwargs["environment"] == "services"
        assert kwargs["access_id"] == "access-id"
        assert kwargs["access_token"] == "token"
        assert kwargs["endpoint"] == "calls"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2023-11-14T22:13:20.000Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.source.babelforce_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_babelforce_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "agents"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2023-11-14T22:13:20.000Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_babelforce_source.call_args.kwargs["db_incremental_field_last_value"] is None
