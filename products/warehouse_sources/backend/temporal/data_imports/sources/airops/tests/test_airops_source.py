from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.airops.source import AirOpsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.airops import AirOpsSourceConfig


def _config(api_key: str = "test-key") -> AirOpsSourceConfig:
    return AirOpsSourceConfig.from_dict({"api_key": api_key})


class TestAirOpsSource:
    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid AirOps API key"))])
    def test_validate_credentials(self, _name: str, probe_result: bool, expected: tuple[bool, str | None]) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.airops.source.validate_airops_credentials",
            return_value=probe_result,
        ):
            assert AirOpsSource().validate_credentials(_config(), team_id=1) == expected

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.airops.com/public_api/airops_apps",),
            ("403 Client Error: Forbidden for url: https://api.airops.com/public_api/airops_apps",),
        ]
    )
    def test_non_retryable_errors_match_credential_failures(self, raised_message: str) -> None:
        # A revoked/regenerated key must permanently fail the sync rather than retry forever; the
        # matcher keys on the stable status text + base host, so a real HTTPError string matches.
        errors = AirOpsSource().get_non_retryable_errors()
        assert any(pattern in raised_message and friendly for pattern, friendly in errors.items())
