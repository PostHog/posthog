import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tawkto import TawkToSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tawk_to.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.tawk_to.source import TawkToSource

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.tawk_to.source"


class TestTawkToSource:
    def setup_method(self):
        self.source = TawkToSource()
        self.team_id = 123
        self.config = TawkToSourceConfig(api_key="api-key")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.tawk.to/v1/chat.list",
            "403 Client Error: Forbidden for url: https://api.tawk.to/v1/ticket.list",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.tawk.to/v1/chat.list",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_are_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # tawk.to's date filters are unverified (API reference is access-gated), so no endpoint
        # may advertise incremental sync until they're confirmed against a live account.
        assert all(not schema.supports_incremental and not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["chats"])
        assert [schema.name for schema in schemas] == ["chats"]

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid tawk.to API key"),
        ],
    )
    @mock.patch(f"{MODULE}.validate_tawk_to_credentials")
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)

    @mock.patch(f"{MODULE}.tawk_to_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_tawk_to_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "chats"
        manager = mock.MagicMock()
        config = TawkToSourceConfig(api_key="api-key", property_id="prop-1")

        self.source.source_for_pipeline(config, manager, inputs)

        kwargs = mock_tawk_to_source.call_args.kwargs
        assert kwargs["api_key"] == "api-key"
        assert kwargs["property_id"] == "prop-1"
        assert kwargs["endpoint"] == "chats"
        assert kwargs["resumable_source_manager"] is manager

    @pytest.mark.parametrize("raw_property_id", [None, "", "   "])
    @mock.patch(f"{MODULE}.tawk_to_source")
    def test_source_for_pipeline_normalizes_blank_property_id(self, mock_tawk_to_source, raw_property_id):
        inputs = mock.MagicMock()
        inputs.schema_name = "chats"
        config = TawkToSourceConfig(api_key="api-key", property_id=raw_property_id)

        self.source.source_for_pipeline(config, mock.MagicMock(), inputs)

        assert mock_tawk_to_source.call_args.kwargs["property_id"] is None
