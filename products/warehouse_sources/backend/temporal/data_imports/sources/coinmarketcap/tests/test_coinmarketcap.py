import json
import datetime
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.coinmarketcap import (
    API_KEY_HEADER,
    CoinMarketCapPaginator,
    CoinMarketCapResumeConfig,
    _history_start,
    _last_published_snapshot_date,
    _rows_from,
    _snapshot_start_date,
    coinmarketcap_source,
    get_batch_rows,
    get_resource,
    get_snapshot_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.settings import (
    COINMARKETCAP_BATCH_ENDPOINTS,
    COINMARKETCAP_ENDPOINTS,
    HISTORICAL_BACKFILL_DAYS,
    HISTORICAL_BATCH_SIZE,
    HISTORICAL_COIN_LIMIT,
    HISTORICAL_EXCHANGE_LIMIT,
    LISTINGS_HISTORICAL_RANK_LIMIT,
    METADATA_BATCH_SIZE,
    PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.source import CoinMarketCapSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


def _full_page() -> list[dict[str, Any]]:
    return [{"id": i} for i in range(PAGE_SIZE)]


class TestCoinMarketCapPaginator:
    def test_initial_state_is_one_based(self) -> None:
        paginator = CoinMarketCapPaginator()
        # CoinMarketCap's `start` is 1-based; start=0 is rejected with a 400.
        assert paginator.offset == 1
        assert paginator.limit == PAGE_SIZE
        assert paginator.has_next_page is True

    def test_init_request_emits_start_and_limit(self) -> None:
        paginator = CoinMarketCapPaginator()
        request = Request(method="GET", url="https://pro-api.coinmarketcap.com/v1/cryptocurrency/map")
        paginator.init_request(request)
        assert request.params["start"] == 1
        assert request.params["limit"] == PAGE_SIZE

    def test_advances_start_by_limit_on_full_page(self) -> None:
        paginator = CoinMarketCapPaginator()
        paginator.update_state(MagicMock(), _full_page())
        assert paginator.offset == 1 + PAGE_SIZE
        assert paginator.has_next_page is True

    def test_stops_on_short_page(self) -> None:
        paginator = CoinMarketCapPaginator()
        paginator.update_state(MagicMock(), [{"id": 1}])
        assert paginator.has_next_page is False

    def test_stops_on_empty_page(self) -> None:
        # An out-of-range `start` returns an empty `data` list with HTTP 200.
        paginator = CoinMarketCapPaginator()
        paginator.update_state(MagicMock(), [])
        assert paginator.has_next_page is False

    def test_get_resume_state_when_next_page(self) -> None:
        paginator = CoinMarketCapPaginator()
        paginator.update_state(MagicMock(), _full_page())
        assert paginator.get_resume_state() == {"start": 1 + PAGE_SIZE}

    def test_get_resume_state_none_on_terminal_page(self) -> None:
        paginator = CoinMarketCapPaginator()
        paginator.update_state(MagicMock(), [])
        assert paginator.get_resume_state() is None

    def test_set_resume_state_round_trip(self) -> None:
        paginator = CoinMarketCapPaginator()
        paginator.set_resume_state({"start": 5001})
        assert paginator.offset == 5001
        assert paginator.has_next_page is True

        request = Request(method="GET", url="https://pro-api.coinmarketcap.com/v1/cryptocurrency/map")
        paginator.init_request(request)
        assert request.params["start"] == 5001

    def test_set_resume_state_ignores_missing_start(self) -> None:
        paginator = CoinMarketCapPaginator()
        paginator.set_resume_state({})
        assert paginator.offset == 1


class TestGetResource:
    @pytest.mark.parametrize("endpoint", list(COINMARKETCAP_ENDPOINTS))
    def test_resource_shape(self, endpoint: str) -> None:
        resource = get_resource(endpoint)
        config = COINMARKETCAP_ENDPOINTS[endpoint]

        assert resource["name"] == endpoint
        assert resource["table_name"] == endpoint
        assert resource["write_disposition"] == "replace"
        assert resource["table_format"] == "delta"

        endpoint_def = cast(dict[str, Any], resource["endpoint"])
        assert endpoint_def["path"] == config.path
        assert endpoint_def["path"].startswith("/v1/")
        assert endpoint_def["data_selector"] == "data"

    @pytest.mark.parametrize(
        "endpoint",
        ["cryptocurrency_map", "listings_latest", "fiat_map", "exchange_map", "exchange_listings_latest"],
    )
    def test_paginated_endpoints_pass_a_stable_sort(self, endpoint: str) -> None:
        # A stable `sort` keeps offset pagination from skipping/duplicating rows mid-sync.
        endpoint_def = cast(dict[str, Any], get_resource(endpoint)["endpoint"])
        assert "sort" in endpoint_def["params"]


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestCoinMarketCapSourceResumeBehavior:
    """End-to-end resume behaviour of ``coinmarketcap_source`` via ``rest_api_resource``."""

    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response]
    ) -> tuple[MagicMock, list[dict[str, Any]]]:
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.coinmarketcap.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            source = coinmarketcap_source(
                api_key="test-key",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                logger=MagicMock(),
                resumable_source_manager=manager,
            )
            list(cast(Iterable[Any], source.items()))
            return mock_session, sent_params

    def _page_body(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        return {"data": items, "status": {"error_code": 0, "error_message": None}}

    @pytest.mark.parametrize("endpoint", ["cryptocurrency_map", "listings_latest", "fiat_map"])
    def test_fresh_run_saves_start_after_each_non_terminal_page(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(self._page_body(_full_page())),
            _make_http_response(self._page_body([{"id": "x"}])),
        ]
        _, sent_params = self._drive(endpoint, manager, responses)

        # First request starts at 1; the second carries the advanced start.
        assert [p.get("start") for p in sent_params] == [1, 1 + PAGE_SIZE]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [CoinMarketCapResumeConfig(start=1 + PAGE_SIZE)]

    def test_resume_seeds_paginator_with_saved_start(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = CoinMarketCapResumeConfig(start=1 + PAGE_SIZE)

        responses = [
            _make_http_response(self._page_body([{"id": "resumed"}])),
        ]
        _, sent_params = self._drive("cryptocurrency_map", manager, responses)

        assert [p.get("start") for p in sent_params] == [1 + PAGE_SIZE]
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(self._page_body([{"id": "only"}])),
        ]
        self._drive("cryptocurrency_map", manager, responses)

        manager.save_state.assert_not_called()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(self._page_body([{"id": "a"}])),
        ]
        self._drive("cryptocurrency_map", manager, responses)

        manager.load_state.assert_not_called()


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
            (401, False),
            (429, False),
            (500, False),
        ],
    )
    def test_status_code_mapping(self, status_code: int, expected_valid: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.coinmarketcap.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            response = MagicMock()
            response.status_code = status_code
            mock_session.get.return_value = response

            valid, error = validate_credentials("test-key")
            assert valid is expected_valid
            if expected_valid:
                assert error is None
            else:
                assert error is not None

    def test_sends_key_in_header(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.coinmarketcap.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            response = MagicMock()
            response.status_code = 200
            mock_session.get.return_value = response

            validate_credentials("test-key")

            headers = mock_session.get.call_args.kwargs["headers"]
            assert headers[API_KEY_HEADER] == "test-key"
            assert mock_session.get.call_args.kwargs["allow_redirects"] is False

    def test_network_error_returns_message(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.coinmarketcap.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.get.side_effect = Exception("boom")
            valid, error = validate_credentials("test-key")
            assert valid is False
            assert error == "boom"


def _make_batch_response(body: dict[str, Any], status_code: int = 200, url: str = "") -> Response:
    resp = _make_http_response(body, status_code=status_code)
    resp.url = url
    resp.reason = "Forbidden" if status_code == 403 else "OK"
    return resp


class _FakeSession:
    """Records every `_get` call and replays a queued list of responses."""

    def __init__(self, responses: list[Response]) -> None:
        self.responses = iter(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, params: dict[str, Any] | None = None, **_kwargs: Any) -> Response:
        self.calls.append((url, dict(params or {})))
        return next(self.responses)


def _patch_session(responses: list[Response]) -> tuple[Any, _FakeSession]:
    session = _FakeSession(responses)
    patcher = patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.coinmarketcap.make_tracked_session",
        return_value=session,
    )
    return patcher, session


class TestRowsFrom:
    def test_object_map_keyed_by_id(self) -> None:
        rows = _rows_from("object_map", {"1": {"id": 1, "symbol": "BTC"}, "1027": {"id": 1027, "symbol": "ETH"}})
        assert [row["id"] for row in rows] == [1, 1027]

    def test_object_map_unwraps_a_single_object(self) -> None:
        # A single-id request returns the record directly rather than an id-keyed map.
        assert _rows_from("object_map", {"id": 1, "symbol": "BTC"}) == [{"id": 1, "symbol": "BTC"}]

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
    def test_uses_the_watermark_when_one_is_set(self) -> None:
        import datetime

        watermark = datetime.datetime(2026, 3, 1, 12, 30, tzinfo=datetime.UTC)
        assert _history_start(watermark) == watermark.isoformat()

    def test_falls_back_to_the_backfill_window(self) -> None:
        import datetime

        expected = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=HISTORICAL_BACKFILL_DAYS)).date()
        assert _history_start(None) == expected.isoformat()

    def test_passes_a_string_watermark_through(self) -> None:
        assert _history_start("2026-01-01T00:00:00.000Z") == "2026-01-01T00:00:00.000Z"


class TestGetBatchRows:
    def _manager(self, resume_config: CoinMarketCapResumeConfig | None = None) -> MagicMock:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = resume_config is not None
        manager.load_state.return_value = resume_config
        return manager

    def _run(
        self,
        endpoint: str,
        responses: list[Response],
        manager: MagicMock,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[dict[str, Any]], _FakeSession]:
        patcher, session = _patch_session(responses)
        with patcher:
            batches = list(
                get_batch_rows(
                    api_key="test-key",
                    endpoint=endpoint,
                    logger=MagicMock(),
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=db_incremental_field_last_value,
                )
            )
        return [row for batch in batches for row in batch], session

    def test_global_metrics_makes_one_unbatched_request(self) -> None:
        manager = self._manager()
        rows, session = self._run(
            "global_metrics_quotes_historical",
            [_make_batch_response({"data": {"quotes": [{"timestamp": "2026-01-01T00:00:00.000Z"}]}})],
            manager,
        )

        assert rows == [{"timestamp": "2026-01-01T00:00:00.000Z"}]
        assert len(session.calls) == 1
        url, params = session.calls[0]
        assert url.endswith("/v1/global-metrics/quotes/historical")
        assert "id" not in params
        assert params["interval"] == "daily"
        # No coin batches to resume through, so nothing should be checkpointed.
        manager.save_state.assert_not_called()

    def test_full_refresh_sends_the_backfill_window_not_a_watermark(self) -> None:
        _, session = self._run(
            "global_metrics_quotes_historical",
            [_make_batch_response({"data": {"quotes": []}})],
            self._manager(),
        )
        assert session.calls[0][1]["time_start"] == _history_start(None)

    def test_incremental_sends_the_watermark(self) -> None:
        import datetime

        watermark = datetime.datetime(2026, 3, 1, tzinfo=datetime.UTC)
        _, session = self._run(
            "global_metrics_quotes_historical",
            [_make_batch_response({"data": {"quotes": []}})],
            self._manager(),
            db_incremental_field_last_value=watermark,
        )
        assert session.calls[0][1]["time_start"] == watermark.isoformat()

    def test_info_batches_every_id_in_the_map(self) -> None:
        map_page = {"data": [{"id": coin_id} for coin_id in range(1, METADATA_BATCH_SIZE + 3)]}
        manager = self._manager()
        rows, session = self._run(
            "cryptocurrency_info",
            [
                _make_batch_response(map_page),
                _make_batch_response({"data": {"1": {"id": 1}}}),
                _make_batch_response({"data": {"251": {"id": 251}}}),
            ],
            manager,
        )

        map_call, first_batch, second_batch = session.calls
        assert map_call[0].endswith("/v1/cryptocurrency/map")
        assert first_batch[0].endswith("/v2/cryptocurrency/info")
        assert first_batch[1]["id"] == ",".join(str(i) for i in range(1, METADATA_BATCH_SIZE + 1))
        assert second_batch[1]["id"] == f"{METADATA_BATCH_SIZE + 1},{METADATA_BATCH_SIZE + 2}"
        assert [row["id"] for row in rows] == [1, 251]

        # Checkpointed after each batch is yielded, so a crash re-yields rather than skips.
        assert [call.args[0] for call in manager.save_state.call_args_list] == [
            CoinMarketCapResumeConfig(last_coin_id=METADATA_BATCH_SIZE),
            CoinMarketCapResumeConfig(last_coin_id=METADATA_BATCH_SIZE + 2),
        ]

    def test_info_walks_every_map_page(self) -> None:
        # The first page is full but carries one unusable row. The walk has to count the raw page,
        # or a single bad row ends it early and the table syncs an incomplete coin set.
        first_page = [{"id": i} for i in range(1, PAGE_SIZE)]
        first_page.append({"no_id": True})
        manager = self._manager()
        _, session = self._run(
            "cryptocurrency_info",
            [
                _make_batch_response({"data": first_page}),
                _make_batch_response({"data": [{"id": PAGE_SIZE + 1}]}),
                *[_make_batch_response({"data": {}}) for _ in range(21)],
            ],
            manager,
        )

        map_calls = [params for url, params in session.calls if url.endswith("/v1/cryptocurrency/map")]
        assert [params["start"] for params in map_calls] == [1, 1 + PAGE_SIZE]

    def test_resume_skips_the_coins_already_yielded(self) -> None:
        map_page = {"data": [{"id": coin_id} for coin_id in range(1, METADATA_BATCH_SIZE + 3)]}
        manager = self._manager(CoinMarketCapResumeConfig(last_coin_id=METADATA_BATCH_SIZE))
        _, session = self._run(
            "cryptocurrency_info",
            [_make_batch_response(map_page), _make_batch_response({"data": {"251": {"id": 251}}})],
            manager,
        )

        info_calls = [params for url, params in session.calls if url.endswith("/v2/cryptocurrency/info")]
        assert len(info_calls) == 1
        assert info_calls[0]["id"] == f"{METADATA_BATCH_SIZE + 1},{METADATA_BATCH_SIZE + 2}"

    def test_resume_holds_its_place_when_a_coin_leaves_the_universe(self) -> None:
        # Id 5 is gone since the attempt that checkpointed. A position-based cursor would slide the
        # whole tail forward by one and skip a coin that was never yielded.
        remaining = [coin_id for coin_id in range(1, HISTORICAL_BATCH_SIZE + 2) if coin_id != 5]
        manager = self._manager(CoinMarketCapResumeConfig(last_coin_id=HISTORICAL_BATCH_SIZE))
        _, session = self._run(
            "quotes_historical",
            [
                _make_batch_response({"data": [{"id": coin_id} for coin_id in remaining]}),
                _make_batch_response({"data": {}}),
            ],
            manager,
        )

        batch_calls = [params for url, params in session.calls if url.endswith("/v3/cryptocurrency/quotes/historical")]
        assert len(batch_calls) == 1
        assert batch_calls[0]["id"] == str(HISTORICAL_BATCH_SIZE + 1)

    @pytest.mark.parametrize("endpoint", ["quotes_historical", "ohlcv_historical"])
    def test_historical_endpoints_rank_the_coin_universe_by_market_cap(self, endpoint: str) -> None:
        listings = {"data": [{"id": coin_id} for coin_id in range(HISTORICAL_BATCH_SIZE + 1, 0, -1)]}
        manager = self._manager()
        _, session = self._run(
            endpoint,
            [_make_batch_response(listings), _make_batch_response({"data": {}}), _make_batch_response({"data": {}})],
            manager,
        )

        universe_call, first_batch, second_batch = session.calls
        assert universe_call[0].endswith("/v1/cryptocurrency/listings/latest")
        assert universe_call[1]["sort"] == "market_cap"
        assert universe_call[1]["sort_dir"] == "desc"
        assert universe_call[1]["limit"] == HISTORICAL_COIN_LIMIT

        # Ids are batched in ascending id order, not in the rank order the listing returned, so a
        # resumed run picks up the same batches even after the ranking moves.
        assert first_batch[1]["id"] == ",".join(str(i) for i in range(1, HISTORICAL_BATCH_SIZE + 1))
        assert second_batch[1]["id"] == str(HISTORICAL_BATCH_SIZE + 1)
        assert first_batch[1]["time_start"] == _history_start(None)
        assert first_batch[0].endswith(COINMARKETCAP_BATCH_ENDPOINTS[endpoint].path)

    def test_exchange_info_batches_every_id_in_the_exchange_map(self) -> None:
        manager = self._manager()
        rows, session = self._run(
            "exchange_info",
            [
                _make_batch_response({"data": [{"id": 16}, {"id": 24}]}),
                _make_batch_response({"data": {"16": {"id": 16}, "24": {"id": 24}}}),
            ],
            manager,
        )

        map_call, info_call = session.calls
        # The ids come from the exchange map, not the cryptocurrency map.
        assert map_call[0].endswith("/v1/exchange/map")
        assert info_call[0].endswith("/v1/exchange/info")
        assert info_call[1]["id"] == "16,24"
        assert [row["id"] for row in rows] == [16, 24]

    def test_exchange_history_ranks_the_exchange_universe_by_volume(self) -> None:
        listings = {"data": [{"id": exchange_id} for exchange_id in range(HISTORICAL_BATCH_SIZE + 1, 0, -1)]}
        manager = self._manager()
        _, session = self._run(
            "exchange_quotes_historical",
            [_make_batch_response(listings), _make_batch_response({"data": {}}), _make_batch_response({"data": {}})],
            manager,
        )

        universe_call, first_batch, _ = session.calls
        # `market_cap` is not in this endpoint's sort enum — exchanges rank by traded volume.
        assert universe_call[0].endswith("/v1/exchange/listings/latest")
        assert universe_call[1]["sort"] == "volume_24h"
        assert universe_call[1]["sort_dir"] == "desc"
        assert universe_call[1]["limit"] == HISTORICAL_EXCHANGE_LIMIT

        assert first_batch[0].endswith("/v1/exchange/quotes/historical")
        assert first_batch[1]["id"] == ",".join(str(i) for i in range(1, HISTORICAL_BATCH_SIZE + 1))
        assert first_batch[1]["time_start"] == _history_start(None)


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
    def test_falls_back_to_the_backfill_window(self) -> None:
        expected = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=HISTORICAL_BACKFILL_DAYS)).date()
        assert _snapshot_start_date(None) == expected

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
    def _manager(self, resume_config: CoinMarketCapResumeConfig | None = None) -> MagicMock:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = resume_config is not None
        manager.load_state.return_value = resume_config
        return manager

    def _run(
        self,
        responses: list[Response],
        manager: MagicMock,
        now: Any,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[dict[str, Any]], _FakeSession]:
        patcher, session = _patch_session(responses)
        with (
            patcher,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.coinmarketcap._last_published_snapshot_date",
                return_value=now,
            ),
        ):
            batches = list(
                get_snapshot_rows(
                    api_key="test-key",
                    endpoint="listings_historical",
                    logger=MagicMock(),
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=db_incremental_field_last_value,
                )
            )
        return [row for batch in batches for row in batch], session

    def test_walks_one_request_per_day_from_the_watermark(self) -> None:
        manager = self._manager()
        rows, session = self._run(
            [
                _make_batch_response({"data": [{"id": 1, "cmc_rank": 1}]}),
                _make_batch_response({"data": [{"id": 1, "cmc_rank": 2}]}),
            ],
            manager,
            now=datetime.date(2026, 3, 2),
            db_incremental_field_last_value="2026-03-01",
        )

        assert [params["date"] for _, params in session.calls] == ["2026-03-01", "2026-03-02"]
        assert all(url.endswith("/v1/cryptocurrency/listings/historical") for url, _ in session.calls)
        assert session.calls[0][1]["limit"] == LISTINGS_HISTORICAL_RANK_LIMIT
        assert session.calls[0][1]["sort"] == "cmc_rank"

        # The response identifies its day only through last_updated, which repeats for a coin that
        # stopped trading, so the requested day is stamped on to keep the two days distinct.
        assert [row["snapshot_date"] for row in rows] == ["2026-03-01", "2026-03-02"]
        assert [row["cmc_rank"] for row in rows] == [1, 2]

    def test_re_requests_the_watermark_day(self) -> None:
        # A run cut short part-way through a day would otherwise leave the rest of that day's
        # ranking missing for good.
        _, session = self._run(
            [_make_batch_response({"data": []})],
            self._manager(),
            now=datetime.date(2026, 3, 1),
            db_incremental_field_last_value="2026-03-01",
        )
        assert [params["date"] for _, params in session.calls] == ["2026-03-01"]

    def test_checkpoints_each_day_after_yielding_it(self) -> None:
        manager = self._manager()
        self._run(
            [
                _make_batch_response({"data": [{"id": 1}]}),
                _make_batch_response({"data": [{"id": 1}]}),
            ],
            manager,
            now=datetime.date(2026, 3, 2),
            db_incremental_field_last_value="2026-03-01",
        )

        assert [call.args[0] for call in manager.save_state.call_args_list] == [
            CoinMarketCapResumeConfig(last_snapshot_date="2026-03-01"),
            CoinMarketCapResumeConfig(last_snapshot_date="2026-03-02"),
        ]

    def test_resume_picks_up_the_day_after_the_checkpoint(self) -> None:
        manager = self._manager(CoinMarketCapResumeConfig(last_snapshot_date="2026-03-02"))
        _, session = self._run(
            [_make_batch_response({"data": [{"id": 1}]})],
            manager,
            now=datetime.date(2026, 3, 3),
            db_incremental_field_last_value="2026-03-01",
        )
        assert [params["date"] for _, params in session.calls] == ["2026-03-03"]

    def test_makes_no_request_when_the_watermark_is_already_current(self) -> None:
        _, session = self._run(
            [],
            self._manager(),
            now=datetime.date(2026, 3, 1),
            db_incremental_field_last_value="2026-03-02",
        )
        assert session.calls == []


class TestBatchEndpointErrors:
    def test_a_plan_refusal_matches_a_non_retryable_error(self) -> None:
        # CoinMarketCap answers 403 when the plan doesn't cover an endpoint. Retrying can never
        # satisfy that, so the raised message has to match one of the source's declared patterns.
        patcher, _ = _patch_session(
            [
                _make_batch_response(
                    {"status": {"error_code": 1006}},
                    status_code=403,
                    url="https://pro-api.coinmarketcap.com/v2/cryptocurrency/ohlcv/historical",
                )
            ]
        )
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        with patcher, pytest.raises(Exception) as exc_info:
            list(
                get_batch_rows(
                    api_key="test-key",
                    endpoint="ohlcv_historical",
                    logger=MagicMock(),
                    resumable_source_manager=manager,
                )
            )

        assert any(key in str(exc_info.value) for key in CoinMarketCapSource().get_non_retryable_errors())
