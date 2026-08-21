from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.vantage.source import VantageSource


class TestValidateCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_delegates_to_transport(self, _name: str, transport_result: bool, expected_ok: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.vantage.source.validate_vantage_credentials",
            return_value=transport_result,
        ):
            ok, error = VantageSource().validate_credentials(MagicMock(), team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok
