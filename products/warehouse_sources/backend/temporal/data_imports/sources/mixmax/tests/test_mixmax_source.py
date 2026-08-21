from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mixmax import MixMaxSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mixmax.source import MixMaxSource


def _config() -> MixMaxSourceConfig:
    return MixMaxSourceConfig(api_key="tok")


class TestValidateCredentials:
    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid Mixmax API token"))])
    def test_validate_credentials(self, _name: str, probe_result: bool, expected: tuple[bool, str | None]) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mixmax.source.validate_mixmax_credentials",
            return_value=probe_result,
        ):
            assert MixMaxSource().validate_credentials(_config(), team_id=1) == expected
