from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.codacy.source import CodacySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.codacy import CodacySourceConfig


def _config() -> CodacySourceConfig:
    return CodacySourceConfig(api_token="token", provider="gh", organization="acme")


class TestCodacySource:
    def setup_method(self) -> None:
        self.source = CodacySource()

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.codacy.source.validate_codacy_credentials")
    def test_validate_credentials_maps_transport_result(self, mock_validate: MagicMock) -> None:
        mock_validate.return_value = True
        assert self.source.validate_credentials(_config(), team_id=1) == (True, None)

        mock_validate.return_value = False
        ok, error = self.source.validate_credentials(_config(), team_id=1)
        assert ok is False
        assert error == "Invalid Codacy API token"
