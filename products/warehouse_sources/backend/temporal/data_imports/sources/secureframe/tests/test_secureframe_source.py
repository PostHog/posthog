import pytest
from unittest import mock

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.secureframe import (
    SecureframeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.secureframe.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.secureframe.source import SecureframeSource

MOCK_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.secureframe.source"


class TestSecureframeSource:
    def setup_method(self):
        self.source = SecureframeSource()
        self.team_id = 123
        self.config = SecureframeSourceConfig(api_key="key", api_secret="secret", region="us")

    @pytest.mark.parametrize("field_name", ["api_key", "api_secret"])
    def test_credential_fields_are_secret_passwords(self, field_name):
        # Both halves of the credential must be secret so the source serializer never echoes
        # them back in job_inputs to anyone who can read the source.
        config = self.source.get_source_config
        secret_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == field_name)
        assert secret_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_field.secret is True
        assert secret_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.secureframe.com/controls?page=1&per_page=100",
            "403 Client Error: Forbidden for url: https://api-uk.secureframe.com/tests?page=1&per_page=100",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_non_retryable_errors_do_not_match_transient_failures(self):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(
            key in "500 Server Error for url: https://api.secureframe.com/controls" for key in non_retryable_errors
        )

    def test_get_schemas_are_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # No verified server-side timestamp filter exists, so nothing may advertise incremental.
        assert all(not schema.supports_incremental and not schema.supports_append for schema in schemas)

    @pytest.mark.parametrize(
        "probe_result, schema_name, expected_valid",
        [
            # At source-create a valid key with a missing scope (403) must still connect.
            ((True, True), None, True),
            ((True, False), None, True),
            ((False, False), None, False),
            # A per-schema check demands read access to that specific endpoint.
            ((True, True), "controls", True),
            ((True, False), "controls", False),
            ((False, False), "controls", False),
        ],
    )
    @mock.patch(f"{MOCK_MODULE}.validate_secureframe_credentials")
    def test_validate_credentials(self, mock_validate, probe_result, schema_name, expected_valid):
        mock_validate.return_value = probe_result

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        assert is_valid is expected_valid
        assert (error_message is None) is expected_valid
        mock_validate.assert_called_once_with("key", "secret", "us", endpoint=schema_name)
