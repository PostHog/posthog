from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kalshi import KalshiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kalshi.kalshi import (
    KalshiResumeConfig,
    _to_epoch_seconds,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kalshi.settings import KALSHI_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.kalshi.source import KalshiSource


def _driver() -> SourceDriver:
    return SourceDriver(KalshiSource(), KalshiSourceConfig())


def _page(data_key: str, items: list[dict[str, Any]], *, cursor: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {data_key: items}
    if cursor is not None:
        body["cursor"] = cursor
    return ScriptedResponse(json=body)


class TestKalshiTransport:
    @parameterized.expand(
        [
            ("datetime", datetime(2021, 1, 1, tzinfo=UTC), 1609459200),
            ("date", date(2021, 1, 1), 1609459200),
            ("int_passthrough", 1609459200, 1609459200),
            ("iso_string", "2021-01-01T00:00:00+00:00", 1609459200),
            ("iso_string_z", "2021-01-01T00:00:00Z", 1609459200),
            ("none", None, None),
            ("garbage", "not-a-date", None),
        ]
    )
    def test_to_epoch_seconds(self, _name: str, value: Any, expected: int | None) -> None:
        # min_ts is epoch seconds; sending an ISO string instead would be silently ignored by the
        # API and quietly turn every incremental sync into a full scan.
        assert _to_epoch_seconds(value) == expected

    def test_trades_incremental_sends_min_ts(self) -> None:
        result = _driver().run(
            "trades",
            [_page("trades", [{"trade_id": "t1"}])],
            incremental_field="created_time",
            db_incremental_field_last_value=datetime(2021, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("min_ts") == "1609459200"
        assert result.requests[0].param("limit") == str(KALSHI_ENDPOINTS["trades"].page_size)

    @parameterized.expand(["markets", "events", "milestones"])
    def test_non_incremental_endpoints_never_send_min_ts(self, endpoint: str) -> None:
        # Kalshi answers 200 and ignores params it doesn't recognise, so a filter wired onto an
        # endpoint that has none would look like it worked while syncing everything every run.
        result = _driver().run(
            endpoint,
            [_page(KALSHI_ENDPOINTS[endpoint].data_key, [{"id": "1"}])],
            incremental_field="created_time",
            db_incremental_field_last_value=datetime(2021, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("min_ts") is None

    def test_cursor_pagination_walks_then_stops(self) -> None:
        result = _driver().run(
            "markets",
            [
                _page("markets", [{"ticker": "A"}], cursor="c1"),
                _page("markets", [{"ticker": "B"}], cursor="c2"),
                # No cursor on the final page.
                _page("markets", [{"ticker": "C"}]),
            ],
        )

        assert result.raised is None
        assert [row["ticker"] for row in result.rows] == ["A", "B", "C"]
        # The first request carries no cursor; each later one carries the previous response's.
        assert result.params("cursor") == [None, "c1", "c2"]

    def test_resume_seeds_cursor_onto_first_request(self) -> None:
        result = _driver().run(
            "markets",
            [_page("markets", [{"ticker": "B"}])],
            resume_state=KalshiResumeConfig(cursor="saved"),
        )

        assert result.raised is None
        assert result.requests[0].param("cursor") == "saved"

    @parameterized.expand(
        [
            ("trades", "desc"),
            ("markets", "asc"),
            ("series", "asc"),
        ]
    )
    def test_sort_mode_matches_api_order(self, endpoint: str, expected: str) -> None:
        # Trades arrive newest-first. Declaring "asc" would checkpoint the watermark to ~now after
        # the first batch and skip the rest of the backfill.
        result = _driver().run(endpoint, [_page(KALSHI_ENDPOINTS[endpoint].data_key, [])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.sort_mode == expected

    @parameterized.expand(
        [
            ("markets", ["ticker"]),
            ("events", ["event_ticker"]),
            ("series", ["ticker"]),
            ("trades", ["trade_id"]),
            ("milestones", ["id"]),
        ]
    )
    def test_primary_keys_per_endpoint(self, endpoint: str, expected: list[str]) -> None:
        # A wrong key seeds duplicate rows that every later merge multi-matches.
        result = _driver().run(endpoint, [_page(KALSHI_ENDPOINTS[endpoint].data_key, [])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.primary_keys == expected

    @parameterized.expand(
        [
            ("trades", ["created_time"]),
            ("markets", ["created_time"]),
            ("series", None),
        ]
    )
    def test_partitioning_only_where_a_stable_key_exists(self, endpoint: str, expected: list[str] | None) -> None:
        result = _driver().run(endpoint, [_page(KALSHI_ENDPOINTS[endpoint].data_key, [])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.partition_keys == expected
        assert result.response.partition_mode == ("datetime" if expected else None)

    @parameterized.expand([("ok", 200, True), ("forbidden", 403, False), ("server_error", 500, False)])
    def test_validate_credentials_maps_status(self, _name: str, status: int, expected: bool) -> None:
        answer = ScriptedResponse(status=status)
        script = always(answer) if status == 500 else [answer]
        with scripted_network(script) as network:
            assert validate_credentials() is expected

        assert network.requests_log[0].path == "/trade-api/v2/exchange/status"
