import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.env0.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.env0.source import Env0Source
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.env0 import Env0SourceConfig


class TestEnv0Source:
    def setup_method(self):
        self.source = Env0Source()
        self.team_id = 123
        self.config = Env0SourceConfig(api_key_id="key-id", api_key_secret="key-secret")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.env0.com/environments?limit=100",
            "403 Client Error: Forbidden for url: https://api.env0.com/projects?organizationId=org-1",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.env0.com/environments",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only deployments expose env0's server-side fromDate/toDate window.
        assert incremental == {"deployments"}

    def test_incremental_schemas_advertise_their_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["deployments"].incremental_fields == INCREMENTAL_FIELDS["deployments"]
        assert schemas["environments"].incremental_fields == []
        assert schemas["environments"].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["deployments"])
        assert len(schemas) == 1
        assert schemas[0].name == "deployments"

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid env0 API key credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.env0.source.validate_env0_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key_id, self.config.api_key_secret)
