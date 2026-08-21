from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm import source as agilecrm_source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm.source import AgileCRMSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.agilecrm import (
    AgileCRMSourceConfig,
)


def _config() -> AgileCRMSourceConfig:
    return AgileCRMSourceConfig(domain="acme", email="a@b.com", api_key="key")


class TestValidateCredentials:
    def test_success(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(agilecrm_source_module, "validate_agilecrm_credentials", lambda *a, **k: True)
        ok, error = AgileCRMSource().validate_credentials(_config(), team_id=1)
        assert ok is True
        assert error is None

    def test_failure(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(agilecrm_source_module, "validate_agilecrm_credentials", lambda *a, **k: False)
        ok, error = AgileCRMSource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert error is not None
