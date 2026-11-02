from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.chartmogul import (
    ChartMogulResumeConfig,
    _format_start_date,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.settings import (
    CHARTMOGUL_ENDPOINTS,
    METRICS_START_DATE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.source import ChartMogulSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.chartmogul import (
    ChartMogulSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(ChartMogulSource(), ChartMogulSourceConfig(api_key="key"))


def _page(
    data_key: str,
    items: list[dict[str, Any]],
    *,
    has_more: bool = False,
    cursor: str | None = None,
) -> ScriptedResponse:
    return ScriptedResponse(json={data_key: items, "has_more": has_more, "cursor": cursor})


class TestFormatStartDate:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14"),
            (date(2026, 3, 4), "2026-03-04"),
            ("2026-03-04", "2026-03-04"),
        ],
    )
    def test_format_start_date(self, value: object, expected: str) -> None:
        assert _format_start_date(value) == expected


class TestPagination:
    # subscription_events wraps its rows under its own resource name rather than "entries",
    # so it paginates through a different data selector.
    @pytest.mark.parametrize(
        "endpoint,data_key",
        [("customers", "entries"), ("subscription_events", "subscription_events")],
    )
    def test_paginates_across_cursors(self, endpoint: str, data_key: str) -> None:
        result = _driver().run(
            endpoint,
            [
                _page(data_key, [{"uuid": "a"}], has_more=True, cursor="c1"),
                _page(data_key, [{"uuid": "b"}]),
            ],
        )

        assert [row["uuid"] for row in result.rows] == ["a", "b"]
        assert result.params("per_page") == ["200", "200"]
        assert result.params("cursor") == [None, "c1"]
        # Checkpoint saved after the first page (points at the next page); final page ends it.
        assert result.saved_states == [ChartMogulResumeConfig(cursor="c1")]
        assert result.raised is None

    def test_stops_when_has_more_false_even_with_cursor(self) -> None:
        # ChartMogul may still return a cursor on the last page; termination is
        # gated on has_more, not cursor presence.
        result = _driver().run("customers", [_page("entries", [{"uuid": "a"}], cursor="c9")])

        assert [row["uuid"] for row in result.rows] == ["a"]
        assert len(result.requests) == 1
        assert result.saved_states == []
        assert result.raised is None

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "customers",
            [_page("entries", [{"uuid": "b"}])],
            resume_state=ChartMogulResumeConfig(cursor="resume-cursor"),
        )

        assert result.params("cursor") == ["resume-cursor"]
        assert result.raised is None


class TestIncrementalParams:
    def test_activities_incremental_sets_start_date(self) -> None:
        result = _driver().run(
            "activities",
            [_page("entries", [{"uuid": "a"}])],
            incremental_field="date",
            db_incremental_field_last_value=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        )

        assert result.params("start-date") == ["2026-01-01T00:00:00"]
        assert result.params("per_page") == ["200"]
        assert result.raised is None

    def test_no_start_date_when_incremental_disabled(self) -> None:
        result = _driver().run(
            "activities",
            [_page("entries", [{"uuid": "a"}])],
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.params("start-date") == [None]
        assert result.raised is None

    def test_non_incremental_endpoint_never_sets_start_date(self) -> None:
        result = _driver().run(
            "customers",
            [_page("entries", [{"uuid": "a"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.params("start-date") == [None]
        assert result.raised is None


class TestValidateCredentials:
    def test_exception_returns_false(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert validate_credentials("key") is False

        assert {request.path for request in network.requests_log} == {"/v1/data_sources"}


class TestChartmogulSource:
    @pytest.mark.parametrize(
        "endpoint,primary_keys,partition_key",
        [
            ("customers", ["uuid"], None),
            ("plans", ["uuid"], None),
            ("plan_groups", ["uuid"], None),
            ("invoices", ["uuid"], "date"),
            ("activities", ["uuid"], "date"),
            ("data_sources", ["uuid"], "created_at"),
            ("customer_subscriptions", ["customer_uuid", "uuid"], None),
            ("subscription_events", ["id"], "created_at"),
            ("opportunities", ["uuid"], "created_at"),
            ("metrics", ["date"], "date"),
            ("metrics_mrr", ["date"], "date"),
        ],
    )
    def test_source_response_shape(self, endpoint: str, primary_keys: list[str], partition_key: str | None) -> None:
        data_key = CHARTMOGUL_ENDPOINTS[endpoint].data_key
        result = _driver().run(endpoint, [_page("entries" if endpoint == "customer_subscriptions" else data_key, [])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == primary_keys
        assert result.response.sort_mode == "asc"
        if partition_key:
            assert result.response.partition_keys == [partition_key]
            assert result.response.partition_mode == "datetime"
        else:
            assert result.response.partition_keys is None
            assert result.response.partition_mode is None


class TestMetricsDateRange:
    @pytest.mark.parametrize("endpoint", ["metrics", "metrics_mrr"])
    def test_metrics_send_a_closed_daily_window(self, endpoint: str) -> None:
        # The metrics endpoints reject a request without both bounds, so the window has to be
        # built at request time rather than declared.
        with time_machine.travel(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), tick=False):
            result = _driver().run(endpoint, [_page("entries", [{"date": "2026-01-01", "mrr": 100}])])

        assert [row["date"] for row in result.rows] == ["2026-01-01"]
        assert result.params("start-date") == [METRICS_START_DATE]
        assert result.params("end-date") == ["2026-03-04"]
        assert result.params("interval") == ["day"]
        # Unpaginated, so a page-size param would be undocumented and the run is one request.
        assert result.params("per_page") == [None]
        assert len(result.requests) == 1
        assert result.raised is None


class TestCustomerSubscriptionsFanout:
    def test_child_requests_are_bound_to_each_customer(self) -> None:
        result = _driver().run(
            "customer_subscriptions",
            [
                _page("entries", [{"uuid": "cus_1"}, {"uuid": "cus_2"}]),
                _page("entries", [{"uuid": "sub_a"}]),
                _page("entries", [{"uuid": "sub_b"}]),
            ],
        )

        assert result.paths == [
            "/v1/customers",
            "/v1/customers/cus_1/subscriptions",
            "/v1/customers/cus_2/subscriptions",
        ]
        # The subscription object carries no customer reference of its own, so the parent uuid is
        # injected under the name the primary key is declared on.
        assert result.rows == [
            {"uuid": "sub_a", "customer_uuid": "cus_1"},
            {"uuid": "sub_b", "customer_uuid": "cus_2"},
        ]
        assert result.params("per_page") == ["200", "200", "200"]
        assert result.raised is None

    def test_resumes_from_the_customer_in_progress(self) -> None:
        result = _driver().run(
            "customer_subscriptions",
            [
                _page("entries", [{"uuid": "cus_1"}, {"uuid": "cus_2"}]),
                _page("entries", [{"uuid": "sub_b"}]),
            ],
            resume_state=ChartMogulResumeConfig(completed=["/v1/customers/cus_1/subscriptions"]),
        )

        # cus_1 was already fully synced before the crash, so only cus_2 is fetched again.
        assert result.paths == ["/v1/customers", "/v1/customers/cus_2/subscriptions"]
        assert [row["uuid"] for row in result.rows] == ["sub_b"]
        assert result.raised is None

    def test_checkpoints_the_completed_customer(self) -> None:
        result = _driver().run(
            "customer_subscriptions",
            [
                _page("entries", [{"uuid": "cus_1"}]),
                _page("entries", [{"uuid": "sub_a"}]),
            ],
        )

        assert result.saved_states[-1].completed == ["/v1/customers/cus_1/subscriptions"]
        assert result.raised is None
