from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hyros import HyrosSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hyros.source import HyrosSource

_INCREMENTAL_ENDPOINTS = {"Leads", "Sales", "Calls", "Subscriptions"}
_FULL_REFRESH_ENDPOINTS = {"Sources", "Tags", "Keywords", "Stages"}


class TestHyrosSource:
    def setup_method(self):
        self.source = HyrosSource()
        self.team_id = 123
        self.config = HyrosSourceConfig(api_key="key")

    def test_api_version_metadata(self):
        assert self.source.supported_versions == ("v1.0",)
        assert self.source.default_version == "v1.0"
        assert self.source.api_docs_url == "https://api-docs.hyros.com"

    @parameterized.expand(
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Hyros API key"),
            ((False, 403), False, "Invalid Hyros API key"),
            ((False, None), False, "Invalid Hyros API key"),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.hyros.source.validate_hyros_credentials"
    )
    def test_validate_credentials(self, mock_return, expected_valid, expected_message_prefix, mock_validate):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if expected_message_prefix is None:
            assert error_message is None
        else:
            assert error_message is not None
            assert error_message.startswith(expected_message_prefix)
        mock_validate.assert_called_once_with("key")
