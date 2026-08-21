from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.katana import KatanaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.katana import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.katana.settings import KATANA_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.katana.source import KatanaSource

_INCREMENTAL_ENDPOINTS = [name for name, cfg in KATANA_ENDPOINTS.items() if cfg.incremental_fields]
_FULL_REFRESH_ENDPOINTS = [name for name, cfg in KATANA_ENDPOINTS.items() if not cfg.incremental_fields]


class TestKatanaSourceClass:
    @patch.object(source_module, "validate_katana_credentials")
    def test_validate_credentials_success(self, mock_validate: MagicMock) -> None:
        mock_validate.return_value = True
        ok, error = KatanaSource().validate_credentials(KatanaSourceConfig(api_key="k"), team_id=1)
        assert ok is True
        assert error is None

    @patch.object(source_module, "validate_katana_credentials")
    def test_validate_credentials_failure(self, mock_validate: MagicMock) -> None:
        mock_validate.return_value = False
        ok, error = KatanaSource().validate_credentials(KatanaSourceConfig(api_key="bad"), team_id=1)
        assert ok is False
        assert error is not None
