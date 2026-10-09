import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.justcall import (
    JustCallSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.justcall.source import JustCallSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.justcall.source"


class TestJustCallSource:
    def setup_method(self):
        self.source = JustCallSource()
        self.team_id = 123
        self.config = JustCallSourceConfig(api_key="key", api_secret="secret")

    def test_lists_tables_without_credentials(self):
        # The endpoint catalog is static (no I/O), so it's safe to render in public docs.
        assert JustCallSource.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        "probe_result, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid JustCall API credentials"),
        ],
    )
    @mock.patch(f"{SOURCE_MODULE}.validate_justcall_credentials")
    def test_validate_credentials(self, mock_validate, probe_result, expected_valid, expected_message):
        mock_validate.return_value = probe_result

        is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key, self.config.api_secret)
