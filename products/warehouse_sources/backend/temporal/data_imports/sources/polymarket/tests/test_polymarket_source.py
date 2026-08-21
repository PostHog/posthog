from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.polymarket.source import PolymarketSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.polymarket.source"


class TestPolymarketSource:
    @parameterized.expand([("reachable", True, True), ("unreachable", False, False)])
    @mock.patch(f"{SOURCE_MODULE}.validate_polymarket_credentials")
    def test_validate_credentials(self, _name: str, probe_ok: bool, expected: bool, mock_validate) -> None:
        mock_validate.return_value = probe_ok

        ok, message = PolymarketSource().validate_credentials(None, 1)  # type: ignore[arg-type]

        assert ok is expected
        assert (message is None) is expected

    def test_non_retryable_errors_cover_the_regional_403(self) -> None:
        # Gamma restricts some regions with a 403 that no credential fix can resolve; the message
        # should tell the caller that rather than let the pipeline retry forever.
        errors = PolymarketSource().get_non_retryable_errors()

        assert "403 Client Error: Forbidden for url: https://gamma-api.polymarket.com" in errors
        assert errors["403 Client Error: Forbidden for url: https://gamma-api.polymarket.com"] is not None
