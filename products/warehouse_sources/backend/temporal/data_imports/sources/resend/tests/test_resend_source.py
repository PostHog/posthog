from unittest import mock

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldOauthConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.resend import (
    ResendAuthMethodConfig,
    ResendSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.resend.oauth import ResendIntegrationAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.resend.resend import ResendResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.resend.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.resend.source import ResendSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _api_key_config(api_key: str = "re_test_key") -> ResendSourceConfig:
    return ResendSourceConfig(auth_method=ResendAuthMethodConfig(selection="api_key", api_key=api_key))


def _oauth_config(integration_id: int = 42) -> ResendSourceConfig:
    return ResendSourceConfig(
        auth_method=ResendAuthMethodConfig(selection="oauth", resend_integration_id=integration_id)
    )


class TestResendSource:
    def setup_method(self):
        self.source = ResendSource()
        self.team_id = 123
        self.config = _api_key_config()

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.RESEND

    def test_get_source_config_offers_both_auth_methods(self):
        config = self.source.get_source_config

        assert config.name.value == "Resend"
        assert config.releaseStatus == "ga"
        assert len(config.fields) == 1

        auth_field = config.fields[0]
        assert isinstance(auth_field, SourceFieldSelectConfig)
        assert auth_field.name == "auth_method"
        assert auth_field.defaultValue == "api_key"

        options = {option.value: option for option in auth_field.options}
        assert set(options) == {"api_key", "oauth"}

        api_key_fields = options["api_key"].fields
        assert api_key_fields is not None
        api_key_field = api_key_fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.secret is True

        oauth_fields = options["oauth"].fields
        assert oauth_fields is not None
        oauth_field = oauth_fields[0]
        assert isinstance(oauth_field, SourceFieldOauthConfig)
        assert oauth_field.name == "resend_integration_id"
        assert oauth_field.kind == "resend"
        assert oauth_field.requiredScopes == "full_access"

    def test_non_retryable_errors(self):
        errors = self.source.get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)
        # OAuth reconnect signals must be non-retryable too.
        assert any("Integration not found" in key for key in errors)

    def test_audiences_bad_request_is_non_retryable(self):
        errors = self.source.get_non_retryable_errors()
        raised = "400 Client Error: Bad Request for url: https://api.resend.com/audiences"

        matched = [message for key, message in errors.items() if key in raised]

        assert len(matched) == 1
        assert matched[0] is not None and "Audiences" in matched[0]

    @parameterized.expand(
        [
            ("broadcasts_matches", "https://api.resend.com/broadcasts", True),
            ("other_endpoint_stays_retryable", "https://api.resend.com/emails", False),
        ]
    )
    def test_broadcasts_bad_request_retryability(self, _name: str, url: str, should_match: bool):
        errors = self.source.get_non_retryable_errors()
        raised = f"400 Client Error: Bad Request for url: {url}"

        matched = [message for key, message in errors.items() if key in raised]

        if should_match:
            assert len(matched) == 1
            assert matched[0] is not None and "Broadcasts" in matched[0]
        else:
            assert not matched

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["emails"])

        assert len(schemas) == 1
        assert schemas[0].name == "emails"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["nonexistent"])

        assert schemas == []

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.resend.source.validate_resend_credentials"
    )
    def test_validate_credentials_api_key_success(self, mock_validate):
        mock_validate.return_value = True

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None
        mock_validate.assert_called_once_with("re_test_key")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.resend.source.validate_resend_credentials"
    )
    def test_validate_credentials_api_key_failure(self, mock_validate):
        mock_validate.return_value = False

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "Invalid Resend API key"

    def test_validate_credentials_api_key_missing(self):
        config = ResendSourceConfig(auth_method=ResendAuthMethodConfig(selection="api_key", api_key=None))

        is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error_message is not None and "Missing Resend API key" in error_message

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.resend.source.validate_resend_credentials"
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.resend.source.resolve_resend_oauth_token"
    )
    @mock.patch.object(ResendSource, "get_oauth_integration")
    def test_validate_credentials_oauth_success(self, mock_get_integration, mock_resolve, mock_validate):
        mock_resolve.return_value = "oauth_access_token"
        mock_validate.return_value = True

        is_valid, error_message = self.source.validate_credentials(_oauth_config(), self.team_id)

        assert is_valid is True
        assert error_message is None
        mock_get_integration.assert_called_once_with(42, self.team_id)
        mock_resolve.assert_called_once_with(42, self.team_id)
        mock_validate.assert_called_once_with("oauth_access_token")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.resend.source.validate_resend_credentials"
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.resend.source.resolve_resend_oauth_token"
    )
    @mock.patch.object(ResendSource, "get_oauth_integration")
    def test_validate_credentials_oauth_failure(self, mock_get_integration, mock_resolve, mock_validate):
        mock_resolve.return_value = "oauth_access_token"
        mock_validate.return_value = False

        is_valid, error_message = self.source.validate_credentials(_oauth_config(), self.team_id)

        assert is_valid is False
        assert error_message is not None and "reconnect" in error_message.lower()

    @mock.patch.object(ResendSource, "get_oauth_integration", side_effect=ValueError("Integration not found: 42"))
    def test_validate_credentials_oauth_missing_integration(self, _mock_get_integration):
        is_valid, error_message = self.source.validate_credentials(_oauth_config(), self.team_id)

        assert is_valid is False
        assert error_message == "Integration not found: 42"

    def test_get_resumable_source_manager(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ResendResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.resend.source.resend_source")
    def test_source_for_pipeline_api_key_passes_bearer_auth(self, mock_resend_source):
        mock_resend_source.return_value = mock.MagicMock()

        inputs = mock.MagicMock()
        inputs.schema_name = "audiences"
        inputs.team_id = 123
        inputs.job_id = "job-1"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_resend_source.call_args.kwargs
        assert kwargs["endpoint"] == "audiences"
        assert kwargs["team_id"] == 123
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        assert isinstance(kwargs["auth"], BearerTokenAuth)
        assert kwargs["auth"].token == "re_test_key"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.resend.source.resend_source")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.resend.source.resolve_resend_oauth_token"
    )
    @mock.patch.object(ResendSource, "get_oauth_integration")
    def test_source_for_pipeline_oauth_passes_integration_auth(
        self, mock_get_integration, mock_resolve, mock_resend_source
    ):
        mock_resolve.return_value = "oauth_access_token"
        mock_resend_source.return_value = mock.MagicMock()

        inputs = mock.MagicMock()
        inputs.schema_name = "emails"
        inputs.team_id = 123
        inputs.job_id = "job-1"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(_oauth_config(), manager, inputs)

        auth = mock_resend_source.call_args.kwargs["auth"]
        assert isinstance(auth, ResendIntegrationAuth)
        assert auth.token == "oauth_access_token"
        mock_resolve.assert_called_once_with(42, 123)
