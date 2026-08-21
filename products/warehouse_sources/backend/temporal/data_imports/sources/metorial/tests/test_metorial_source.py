from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.metorial import (
    MetorialSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metorial.source import MetorialSource

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.metorial.source"


def _config() -> MetorialSourceConfig:
    return MetorialSourceConfig.from_dict({"api_key": "metorial_sk_test"})


class TestValidateCredentials:
    @parameterized.expand([("valid", True), ("invalid", False)])
    def test_maps_probe_result(self, _name: str, probe_ok: bool) -> None:
        with patch(f"{_SOURCE_MODULE}.validate_metorial_credentials", return_value=probe_ok):
            ok, error = MetorialSource().validate_credentials(_config(), team_id=1)
        assert ok is probe_ok
        assert (error is None) is probe_ok
