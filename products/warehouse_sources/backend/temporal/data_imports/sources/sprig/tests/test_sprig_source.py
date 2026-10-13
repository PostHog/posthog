from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sprig import SprigSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sprig.source import SprigSource


def _config() -> SprigSourceConfig:
    return SprigSourceConfig(api_key="sprig-key")


class TestValidateCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sprig.source.validate_sprig_credentials")
    def test_validate(self, _label: str, api_result: bool, expected_ok: bool, mock_validate: MagicMock) -> None:
        mock_validate.return_value = api_result
        ok, error = SprigSource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok
