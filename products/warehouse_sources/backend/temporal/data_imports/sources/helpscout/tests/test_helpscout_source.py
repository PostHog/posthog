import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldOauthConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.helpscout import (
    HelpScoutSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.helpscout import HelpScoutResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.source import HelpScoutSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestHelpScoutSource:
    def setup_method(self):
        self.source = HelpScoutSource()
        self.team_id = 123
        self.config = HelpScoutSourceConfig(helpscout_integration_id=456)

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.HELPSCOUT

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "HelpScout"
        assert config.label == "Help Scout"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/helpscout.png"

        # The only field is the OAuth connect button. A regression that reintroduced raw client
        # credential inputs would make users register their own Help Scout app again.
        oauth_fields = [f for f in config.fields if isinstance(f, SourceFieldOauthConfig)]
        assert [f.name for f in oauth_fields] == ["helpscout_integration_id"]
        assert oauth_fields[0].kind == "helpscout"
        assert oauth_fields[0].required is True
        assert len(config.fields) == 1

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.helpscout.net/v2/conversations",
            "Integration not found: 456",
            "Help Scout app not configured",
        ],
    )
    def test_non_retryable_errors_match_client_errors(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.helpscout.net/v2/conversations",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas_covers_every_endpoint(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", ["conversations", "customers"])
    def test_get_schemas_supports_incremental_for_modified_since_endpoints(self, endpoint):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[endpoint].supports_incremental is True
        assert [f["field"] for f in schemas[endpoint].incremental_fields] == ["modifiedAt"]

    @pytest.mark.parametrize("endpoint", ["mailboxes", "users", "tags", "workflows", "threads"])
    def test_get_schemas_full_refresh_only_for_remaining_endpoints(self, endpoint):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["mailboxes"])
        assert len(schemas) == 1
        assert schemas[0].name == "mailboxes"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.source.OauthIntegration")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.source.HelpScoutSource.get_oauth_integration"
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.source.validate_helpscout_credentials"
    )
    def test_validate_credentials_plumbs_arguments(self, mock_validate, mock_get_integration, mock_oauth):
        mock_validate.return_value = (True, None)
        mock_get_integration.return_value = mock.MagicMock(access_token="token", kind="helpscout")
        mock_oauth.return_value.access_token_expired.return_value = False

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, schema_name="tags")

        assert is_valid is True
        assert error_message is None
        mock_get_integration.assert_called_once_with(456, self.team_id)
        mock_validate.assert_called_once_with("token", "tags")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.source.HelpScoutSource.get_oauth_integration"
    )
    def test_validate_credentials_reports_missing_integration(self, mock_get_integration):
        mock_get_integration.side_effect = ValueError("Integration not found: 456")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "Integration not found: 456"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.source.OauthIntegration")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.source.HelpScoutSource.get_oauth_integration"
    )
    def test_integration_of_another_kind_is_rejected(self, mock_get_integration, mock_oauth):
        # The lookup only scopes to the team, so a config pointing at another provider's
        # integration must be rejected before its access token is read or refreshed.
        mock_get_integration.return_value = mock.MagicMock(access_token="token", kind="salesforce")

        with pytest.raises(ValueError, match="Integration not found: 456"):
            self.source._get_access_token(self.config, self.team_id)

        mock_oauth.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.source.OauthIntegration")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.source.HelpScoutSource.get_oauth_integration"
    )
    def test_expired_token_is_refreshed_before_use(self, mock_get_integration, mock_oauth):
        # Help Scout access tokens last ~2 days, so a source syncing on a stale token would 401
        # mid-run instead of refreshing.
        mock_get_integration.return_value = mock.MagicMock(access_token="token", kind="helpscout")
        mock_oauth.return_value.access_token_expired.return_value = True

        self.source._get_access_token(self.config, self.team_id)

        mock_oauth.return_value.refresh_access_token.assert_called_once()

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is HelpScoutResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.source.OauthIntegration")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.source.HelpScoutSource.get_oauth_integration"
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.source.helpscout_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_helpscout_source, mock_get_integration, mock_oauth):
        mock_get_integration.return_value = mock.MagicMock(access_token="token", kind="helpscout")
        mock_oauth.return_value.access_token_expired.return_value = False
        inputs = mock.MagicMock()
        inputs.schema_name = "conversations"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "modifiedAt"
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_helpscout_source.assert_called_once()
        kwargs = mock_helpscout_source.call_args.kwargs
        assert kwargs["access_token"] == "token"
        assert kwargs["endpoint"] == "conversations"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["incremental_field"] == "modifiedAt"
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.source.OauthIntegration")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.source.HelpScoutSource.get_oauth_integration"
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.source.helpscout_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(
        self, mock_helpscout_source, mock_get_integration, mock_oauth
    ):
        mock_get_integration.return_value = mock.MagicMock(access_token="token", kind="helpscout")
        mock_oauth.return_value.access_token_expired.return_value = False
        inputs = mock.MagicMock()
        inputs.schema_name = "mailboxes"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "should-be-ignored"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_helpscout_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None
