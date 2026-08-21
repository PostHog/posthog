import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.secureframe import (
    SecureframeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.secureframe.source import SecureframeSource

MOCK_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.secureframe.source"


class TestSecureframeSource:
    def setup_method(self):
        self.source = SecureframeSource()
        self.team_id = 123
        self.config = SecureframeSourceConfig(api_key="key", api_secret="secret", region="us")

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
