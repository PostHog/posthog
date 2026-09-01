from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.polymarket.source import PolymarketSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.polymarket.source"


class TestPolymarketSource:
    @parameterized.expand(["events", "markets", "series", "tags"])
    def test_no_table_advertises_incremental(self, endpoint: str) -> None:
        # Gamma filters on startDate and endDate, which describe the trading window rather than when
        # a row was written. Wiring either as a cursor would silently drop backdated rows.
        schemas = {s.name: s for s in PolymarketSource().get_schemas(None, 1)}  # type: ignore[arg-type]

        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].incremental_fields == []

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

    def test_source_is_visible_and_labelled_alpha(self) -> None:
        # unreleasedSource=True hides the connector from users entirely; this source is finished.
        config = PolymarketSource().get_source_config

        assert config.unreleasedSource is None
        assert config.releaseStatus == "alpha"
        assert config.category is not None
        assert config.iconPath == "/static/services/polymarket.png"
