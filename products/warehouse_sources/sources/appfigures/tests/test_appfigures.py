from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.appfigures import (
    AppfiguresResumeConfig,
    _flatten_ranks,
    _flatten_report,
    _to_date_str,
    check_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.source import AppfiguresSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appfigures import (
    AppfiguresSourceConfig,
)

_PAGE_LIMIT_REASON = (
    "page * count must be less than or equal to 10000. Please request fewer products or a smaller date range."
)


def _driver(aso_countries: str | None = None) -> SourceDriver:
    return SourceDriver(
        AppfiguresSource(), AppfiguresSourceConfig(personal_access_token="pat", aso_countries=aso_countries)
    )


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
    def test_to_date_str(self, value: Any, expected: str | None) -> None:
        assert _to_date_str(value) == expected

    @pytest.mark.parametrize("value", ["2024-01", "not-a-date", "garbage123"])
    def test_to_date_str_raises_on_unparseable_fragment(self, value: str) -> None:
        with pytest.raises(ValueError, match="Could not derive a yyyy-mm-dd date"):
            _to_date_str(value)


class TestFlattenReport:
    def test_keyed_by_date_becomes_sorted_rows_with_date_injected(self) -> None:
        body = {
            "2024-01-02": {"downloads": 5, "revenue": 1.0},
            "2024-01-01": {"downloads": 3, "revenue": 0.5},
        }
        rows = _flatten_report(body)
        assert rows == [
            {"date": "2024-01-01", "downloads": 3, "revenue": 0.5},
            {"date": "2024-01-02", "downloads": 5, "revenue": 1.0},
        ]

    def test_non_dict_input_returns_empty(self) -> None:
        assert _flatten_report([1, 2, 3]) == []


class TestIterObject:
    def test_products_object_flattened_to_list_of_values(self) -> None:
        body = {"42": {"id": 42, "name": "App A"}, "7": {"id": 7, "name": "App B"}}
        result = _driver().run("products", [ScriptedResponse(json=body)])
        assert result.raised is None
        assert len(result.items) == 1
        assert {row["id"] for row in result.rows} == {42, 7}


class TestIterPaged:
    def test_incremental_sets_start_param_from_watermark(self) -> None:
        body = {"total": 0, "pages": 1, "this_page": 1, "reviews": []}
        result = _driver().run(
            "reviews",
            [ScriptedResponse(json=body)],
            incremental_field="date",
            db_incremental_field_last_value=datetime(2024, 5, 1, 12, 0, tzinfo=UTC),
        )
        assert result.raised is None
        assert result.params("start") == ["2024-05-01"]

    def test_page_limit_stops_and_keeps_rows_gathered_so_far(self) -> None:
        # A backlog deep enough that offset pagination would cross Appfigures' page*count<=10000
        # cap. Page 1 succeeds; page 2 hits the cap. get_rows must yield page 1's rows and NOT raise
        # (the reported bug turned this benign boundary into a fatal HTTPError).
        result = _driver().run(
            "reviews",
            [
                ScriptedResponse(json={"total": 50000, "pages": 100, "this_page": 1, "reviews": [{"id": "a"}]}),
                ScriptedResponse(status=400, body=_PAGE_LIMIT_REASON.encode()),
            ],
        )
        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a"]
        assert len(result.requests) == 2


class TestIterReport:
    @time_machine.travel("2024-02-15", tick=False)
    def test_windows_date_range_into_chunks(self) -> None:
        result = _driver().run(
            "sales_report",
            [
                ScriptedResponse(json={"2024-01-01": {"downloads": 1}}),
                ScriptedResponse(json={"2024-01-31": {"downloads": 2}}),
            ],
            incremental_field="date",
            db_incremental_field_last_value=date(2024, 1, 1),
        )
        # 30-day windows: [01-01..01-30], then [01-31..02-15] (clamped to today).
        assert result.raised is None
        assert list(zip(result.params("start_date"), result.params("end_date"))) == [
            ("2024-01-01", "2024-01-30"),
            ("2024-01-31", "2024-02-15"),
        ]
        assert [row["date"] for row in result.rows] == ["2024-01-01", "2024-01-31"]
        # State saved after the first window, pointing at the next window's start.
        assert result.saved_states == [AppfiguresResumeConfig(window_start="2024-01-31")]


def _ranks_body(dates: list[str], series: list[dict[str, Any]]) -> dict[str, Any]:
    return {"start_date": dates[0], "end_date": dates[-1], "dates": dates, "data": series}


class TestFlattenRanks:
    def test_series_arrays_shorter_than_dates_do_not_index_error(self) -> None:
        body = _ranks_body(
            ["2024-01-01", "2024-01-02"],
            [{"country": "US", "product_id": 1, "category": {"id": 12}, "positions": [4], "deltas": []}],
        )
        rows = _flatten_ranks(body)
        assert [(row["date"], row["position"], row["delta"]) for row in rows] == [("2024-01-01", 4, None)]

    @pytest.mark.parametrize("body", [None, [], {"dates": ["2024-01-01"]}, {"data": [{"positions": [1]}]}])
    def test_missing_or_malformed_body_returns_empty(self, body: Any) -> None:
        assert _flatten_ranks(body) == []


class TestIterRanks:
    @time_machine.travel("2024-02-15", tick=False)
    def test_walks_date_windows_and_saves_state_after_each(self) -> None:
        series = [{"country": "US", "product_id": 1, "category": {"id": 12}, "positions": [5], "deltas": [0]}]
        result = _driver().run(
            "ranks",
            [
                ScriptedResponse(json={"1": {"id": 1, "type": "app"}}),
                ScriptedResponse(json=_ranks_body(["2024-01-01"], series)),
                ScriptedResponse(json=_ranks_body(["2024-01-31"], series)),
            ],
            incremental_field="date",
            db_incremental_field_last_value=date(2024, 1, 1),
        )
        assert result.raised is None
        assert result.paths[1:] == [
            "/v2/ranks/1/daily/2024-01-01/2024-01-30",
            "/v2/ranks/1/daily/2024-01-31/2024-02-15",
        ]
        assert result.saved_states == [AppfiguresResumeConfig(window_start="2024-01-31")]

    @time_machine.travel("2024-02-15", tick=False)
    def test_resume_starts_from_saved_window(self) -> None:
        result = _driver().run(
            "ranks",
            [
                ScriptedResponse(json={"1": {"id": 1, "type": "app"}}),
                ScriptedResponse(json={}),
            ],
            resume_state=AppfiguresResumeConfig(window_start="2024-02-10"),
        )
        assert result.raised is None
        assert result.paths[1:] == ["/v2/ranks/1/daily/2024-02-10/2024-02-15"]

    def test_account_with_no_rankable_products_makes_no_ranks_request(self) -> None:
        result = _driver().run("ranks", [ScriptedResponse(json={"999": {"id": 999, "type": "inapp"}})])
        assert result.raised is None
        assert result.items == []
        assert result.paths == ["/v2/products/mine"]


def _aso_page(results: list[dict[str, Any]], page: int = 1, total_pages: int = 1) -> dict[str, Any]:
    return {
        "metadata": {"resultset": {"count": 500, "page": page, "total_pages": total_pages, "total_count": 1}},
        "results": results,
    }


class TestIterAso:
    @time_machine.travel("2024-02-15", tick=False)
    def test_resume_target_missing_from_catalog_starts_over(self) -> None:
        result = _driver("US").run(
            "aso_keywords",
            [
                ScriptedResponse(json={"1": {"id": 1, "type": "app"}}),
                ScriptedResponse(json=_aso_page([])),
            ],
            resume_state=AppfiguresResumeConfig(aso_target="404:US", next_page=7),
        )
        assert result.raised is None
        assert [(request.param("products"), request.param("page")) for request in result.requests[1:]] == [("1", "1")]

    @time_machine.travel("2024-02-15", tick=False)
    def test_page_limit_stops_the_target_and_moves_to_the_next(self) -> None:
        result = _driver("US").run(
            "aso_keywords",
            [
                ScriptedResponse(json={"1": {"id": 1, "type": "app"}, "2": {"id": 2, "type": "app"}}),
                ScriptedResponse(json=_aso_page([{"keyword_id": "k1"}], page=1, total_pages=9)),
                ScriptedResponse(status=400, body=_PAGE_LIMIT_REASON.encode()),
                ScriptedResponse(json=_aso_page([{"keyword_id": "k2"}])),
            ],
        )
        assert result.raised is None
        assert [row["keyword_id"] for row in result.rows] == ["k1", "k2"]
        assert len(result.requests) == 4

    def test_account_with_no_rankable_products_makes_no_aso_request(self) -> None:
        result = _driver().run("aso_keywords", [ScriptedResponse(json={"9": {"id": 9, "type": "inapp"}})])
        assert result.raised is None
        assert result.items == []
        assert result.paths == ["/v2/products/mine"]


class TestIterAsoStats:
    @time_machine.travel("2024-02-15", tick=False)
    def test_one_row_per_target_with_identity_and_window(self) -> None:
        result = _driver("US").run(
            "aso_stats",
            [
                ScriptedResponse(json={"1": {"id": 1, "type": "app"}, "2": {"id": 2, "type": "app"}}),
                ScriptedResponse(json={"avg_position": 21, "top_5": 1, "total_keywords": 5}),
                ScriptedResponse(json={"avg_position": 21, "top_5": 1, "total_keywords": 5}),
            ],
        )
        assert result.raised is None
        assert [len(batch) for batch in result.items] == [1, 1]
        assert [(row["date"], row["product_id"], row["country"], row["avg_position"]) for row in result.rows] == [
            ("2024-02-15", "1", "US", 21),
            ("2024-02-15", "2", "US", 21),
        ]
        # /aso/stats spells its window start/end rather than start_date/end_date.
        assert (result.requests[1].param("start"), result.requests[1].param("end")) == ("2024-01-17", "2024-02-15")
        assert result.saved_states == [AppfiguresResumeConfig(aso_target="2:US")]

    @time_machine.travel("2024-02-15", tick=False)
    def test_resume_skips_targets_already_walked(self) -> None:
        result = _driver("US").run(
            "aso_stats",
            [
                ScriptedResponse(json={str(index): {"id": index, "type": "app"} for index in (1, 2, 3)}),
                ScriptedResponse(json={"avg_position": 1}),
            ],
            resume_state=AppfiguresResumeConfig(aso_target="3:US"),
        )
        assert result.raised is None
        assert [request.param("products") for request in result.requests[1:]] == ["3"]


class TestCheckCredentials:
    @pytest.mark.parametrize("status", [403])
    def test_returns_status_code(self, status: int) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert check_credentials("pat", "/products/mine") == status
        assert network.requests_log[0].path == "/v2/products/mine"

    def test_network_failure_returns_none(self) -> None:
        with scripted_network([ConnectionResetError("boom")]):
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
    def test_response_shape(self, endpoint: str, primary_keys: list[str], partition_key: str | None) -> None:
        result = _driver().run(endpoint, always(ScriptedResponse(json={})))
        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == primary_keys
        assert result.response.partition_mode == ("datetime" if partition_key else None)
        assert result.response.partition_keys == ([partition_key] if partition_key else None)
        assert result.response.sort_mode == "asc"
