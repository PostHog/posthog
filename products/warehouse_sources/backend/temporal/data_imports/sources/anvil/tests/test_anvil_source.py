import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.anvil.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.anvil.source import AnvilSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.anvil import AnvilSourceConfig


class TestAnvilSource:
    def setup_method(self):
        self.source = AnvilSource()
        self.team_id = 123
        self.config = AnvilSourceConfig(api_key="key-1")

    def test_get_schemas_every_table_is_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # No endpoint has a verified server-side timestamp filter, so advertising a cursor
        # would ship an incremental sync that silently re-fetches everything.
        assert not any(schema.supports_incremental or schema.supports_append for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["weld_datas"])
        assert [schema.name for schema in schemas] == ["weld_datas"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_non_retryable_errors_match_anvil_auth_failures(self):
        # The verbatim message requests raises once the transport's retries are exhausted.
        auth_error = "401 Client Error: Unauthorized for url: https://graphql.useanvil.com"
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in auth_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "Anvil API error: Weld not found",
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
        ],
    )
    def test_non_retryable_errors_do_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            ((False, "Anvil rejected the API key"), False, "Anvil rejected the API key"),
            ((False, None), False, "Invalid Anvil API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.anvil.source.validate_anvil_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key-1")
