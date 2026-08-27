import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.torii import ToriiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.torii.source import ToriiSource


class TestToriiSource:
    def setup_method(self):
        self.source = ToriiSource()
        self.team_id = 123
        self.config = ToriiSourceConfig(api_key="test-key")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.toriihq.com/v1.0/apps",
            "403 Client Error: Forbidden for url: https://api.toriihq.com/v1.0/contracts",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.toriihq.com/v1.0/users",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas_full_refresh_only(self):
        # Torii's public API reference documents no server-side "updated since" filter on any
        # of these endpoints.
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.torii.source.validate_torii_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.torii.source.torii_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_torii_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Apps"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.api_version = None
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_torii_source.assert_called_once()
        kwargs = mock_torii_source.call_args.kwargs
        assert kwargs["api_key"] == "test-key"
        assert kwargs["endpoint"] == "Apps"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["api_version"] == "1.1"

    def test_resolves_pinned_api_version_when_set(self):
        inputs = mock.MagicMock()
        inputs.schema_name = "Apps"
        inputs.api_version = "1.1"
        manager = mock.MagicMock()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.torii.source.torii_source"
        ) as mock_torii_source:
            self.source.source_for_pipeline(self.config, manager, inputs)
            assert mock_torii_source.call_args.kwargs["api_version"] == "1.1"
