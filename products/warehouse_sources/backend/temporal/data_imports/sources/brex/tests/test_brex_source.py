import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex import BrexResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.brex.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.brex.source import BrexSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BrexSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestBrexSource:
    def setup_method(self):
        self.source = BrexSource()
        self.team_id = 123
        self.config = BrexSourceConfig(api_key="bxt_test_token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.BREX

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Brex"
        assert config.label == "Brex"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/brex.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    def test_caption_mentions_token_expiry(self):
        config = self.source.get_source_config
        assert config.caption is not None
        assert "90 days" in config.caption

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.brex.com/v2/transactions/card/primary?limit=100",
            "403 Client Error: Forbidden for url: https://api.brex.com/v1/expenses",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_non_retryable_401_message_mentions_token_expiry(self):
        non_retryable_errors = self.source.get_non_retryable_errors()
        message = non_retryable_errors["401 Client Error: Unauthorized for url: https://api.brex.com"]
        assert message is not None
        assert "90 days" in message

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.brex.com/v1/expenses",
            "429 Client Error: Too Many Requests for url: https://api.brex.com/v2/users",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only transactions and expenses expose a server-side timestamp filter.
        assert incremental == {"card_transactions", "cash_transactions", "expenses"}

    @pytest.mark.parametrize("endpoint", ["card_transactions", "cash_transactions", "expenses"])
    def test_incremental_schemas_advertise_their_fields(self, endpoint):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas[endpoint].incremental_fields == INCREMENTAL_FIELDS[endpoint]
        assert schemas[endpoint].supports_append is True

    @pytest.mark.parametrize("endpoint", ["users", "departments", "locations", "vendors", "budgets"])
    def test_full_refresh_schemas_have_no_incremental_fields(self, endpoint):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas[endpoint].incremental_fields == []
        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["expenses"])
        assert len(schemas) == 1
        assert schemas[0].name == "expenses"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [
            (True, True),
            (False, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.brex.source.validate_brex_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if expected_valid:
            assert error_message is None
        else:
            assert error_message is not None
            assert "90 days" in error_message
        mock_validate.assert_called_once_with(self.config.api_key)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is BrexResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.source.brex_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_brex_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "expenses"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_brex_source.assert_called_once()
        kwargs = mock_brex_source.call_args.kwargs
        assert kwargs["api_key"] == "bxt_test_token"
        assert kwargs["endpoint"] == "expenses"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.source.brex_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_brex_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "users"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_brex_source.call_args.kwargs["db_incremental_field_last_value"] is None
