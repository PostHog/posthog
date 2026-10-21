import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.metaplane import (
    MetaplaneSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metaplane.source import MetaplaneSource


class TestMetaplaneSource:
    def setup_method(self) -> None:
        self.source = MetaplaneSource()
        self.team_id = 123
        self.config = MetaplaneSourceConfig(api_key="mp-test-key")

    @pytest.mark.parametrize(
        "is_valid, expected_valid, expected_has_message",
        [
            (True, True, False),
            (False, False, True),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.metaplane.source.validate_metaplane_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        is_valid: bool,
        expected_valid: bool,
        expected_has_message: bool,
    ) -> None:
        mock_validate.return_value = is_valid
        valid, message = self.source.validate_credentials(self.config, self.team_id)
        assert valid is expected_valid
        assert (message is not None) is expected_has_message
        mock_validate.assert_called_once_with(self.config.api_key)
