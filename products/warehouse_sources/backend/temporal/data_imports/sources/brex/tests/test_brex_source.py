import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex import (
    BREX_API_VERSION_V1,
    BREX_API_VERSION_V2,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.brex.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.brex.source import BrexSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.brex import BrexSourceConfig


class TestBrexSource:
    def setup_method(self):
        self.source = BrexSource()
        self.team_id = 123
        self.config = BrexSourceConfig(api_key="bxt_test_token")

    def test_supported_versions_and_default(self):
        # New sources are stamped with the default; v1 stays supported so existing pins keep working.
        assert self.source.supported_versions == (BREX_API_VERSION_V1, BREX_API_VERSION_V2)
        assert self.source.default_version == BREX_API_VERSION_V2

    def test_resolve_api_version_falls_back_to_default_and_honors_pin(self):
        assert self.source.resolve_api_version(None) == BREX_API_VERSION_V2
        assert self.source.resolve_api_version(BREX_API_VERSION_V1) == BREX_API_VERSION_V1

    def test_v1_is_deprecated_without_sunset_and_v2_is_not(self):
        # Brex announced no sunset date, so v1 is flagged deprecated with sunset_at=None; the default
        # v2 must never be deprecated.
        deprecation = self.source.get_version_deprecation(BREX_API_VERSION_V1)
        assert deprecation is not None
        assert deprecation.sunset_at is None
        assert self.source.get_version_deprecation(BREX_API_VERSION_V2) is None

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

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.source.brex_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_brex_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "expenses"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00Z"
        inputs.api_version = None
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_brex_source.assert_called_once()
        kwargs = mock_brex_source.call_args.kwargs
        assert kwargs["api_key"] == "bxt_test_token"
        assert kwargs["endpoint"] == "expenses"
        assert kwargs["team_id"] is inputs.team_id
        assert kwargs["job_id"] is inputs.job_id
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00Z"
        # Unpinned source resolves to the default version at the source class.
        assert kwargs["api_version"] == BREX_API_VERSION_V2

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.source.brex_source")
    def test_source_for_pipeline_passes_pinned_api_version(self, mock_brex_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "users"
        inputs.api_version = BREX_API_VERSION_V1

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_brex_source.call_args.kwargs["api_version"] == BREX_API_VERSION_V1

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.brex.source.brex_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_brex_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "users"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_brex_source.call_args.kwargs["db_incremental_field_last_value"] is None
