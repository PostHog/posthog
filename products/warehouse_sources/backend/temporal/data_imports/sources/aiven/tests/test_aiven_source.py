from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.aiven import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.aiven.source import AivenSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.aiven import AivenSourceConfig


def _config() -> AivenSourceConfig:
    return AivenSourceConfig.from_dict({"api_token": "tok"})


class TestValidateCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_maps_validation_result(self, _name: str, valid: bool, expected: bool) -> None:
        with patch.object(source_module, "validate_aiven_credentials", return_value=valid):
            ok, error = AivenSource().validate_credentials(_config(), team_id=1)
        assert ok is expected
        assert (error is None) is expected
