from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.kalshi.source import KalshiSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.kalshi.source"


class TestKalshiSource:
    @parameterized.expand([("reachable", True, True), ("unreachable", False, False)])
    @mock.patch(f"{SOURCE_MODULE}.validate_kalshi_credentials")
    def test_validate_credentials(self, _name: str, probe_ok: bool, expected: bool, mock_validate) -> None:
        mock_validate.return_value = probe_ok

        ok, message = KalshiSource().validate_credentials(None, 1)  # type: ignore[arg-type]

        assert ok is expected
        assert (message is None) is expected
