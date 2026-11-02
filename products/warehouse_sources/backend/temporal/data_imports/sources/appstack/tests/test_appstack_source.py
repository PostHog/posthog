from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.appstack.source import AppstackSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appstack import (
    AppstackSourceConfig,
)


def _config() -> AppstackSourceConfig:
    return AppstackSourceConfig(api_key="appstack-key")


class TestValidateCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.appstack.source.validate_appstack_credentials"
    )
    def test_validate(self, _label: str, api_result: bool, expected_ok: bool, mock_validate: MagicMock) -> None:
        mock_validate.return_value = api_result
        ok, error = AppstackSource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok
