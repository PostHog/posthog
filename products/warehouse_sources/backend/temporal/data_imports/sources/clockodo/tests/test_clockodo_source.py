from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.source import ClockodoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clockodo import (
    ClockodoSourceConfig,
)


def _config() -> ClockodoSourceConfig:
    return ClockodoSourceConfig(api_user="me@example.com", api_key="secret")


class TestClockodoSource:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validate_credentials(self, _name: str, probe_result: bool, expected_ok: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.source.validate_clockodo_credentials",
            return_value=probe_result,
        ):
            ok, error = ClockodoSource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok
