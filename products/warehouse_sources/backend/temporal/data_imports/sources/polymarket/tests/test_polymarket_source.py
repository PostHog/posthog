from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.polymarket.source import PolymarketSource


class TestPolymarketSource:
    @parameterized.expand(["events", "markets", "series", "tags"])
    def test_no_table_advertises_incremental(self, endpoint: str) -> None:
        # Gamma filters on startDate and endDate, which describe the trading window rather than when
        # a row was written. Wiring either as a cursor would silently drop backdated rows.
        schemas = {s.name: s for s in PolymarketSource().get_schemas(None, 1)}  # type: ignore[arg-type]

        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].incremental_fields == []

    @parameterized.expand([("reachable", True, True), ("unreachable", False, False)])
    def test_validate_credentials(self, _name: str, probe_ok: bool, expected: bool) -> None:
        status = 200 if probe_ok else 403
        with scripted_network([ScriptedResponse(status=status)]) as network:
            ok, message = PolymarketSource().validate_credentials(None, 1)  # type: ignore[arg-type]

        assert ok is expected
        assert (message is None) is expected
        assert [request.path for request in network.requests_log] == ["/status"]
