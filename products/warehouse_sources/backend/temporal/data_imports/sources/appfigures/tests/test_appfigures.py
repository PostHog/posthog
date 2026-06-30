from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.appfigures import appfigures
from products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.appfigures import (
    AppfiguresResumeConfig,
    _flatten_report,
    _headers,
    _to_date_str,
    appfigures_source,
    check_credentials,
    get_rows,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.appfigures"


def _manager(resume: AppfiguresResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


class TestHeaders:
    def test_bearer_header(self):
        headers = _headers("pat_123")
        assert headers["Authorization"] == "Bearer pat_123"
        assert headers["Accept"] == "application/json"


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

    def test_non_dict_values_are_skipped(self):
        assert _flatten_report({"2024-01-01": {"downloads": 1}, "meta": "ignored"}) == [
            {"date": "2024-01-01", "downloads": 1}
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
    def test_walks_all_pages_using_pages_and_this_page(self):
        pages = [
            {"total": 3, "pages": 2, "this_page": 1, "reviews": [{"id": "a"}, {"id": "b"}]},
            {"total": 3, "pages": 2, "this_page": 2, "reviews": [{"id": "c"}]},
        ]
        # The transport mutates one params dict across pages, so snapshot the `page` per call.
        seen_pages: list[int] = []

        def fake_fetch(_session, _url, params, _logger):
            seen_pages.append(params["page"])
            return pages[len(seen_pages) - 1]

        manager = _manager()
        with mock.patch(f"{_MODULE}._fetch", side_effect=fake_fetch) as fetch:
            batches = list(
                get_rows(
                    token="pat",
                    endpoint="reviews",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                )
            )
        assert [r["id"] for batch in batches for r in batch] == ["a", "b", "c"]
        assert seen_pages == [1, 2]
        # First request uses the configured sort and page size.
        first_params = fetch.call_args_list[0].args[2]
        assert first_params["sort"] == "date"
        assert first_params["count"] == 500
        # State saved after yielding the first page, pointing at the next page to fetch.
        manager.save_state.assert_called_once_with(AppfiguresResumeConfig(next_page=2))

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

    def test_resume_starts_from_saved_page(self):
        body = {"total": 1, "pages": 3, "this_page": 3, "reviews": [{"id": "z"}]}
        with mock.patch(f"{_MODULE}._fetch", return_value=body) as fetch:
            list(
                get_rows(
                    token="pat",
                    endpoint="reviews",
                    logger=mock.MagicMock(),
                    resumable_source_manager=_manager(AppfiguresResumeConfig(next_page=3)),
                )
            )
        assert fetch.call_args_list[0].args[2]["page"] == 3


class TestIterReport:
    @freeze_time("2024-02-15")
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

    @freeze_time("2024-02-15")
    def test_report_request_sets_group_by_and_granularity(self):
        with mock.patch(f"{_MODULE}._fetch", return_value={}) as fetch:
            list(
                get_rows(
                    token="pat",
                    endpoint="sales_report",
                    logger=mock.MagicMock(),
                    resumable_source_manager=_manager(),
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=date(2024, 2, 1),
                )
            )
        params = fetch.call_args_list[0].args[2]
        assert params["group_by"] == "dates"
        assert params["granularity"] == "daily"

    @freeze_time("2024-02-15")
    def test_resume_starts_from_saved_window(self):
        with mock.patch(f"{_MODULE}._fetch", return_value={}) as fetch:
            list(
                get_rows(
                    token="pat",
                    endpoint="sales_report",
                    logger=mock.MagicMock(),
                    resumable_source_manager=_manager(AppfiguresResumeConfig(window_start="2024-02-10")),
                )
            )
        assert fetch.call_args_list[0].args[2]["start_date"] == "2024-02-10"


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
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]
        assert response.sort_mode == "asc"


class TestRetryableError:
    def test_retryable_error_is_exception(self):
        assert issubclass(appfigures.AppfiguresRetryableError, Exception)
