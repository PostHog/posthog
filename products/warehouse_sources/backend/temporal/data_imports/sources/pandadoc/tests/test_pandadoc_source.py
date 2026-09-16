import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pandadoc import (
    PandaDocSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.source import PandaDocSource


class TestPandaDocSource:
    def setup_method(self):
        self.source = PandaDocSource()
        self.team_id = 123
        self.config = PandaDocSourceConfig(api_key="api-key")

    def test_declares_v1_and_v2_with_v2_default(self):
        # v2 must be the default (new sources stamp it) while v1 stays supported. The registry
        # invariant test only checks default == supported[-1], so it would still pass if v2 were
        # dropped; this test locks in the actual bump.
        assert self.source.supported_versions == ("v1", "v2")
        assert self.source.default_version == "v2"

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.pandadoc.com/public/v1/documents",
            "403 Client Error: Forbidden for url: https://api.pandadoc.com/public/v1/members",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.pandadoc.com/public/v1/documents",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only documents expose server-side date filters (modified_from/created_from).
        assert incremental == {"documents"}

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid PandaDoc API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.source.validate_pandadoc_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)
