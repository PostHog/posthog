from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.vapi import VapiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vapi.settings import (
    ENDPOINTS,
    VAPI_VERSION_V1,
    VAPI_VERSION_V2,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.vapi.source import VapiSource

# Endpoints whose Vapi list action exposes a server-side timestamp filter usable with the
# endpoint's ordering guarantees; the rest are full refresh only.
_INCREMENTAL_ENDPOINTS = {"calls", "chats", "sessions"}
_FULL_REFRESH_ENDPOINTS = set(ENDPOINTS) - _INCREMENTAL_ENDPOINTS


class TestVapiSource:
    def setup_method(self):
        self.source = VapiSource()
        self.team_id = 123
        self.config = VapiSourceConfig(api_key="key")

    def test_declares_v1_and_v2_with_v2_default(self):
        # New sources are stamped v2; v1 stays declared so existing pinned rows keep their path.
        assert self.source.supported_versions == (VAPI_VERSION_V1, VAPI_VERSION_V2)
        assert self.source.default_version == VAPI_VERSION_V2

    @parameterized.expand(
        [
            (True, True, None),
            (False, False, "Invalid Vapi API key"),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.vapi.source.validate_vapi_credentials"
    )
    def test_validate_credentials(self, mock_return, expected_valid, expected_message, mock_validate):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key")
