from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.appfigures import appfigures
from products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.appfigures import (
    AppfiguresResumeConfig,
    _flatten_ranks,
    _flatten_report,
    _to_date_str,
    appfigures_source,
    check_credentials,
    get_rows,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.appfigures"

_PAGE_LIMIT_REASON = (
    "page * count must be less than or equal to 10000. Please request fewer products or a smaller date range."
)


def _response(status_code: int, reason: str = "", text: str = "") -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.reason = reason
    response.text = text
    response.ok = status_code < 400
    return response


def _manager(resume: AppfiguresResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


class TestToDateStr:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, None),
            (datetime(2024, 3, 4, 2, 58, 14, tzinfo=UTC), "2024-03-04"),
            (datetime(2024, 3, 4, 23, 0, 0), "2024-03-04"),
            (date(2024, 3, 4), "2024-03-04"),
            ("2024-03-04T05:06:07", "2024-03-04"),
            ("2024-03-04", "2024-03-04"),
        ],
    )
    def test_to_date_str(self, value: Any, expected: str | None):
        assert _to_date_str(value) == expected

    @pytest.mark.parametrize("value", ["2024-01", "not-a-date", "garbage123"])
    def test_to_date_str_raises_on_unparseable_fragment(self, value: str):
        with pytest.raises(ValueError, match="Could not derive a yyyy-mm-dd date"):
            _to_date_str(value)


class TestFlattenReport:
    def test_keyed_by_date_becomes_sorted_rows_with_date_injected(self):
        body = {
            "2024-01-02": {"downloads": 5, "revenue": 1.0},
            "2024-01-01": {"downloads": 3, "revenue": 0.5},
        }
        rows = _flatten_report(body)
        assert rows == [
            {"date": "2024-01-01", "downloads": 3, "revenue": 0.5},
            {"date": "2024-01-02", "downloads": 5, "revenue": 1.0},
        ]

    def test_non_dict_input_returns_empty(self):
        assert _flatten_report([1, 2, 3]) == []


class TestIterObject:
    def test_products_object_flattened_to_list_of_values(self):
        body = {"42": {"id": 42, "name": "App A"}, "7": {"id": 7, "name": "App B"}}
        with mock.patch(f"{_MODULE}._fetch", return_value=body):
            batches = list(
                get_rows(token="pat", endpoint="products", logger=mock.MagicMock(), resumable_source_manager=_manager())
            )
        assert len(batches) == 1
        assert {row["id"] for row in batches[0]} == {42, 7}


class TestIterPaged:
    def test_incremental_sets_start_param_from_watermark(self):
        body = {"total": 0, "pages": 1, "this_page": 1, "reviews": []}
        with mock.patch(f"{_MODULE}._fetch", return_value=body) as fetch:
            list(
                get_rows(
                    token="pat",
                    endpoint="reviews",
                    logger=mock.MagicMock(),
                    resumable_source_manager=_manager(),
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2024, 5, 1, 12, 0, tzinfo=UTC),
                )
            )
        assert fetch.call_args_list[0].args[2]["start"] == "2024-05-01"

    def test_page_limit_stops_and_keeps_rows_gathered_so_far(self):
        # A backlog deep enough that offset pagination would cross Appfigures' page*count<=10000
        # cap. Page 1 succeeds; page 2 hits the cap. get_rows must yield page 1's rows and NOT raise
        # (the reported bug turned this benign boundary into a fatal HTTPError).
        page1 = _response(200)
        page1.json.return_value = {"total": 50000, "pages": 100, "this_page": 1, "reviews": [{"id": "a"}]}
        page_limit = _response(400, reason=_PAGE_LIMIT_REASON)

        session = mock.MagicMock()
        session.get.side_effect = [page1, page_limit]

        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            batches = list(
                get_rows(
                    token="pat",
                    endpoint="reviews",
                    logger=mock.MagicMock(),
                    resumable_source_manager=_manager(),
                )
            )

        assert [row["id"] for batch in batches for row in batch] == ["a"]
        assert session.get.call_count == 2


class TestIterReport:
    @time_machine.travel("2024-02-15", tick=False)
    def test_windows_date_range_into_chunks(self):
        body_by_window: dict[str, dict] = {
            "2024-01-01": {"2024-01-01": {"downloads": 1}},
            "2024-01-31": {"2024-01-31": {"downloads": 2}},
        }

        def fake_fetch(_session, _url, params, _logger):
            return body_by_window[params["start_date"]]

        manager = _manager()
        with mock.patch(f"{_MODULE}._fetch", side_effect=fake_fetch) as fetch:
            batches = list(
                get_rows(
                    token="pat",
                    endpoint="sales_report",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=date(2024, 1, 1),
                )
            )
        windows = [(c.args[2]["start_date"], c.args[2]["end_date"]) for c in fetch.call_args_list]
        # 30-day windows: [01-01..01-30], then [01-31..02-15] (clamped to today).
        assert windows == [("2024-01-01", "2024-01-30"), ("2024-01-31", "2024-02-15")]
        assert [r["date"] for batch in batches for r in batch] == ["2024-01-01", "2024-01-31"]
        # State saved after the first window, pointing at the next window's start.
        manager.save_state.assert_called_once_with(AppfiguresResumeConfig(window_start="2024-01-31"))


def _ranks_body(dates: list[str], series: list[dict[str, Any]]) -> dict[str, Any]:
    return {"start_date": dates[0], "end_date": dates[-1], "dates": dates, "data": series}


class TestFlattenRanks:
    def test_series_arrays_shorter_than_dates_do_not_index_error(self):
        body = _ranks_body(
            ["2024-01-01", "2024-01-02"],
            [{"country": "US", "product_id": 1, "category": {"id": 12}, "positions": [4], "deltas": []}],
        )
        rows = _flatten_ranks(body)
        assert [(r["date"], r["position"], r["delta"]) for r in rows] == [("2024-01-01", 4, None)]

    @pytest.mark.parametrize("body", [None, [], {"dates": ["2024-01-01"]}, {"data": [{"positions": [1]}]}])
    def test_missing_or_malformed_body_returns_empty(self, body: Any):
        assert _flatten_ranks(body) == []


class TestIterRanks:
    @time_machine.travel("2024-02-15", tick=False)
    def test_walks_date_windows_and_saves_state_after_each(self):
        windows: list[tuple[str, str]] = []

        def fake_fetch(_session, url, _params, _logger):
            if url.endswith(appfigures.PRODUCTS_PATH):
                return {"1": {"id": 1, "type": "app"}}
            _, _, start, end = url.split("/ranks/")[1].split("/")
            windows.append((start, end))
            return _ranks_body(
                [start], [{"country": "US", "product_id": 1, "category": {"id": 12}, "positions": [5], "deltas": [0]}]
            )

        manager = _manager()
        with mock.patch(f"{_MODULE}._fetch", side_effect=fake_fetch):
            list(
                get_rows(
                    token="pat",
                    endpoint="ranks",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=date(2024, 1, 1),
                )
            )

        assert windows == [("2024-01-01", "2024-01-30"), ("2024-01-31", "2024-02-15")]
        manager.save_state.assert_called_once_with(AppfiguresResumeConfig(window_start="2024-01-31"))

    @time_machine.travel("2024-02-15", tick=False)
    def test_resume_starts_from_saved_window(self):
        starts: list[str] = []

        def fake_fetch(_session, url, _params, _logger):
            if url.endswith(appfigures.PRODUCTS_PATH):
                return {"1": {"id": 1, "type": "app"}}
            starts.append(url.split("/ranks/")[1].split("/")[2])
            return {}

        with mock.patch(f"{_MODULE}._fetch", side_effect=fake_fetch):
            list(
                get_rows(
                    token="pat",
                    endpoint="ranks",
                    logger=mock.MagicMock(),
                    resumable_source_manager=_manager(AppfiguresResumeConfig(window_start="2024-02-10")),
                )
            )
        assert starts == ["2024-02-10"]

    def test_account_with_no_rankable_products_makes_no_ranks_request(self):
        def fake_fetch(_session, url, _params, _logger):
            assert url.endswith(appfigures.PRODUCTS_PATH)
            return {"999": {"id": 999, "type": "inapp"}}

        with mock.patch(f"{_MODULE}._fetch", side_effect=fake_fetch) as fetch:
            batches = list(
                get_rows(token="pat", endpoint="ranks", logger=mock.MagicMock(), resumable_source_manager=_manager())
            )
        assert batches == []
        assert fetch.call_count == 1


def _aso_page(results: list[dict[str, Any]], page: int = 1, total_pages: int = 1) -> dict[str, Any]:
    return {
        "metadata": {"resultset": {"count": 500, "page": page, "total_pages": total_pages, "total_count": 1}},
        "results": results,
    }


class TestIterAso:
    @time_machine.travel("2024-02-15", tick=False)
    def test_resume_target_missing_from_catalog_starts_over(self):
        def fake_fetch(_session, url, _params, _logger):
            if url.endswith(appfigures.PRODUCTS_PATH):
                return {"1": {"id": 1, "type": "app"}}
            return _aso_page([])

        with mock.patch(f"{_MODULE}._fetch", side_effect=fake_fetch) as fetch:
            list(
                get_rows(
                    token="pat",
                    endpoint="aso_keywords",
                    logger=mock.MagicMock(),
                    resumable_source_manager=_manager(AppfiguresResumeConfig(aso_target="404:US", next_page=7)),
                    aso_countries="US",
                )
            )
        assert [(c.args[2]["products"], c.args[2]["page"]) for c in fetch.call_args_list[1:]] == [("1", 1)]

    @time_machine.travel("2024-02-15", tick=False)
    def test_page_limit_stops_the_target_and_moves_to_the_next(self):
        products = _response(200)
        products.json.return_value = {"1": {"id": 1, "type": "app"}, "2": {"id": 2, "type": "app"}}
        first_page = _response(200)
        first_page.json.return_value = _aso_page([{"keyword_id": "k1"}], page=1, total_pages=9)
        page_limit = _response(400, reason=_PAGE_LIMIT_REASON)
        second_target = _response(200)
        second_target.json.return_value = _aso_page([{"keyword_id": "k2"}])

        session = mock.MagicMock()
        session.get.side_effect = [products, first_page, page_limit, second_target]

        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            batches = list(
                get_rows(
                    token="pat",
                    endpoint="aso_keywords",
                    logger=mock.MagicMock(),
                    resumable_source_manager=_manager(),
                    aso_countries="US",
                )
            )

        assert [row["keyword_id"] for batch in batches for row in batch] == ["k1", "k2"]
        assert session.get.call_count == 4

    def test_account_with_no_rankable_products_makes_no_aso_request(self):
        with mock.patch(f"{_MODULE}._fetch", return_value={"9": {"id": 9, "type": "inapp"}}) as fetch:
            batches = list(
                get_rows(
                    token="pat",
                    endpoint="aso_keywords",
                    logger=mock.MagicMock(),
                    resumable_source_manager=_manager(),
                )
            )
        assert batches == []
        assert fetch.call_count == 1


class TestIterAsoStats:
    @time_machine.travel("2024-02-15", tick=False)
    def test_one_row_per_target_with_identity_and_window(self):
        def fake_fetch(_session, url, params, _logger):
            if url.endswith(appfigures.PRODUCTS_PATH):
                return {"1": {"id": 1, "type": "app"}, "2": {"id": 2, "type": "app"}}
            return {"avg_position": 21, "top_5": 1, "total_keywords": 5, "_asked": params["products"]}

        manager = _manager()
        with mock.patch(f"{_MODULE}._fetch", side_effect=fake_fetch) as fetch:
            batches = list(
                get_rows(
                    token="pat",
                    endpoint="aso_stats",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    aso_countries="US",
                )
            )

        assert [len(batch) for batch in batches] == [1, 1]
        rows = [row for batch in batches for row in batch]
        assert [(r["date"], r["product_id"], r["country"], r["avg_position"]) for r in rows] == [
            ("2024-02-15", "1", "US", 21),
            ("2024-02-15", "2", "US", 21),
        ]
        # /aso/stats spells its window start/end rather than start_date/end_date.
        params = fetch.call_args_list[1].args[2]
        assert (params["start"], params["end"]) == ("2024-01-17", "2024-02-15")
        manager.save_state.assert_called_once_with(AppfiguresResumeConfig(aso_target="2:US"))

    @time_machine.travel("2024-02-15", tick=False)
    def test_resume_skips_targets_already_walked(self):
        def fake_fetch(_session, url, _params, _logger):
            if url.endswith(appfigures.PRODUCTS_PATH):
                return {str(index): {"id": index, "type": "app"} for index in (1, 2, 3)}
            return {"avg_position": 1}

        with mock.patch(f"{_MODULE}._fetch", side_effect=fake_fetch) as fetch:
            list(
                get_rows(
                    token="pat",
                    endpoint="aso_stats",
                    logger=mock.MagicMock(),
                    resumable_source_manager=_manager(AppfiguresResumeConfig(aso_target="3:US")),
                    aso_countries="US",
                )
            )
        assert [c.args[2]["products"] for c in fetch.call_args_list[1:]] == ["3"]


class TestCheckCredentials:
    @pytest.mark.parametrize("status", [200, 401, 403, 500])
    def test_returns_status_code(self, status):
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status)
        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            assert check_credentials("pat", "/products/mine") == status

    def test_network_failure_returns_none(self):
        session = mock.MagicMock()
        session.get.side_effect = Exception("boom")
        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            assert check_credentials("pat") is None


class TestAppfiguresSourceResponse:
    @pytest.mark.parametrize(
        "endpoint,primary_keys,partition_key",
        [
            ("products", ["id"], "added_date"),
            ("reviews", ["id"], "date"),
            ("sales_report", ["date"], "date"),
            ("revenue_report", ["date"], "date"),
            ("ranks", ["date", "product_id", "country", "category_id", "category_subtype"], "date"),
            ("aso_keywords", ["date", "product_id", "country", "keyword_id"], "date"),
            ("aso_stats", ["date", "product_id", "country"], "date"),
            # The /data lookups carry no date field, so they sync unpartitioned.
            ("stores", ["id"], None),
            ("categories", ["id"], None),
            ("countries", ["iso"], None),
        ],
    )
    def test_response_shape(self, endpoint, primary_keys, partition_key):
        response = appfigures_source(
            token="pat",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=_manager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_mode == ("datetime" if partition_key else None)
        assert response.partition_keys == ([partition_key] if partition_key else None)
        assert response.sort_mode == "asc"
