import datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.coinmarketcap import (
    CoinMarketCapPaginator,
    CoinMarketCapResumeConfig,
    _history_start,
    _last_published_snapshot_date,
    _rows_from,
    _snapshot_start_date,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.settings import (
    HISTORICAL_BACKFILL_DAYS,
    HISTORICAL_BATCH_SIZE,
    HISTORICAL_EXCHANGE_LIMIT,
    PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.source import CoinMarketCapSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.coinmarketcap import (
    CoinMarketCapSourceConfig,
)


def _full_page() -> list[dict[str, Any]]:
    return [{"id": i} for i in range(PAGE_SIZE)]


class TestCoinMarketCapPaginator:
    def test_get_resume_state_none_on_terminal_page(self) -> None:
        paginator = CoinMarketCapPaginator()
        paginator.update_state(MagicMock(), [])
        assert paginator.get_resume_state() is None


def _driver() -> SourceDriver:
    return SourceDriver(CoinMarketCapSource(), CoinMarketCapSourceConfig(api_key="test-key"))


def _response(body: dict[str, Any], status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body)


class TestCoinMarketCapSourceResumeBehavior:
    @staticmethod
    def _page_body(items: list[dict[str, Any]]) -> dict[str, Any]:
        return {"data": items, "status": {"error_code": 0, "error_message": None}}

    @pytest.mark.parametrize(
        ("endpoint", "list_key"),
        [
            ("cryptocurrency_map", None),
            ("listings_latest", None),
            ("fiat_map", None),
            ("liquidations_by_cryptocurrency_latest", "cryptocurrencies"),
            ("liquidations_by_exchange_latest", "exchanges"),
        ],
    )
    def test_fresh_run_saves_start_after_each_non_terminal_page(self, endpoint: str, list_key: str | None) -> None:
        def body(items: list[dict[str, Any]]) -> dict[str, Any]:
            if list_key is None:
                return self._page_body(items)
            return {"data": {list_key: items, "total_size": PAGE_SIZE + 1, "has_more": False}}

        result = _driver().run(endpoint, [_response(body(_full_page())), _response(body([{"id": "x"}]))])

        # First request starts at 1; the second carries the advanced start.
        assert result.params("start") == ["1", str(1 + PAGE_SIZE)]
        assert result.saved_states == [CoinMarketCapResumeConfig(start=1 + PAGE_SIZE)]
        assert len(result.rows) == PAGE_SIZE + 1
        assert result.raised is None

    def test_resume_seeds_paginator_with_saved_start(self) -> None:
        result = _driver().run(
            "cryptocurrency_map",
            [_response(self._page_body([{"id": "resumed"}]))],
            resume_state=CoinMarketCapResumeConfig(start=1 + PAGE_SIZE),
        )

        assert result.params("start") == [str(1 + PAGE_SIZE)]
        assert result.rows == [{"id": "resumed"}]
        assert result.raised is None

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        result = _driver().run("cryptocurrency_map", [_response(self._page_body([{"id": "a"}]))])

        assert result.params("start") == ["1"]
        assert result.raised is None


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (429, False),
        ],
    )
    def test_status_code_mapping(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            valid, error = validate_credentials("test-key")
        assert valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None
        assert network.requests_log[0].path == "/v1/key/info"
        assert network.requests_log[0].headers["x-cmc_pro_api_key"] == "test-key"


class TestRowsFrom:
    def test_object_map_flattens_symbol_keyed_lists(self) -> None:
        # Requesting by symbol wraps each value in a list, because a symbol isn't unique.
        rows = _rows_from("object_map", {"BTC": [{"id": 1}, {"id": 2}]})
        assert [row["id"] for row in rows] == [1, 2]

    def test_per_coin_quotes_stamps_coin_identity_on_each_quote(self) -> None:
        rows = _rows_from(
            "per_coin_quotes",
            {
                "1": {
                    "id": 1,
                    "name": "Bitcoin",
                    "symbol": "BTC",
                    "quotes": [
                        {"timestamp": "2026-01-01T00:00:00.000Z", "quote": {"USD": {"price": 1.0}}},
                        {"timestamp": "2026-01-02T00:00:00.000Z", "quote": {"USD": {"price": 2.0}}},
                    ],
                }
            },
        )

        assert len(rows) == 2
        assert all(row["id"] == 1 and row["symbol"] == "BTC" for row in rows)
        assert [row["timestamp"] for row in rows] == ["2026-01-01T00:00:00.000Z", "2026-01-02T00:00:00.000Z"]
        # The nested array must not survive onto the row, or every row carries the whole series.
        assert all("quotes" not in row for row in rows)

    def test_per_coin_quotes_handles_a_single_object_payload(self) -> None:
        # OHLCV historical returns the coin object directly when only one id is requested.
        rows = _rows_from(
            "per_coin_quotes",
            {"id": 1, "symbol": "BTC", "quotes": [{"time_open": "2026-01-01T00:00:00.000Z"}]},
        )
        assert rows == [{"id": 1, "symbol": "BTC", "time_open": "2026-01-01T00:00:00.000Z"}]

    def test_quote_list_reads_the_nested_series(self) -> None:
        rows = _rows_from("quote_list", {"quotes": [{"timestamp": "2026-01-01T00:00:00.000Z", "btc_dominance": 50.0}]})
        assert rows == [{"timestamp": "2026-01-01T00:00:00.000Z", "btc_dominance": 50.0}]

    @pytest.mark.parametrize("data", [None, {}, {"quotes": None}])
    def test_quote_list_tolerates_an_empty_body(self, data: Any) -> None:
        assert _rows_from("quote_list", data) == []


class TestHistoryStart:
    def test_passes_a_string_watermark_through(self) -> None:
        assert _history_start("2026-01-01T00:00:00.000Z") == "2026-01-01T00:00:00.000Z"


class TestGetBatchRows:
    def test_global_metrics_makes_one_unbatched_request(self) -> None:
        result = _driver().run(
            "global_metrics_quotes_historical",
            [_response({"data": {"quotes": [{"timestamp": "2026-01-01T00:00:00.000Z"}]}})],
        )

        assert result.rows == [{"timestamp": "2026-01-01T00:00:00.000Z"}]
        assert result.paths == ["/v1/global-metrics/quotes/historical"]
        assert result.requests[0].param("id") is None
        assert result.requests[0].param("interval") == "daily"
        # No coin batches to resume through, so nothing should be checkpointed.
        assert result.saved_states == []
        assert result.raised is None

    def test_incremental_sends_the_watermark(self) -> None:
        watermark = datetime.datetime(2026, 3, 1, tzinfo=datetime.UTC)
        result = _driver().run(
            "global_metrics_quotes_historical",
            [_response({"data": {"quotes": []}})],
            incremental_field="timestamp",
            db_incremental_field_last_value=watermark,
        )
        assert result.requests[0].param("time_start") == watermark.isoformat()
        assert result.raised is None

    def test_info_walks_every_map_page(self) -> None:
        # The first page is full but carries one unusable row. The walk has to count the raw page,
        # or a single bad row ends it early and the table syncs an incomplete coin set.
        first_page = [{"id": i} for i in range(1, PAGE_SIZE)]
        first_page.append({"no_id": True})
        result = _driver().run(
            "cryptocurrency_info",
            [
                _response({"data": first_page}),
                _response({"data": [{"id": PAGE_SIZE + 1}]}),
                *[_response({"data": {}}) for _ in range(21)],
            ],
        )

        map_calls = [request for request in result.requests if request.path == "/v1/cryptocurrency/map"]
        assert [request.param("start") for request in map_calls] == ["1", str(1 + PAGE_SIZE)]
        assert result.raised is None

    def test_resume_holds_its_place_when_a_coin_leaves_the_universe(self) -> None:
        # Id 5 is gone since the attempt that checkpointed. A position-based cursor would slide the
        # whole tail forward by one and skip a coin that was never yielded.
        remaining = [coin_id for coin_id in range(1, HISTORICAL_BATCH_SIZE + 2) if coin_id != 5]
        result = _driver().run(
            "quotes_historical",
            [
                _response({"data": [{"id": coin_id} for coin_id in remaining]}),
                _response({"data": {}}),
            ],
            resume_state=CoinMarketCapResumeConfig(last_coin_id=HISTORICAL_BATCH_SIZE),
        )

        batch_calls = [request for request in result.requests if request.path == "/v3/cryptocurrency/quotes/historical"]
        assert len(batch_calls) == 1
        assert batch_calls[0].param("id") == str(HISTORICAL_BATCH_SIZE + 1)
        assert result.raised is None

    def test_exchange_info_batches_every_id_in_the_exchange_map(self) -> None:
        result = _driver().run(
            "exchange_info",
            [
                _response({"data": [{"id": 16}, {"id": 24}]}),
                _response({"data": {"16": {"id": 16}, "24": {"id": 24}}}),
            ],
        )

        map_call, info_call = result.requests
        # The ids come from the exchange map, not the cryptocurrency map.
        assert map_call.path == "/v1/exchange/map"
        assert info_call.path == "/v1/exchange/info"
        assert info_call.param("id") == "16,24"
        assert [row["id"] for row in result.rows] == [16, 24]
        assert result.raised is None

    def test_exchange_history_ranks_the_exchange_universe_by_volume(self) -> None:
        listings = {"data": [{"id": exchange_id} for exchange_id in range(HISTORICAL_BATCH_SIZE + 1, 0, -1)]}
        result = _driver().run(
            "exchange_quotes_historical",
            [_response(listings), _response({"data": {}}), _response({"data": {}})],
        )

        universe_call, first_batch, _ = result.requests
        # `market_cap` is not in this endpoint's sort enum — exchanges rank by traded volume.
        assert universe_call.path == "/v1/exchange/listings/latest"
        assert universe_call.param("sort") == "volume_24h"
        assert universe_call.param("sort_dir") == "desc"
        assert universe_call.param("limit") == str(HISTORICAL_EXCHANGE_LIMIT)

        assert first_batch.path == "/v1/exchange/quotes/historical"
        assert first_batch.param("id") == ",".join(str(i) for i in range(1, HISTORICAL_BATCH_SIZE + 1))
        assert first_batch.param("time_start") == _history_start(None)
        assert result.raised is None


class TestLastPublishedSnapshotDate:
    @pytest.mark.parametrize(
        ("hour", "expected_day"),
        [
            # A completed day's snapshot lands ~30 minutes after midnight UTC, so before 01:00
            # yesterday is not there yet and asking for it would fail the sync.
            (0, 8),
            (1, 9),
            (23, 9),
        ],
    )
    def test_waits_for_the_snapshot_to_publish(self, hour: int, expected_day: int) -> None:
        now = datetime.datetime(2026, 3, 10, hour, 15, tzinfo=datetime.UTC)
        assert _last_published_snapshot_date(now) == datetime.date(2026, 3, expected_day)


class TestSnapshotStartDate:
    @pytest.mark.parametrize(
        "watermark",
        [
            "2026-03-01",
            "2026-03-01T00:00:00.000Z",
            datetime.date(2026, 3, 1),
            datetime.datetime(2026, 3, 1, 18, 0, tzinfo=datetime.UTC),
        ],
    )
    def test_reads_the_day_out_of_every_watermark_shape(self, watermark: Any) -> None:
        assert _snapshot_start_date(watermark) == datetime.date(2026, 3, 1)

    def test_unparseable_watermark_falls_back_rather_than_raising(self) -> None:
        expected = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=HISTORICAL_BACKFILL_DAYS)).date()
        assert _snapshot_start_date("not-a-date") == expected


class TestGetSnapshotRows:
    def test_resume_picks_up_the_day_after_the_checkpoint(self) -> None:
        last_day = _last_published_snapshot_date(datetime.datetime.now(datetime.UTC))
        checkpoint = last_day - datetime.timedelta(days=1)
        watermark = checkpoint - datetime.timedelta(days=1)
        result = _driver().run(
            "listings_historical",
            [_response({"data": [{"id": 1}]})],
            resume_state=CoinMarketCapResumeConfig(last_snapshot_date=checkpoint.isoformat()),
            incremental_field="snapshot_date",
            db_incremental_field_last_value=watermark.isoformat(),
        )
        assert result.params("date") == [last_day.isoformat()]
        assert result.rows == [{"id": 1, "snapshot_date": last_day.isoformat()}]
        assert result.raised is None


class TestBatchEndpointErrors:
    def test_a_plan_refusal_matches_a_non_retryable_error(self) -> None:
        # CoinMarketCap answers 403 when the plan doesn't cover an endpoint. Retrying can never
        # satisfy that, so the raised message has to match one of the source's declared patterns.
        result = _driver().run(
            "ohlcv_historical",
            [
                _response({"data": [{"id": 1}]}),
                _response({"status": {"error_code": 1006}}, status_code=403),
            ],
        )

        assert isinstance(result.raised, Exception)
        assert any(key in str(result.raised) for key in CoinMarketCapSource().get_non_retryable_errors())
