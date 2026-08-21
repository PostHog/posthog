from typing import Any

from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.easypost.source import EasypostSource


def _config() -> Any:
    config = MagicMock()
    config.api_key = "EZAK_test"
    return config


class TestValidateCredentials:
    def test_valid(self, monkeypatch: Any) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.easypost import source as source_module

        monkeypatch.setattr(source_module, "validate_easypost_credentials", lambda api_key: True)
        assert EasypostSource().validate_credentials(_config(), team_id=1) == (True, None)

    def test_invalid(self, monkeypatch: Any) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.easypost import source as source_module

        monkeypatch.setattr(source_module, "validate_easypost_credentials", lambda api_key: False)
        ok, error = EasypostSource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert error is not None
