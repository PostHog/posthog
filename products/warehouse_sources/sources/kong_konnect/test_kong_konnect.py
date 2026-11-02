from datetime import UTC, date, datetime
from typing import Any, Literal

import pytest
import time_machine
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kongkonnect import (
    KongKonnectSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kong_konnect import kong_konnect
from products.warehouse_sources.backend.temporal.data_imports.sources.kong_konnect.kong_konnect import (
    LIST_PAGE_SIZE,
    MAX_PAGE_SIZE,
    KongKonnectResumeConfig,
    _clamp_future_value_to_now,
    _format_datetime,
    _resolve_window,
    get_lookup_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kong_konnect.source import KongKonnectSource


def _driver(region: Literal["us", "eu"] = "us", lookback_days: int | None = None) -> SourceDriver:
    return SourceDriver(
        KongKonnectSource(), KongKonnectSourceConfig(api_token="tok", region=region, lookback_days=lookback_days)
    )


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format_datetime(self, _name: str, value: object, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestResolveWindow:
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_future_watermark_clamped_to_now(self) -> None:
        # A future-dated cursor would otherwise produce start > end, wedging every later sync.
        start, _ = _resolve_window(
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2027, 1, 1, tzinfo=UTC),
            lookback_days=30,
        )
        assert start == "2026-06-15T12:00:00Z"


class TestClampFutureValue:
    @parameterized.expand(
        [
            ("past_datetime_untouched", datetime(2026, 1, 1, tzinfo=UTC), False),
            ("future_datetime_clamped", datetime(2027, 1, 1, tzinfo=UTC), True),
        ]
    )
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_clamp(self, _name: str, value: datetime, should_clamp: bool) -> None:
        result = _clamp_future_value_to_now(value)
        if should_clamp:
            assert result == datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
        else:
            assert result == value


def _manager(resume: KongKonnectResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _page(count: int) -> ScriptedResponse:
    return ScriptedResponse(json={"results": [{"request_id": f"r{i}"} for i in range(count)], "meta": {}})


class TestGetRowsPagination:
    def test_empty_first_page_yields_nothing(self) -> None:
        result = _driver().run("api_requests", [_page(0)])
        assert result.raised is None
        assert result.items == []

    def test_saves_state_after_full_page_only(self) -> None:
        result = _driver().run("api_requests", [_page(MAX_PAGE_SIZE), _page(2)])

        # One save after the first (full) page; the final short page must NOT persist state.
        assert result.raised is None
        assert len(result.rows) == MAX_PAGE_SIZE + 2
        assert len(result.saved_states) == 1
        saved = result.saved_states[0]
        assert saved.offset == MAX_PAGE_SIZE
        assert result.requests[0].json()["offset"] == 0
        assert result.requests[1].json()["offset"] == MAX_PAGE_SIZE

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_resume_reuses_saved_window_not_recomputed(self) -> None:
        # A crash saved a mid-window checkpoint; resume must re-issue that exact window + offset,
        # never recompute `end` as "now" (which would shift the window and skip/duplicate rows).
        resume = KongKonnectResumeConfig(start="2026-01-01T00:00:00Z", end="2026-01-05T00:00:00Z", offset=5000)

        result = _driver().run("api_requests", [_page(1)], resume_state=resume)

        assert result.raised is None
        body = result.requests[0].json()
        assert body["time_range"]["start"] == "2026-01-01T00:00:00Z"
        assert body["time_range"]["end"] == "2026-01-05T00:00:00Z"
        assert body["offset"] == 5000


def _metrics_page(*events: dict[str, Any]) -> ScriptedResponse:
    return ScriptedResponse(
        json={"data": [{"event": event, "timestamp": "2026-06-14T00:00:00Z"} for event in events], "meta": {}}
    )


class TestDailyServiceMetrics:
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_walks_days_and_merges_metric_groups_per_service(self) -> None:
        result = _driver().run(
            "daily_service_metrics",
            [
                _metrics_page(
                    {"gateway_service": "cp:svc-a", "request_count": 10, "error_rate": 0.1},
                    {"gateway_service": None, "request_count": 2, "error_rate": 0},
                ),
                _metrics_page({"gateway_service": "cp:svc-a", "response_latency_p99": 40}),
                _metrics_page(),
                _metrics_page(),
            ],
            incremental_field="day",
            db_incremental_field_last_value=datetime(2026, 6, 14, tzinfo=UTC),
        )

        assert result.raised is None
        day = datetime(2026, 6, 14, tzinfo=UTC)
        assert result.rows == [
            {
                "day": day,
                "gateway_service": "cp:svc-a",
                "request_count": 10,
                "error_rate": 0.1,
                "response_latency_p99": 40,
            },
            {"day": day, "gateway_service": "", "request_count": 2, "error_rate": 0},
        ]
        bodies = [request.json() for request in result.requests]
        assert all(request.method == "POST" and request.path == "/v2/metrics" for request in result.requests)
        assert [body["dimensions"] for body in bodies] == [["gateway_service"]] * 4
        assert [body["metrics"] for body in bodies[:2]] == [
            ["request_count", "error_rate", "response_latency_average"],
            ["response_latency_p99", "upstream_latency_p99", "kong_latency_p99"],
        ]
        # The current day ends at now, so a later sync re-reads it and the merge replaces its rows.
        assert [(body["time_range"]["start"], body["time_range"]["end"]) for body in bodies] == [
            ("2026-06-14T00:00:00Z", "2026-06-15T00:00:00Z"),
            ("2026-06-14T00:00:00Z", "2026-06-15T00:00:00Z"),
            ("2026-06-15T00:00:00Z", "2026-06-15T12:00:00Z"),
            ("2026-06-15T00:00:00Z", "2026-06-15T12:00:00Z"),
        ]
        # The completed day moves the cursor on; the day still in progress keeps it there.
        assert [state.start for state in result.saved_states] == ["2026-06-15T00:00:00Z", "2026-06-15T00:00:00Z"]
        assert result.response is not None
        assert result.response.sort_mode == "asc"

    @parameterized.expand(
        [
            ("full_refresh_walks_back_lookback", {"should_use_incremental_field": False}, None, "2026-06-12T00:00:00Z"),
            (
                "incremental_starts_at_watermark_day",
                {
                    "incremental_field": "day",
                    "db_incremental_field_last_value": datetime(2026, 6, 14, 9, 30, tzinfo=UTC),
                },
                None,
                "2026-06-14T00:00:00Z",
            ),
            (
                "future_watermark_clamped_to_today",
                {"incremental_field": "day", "db_incremental_field_last_value": datetime(2027, 1, 1, tzinfo=UTC)},
                None,
                "2026-06-15T00:00:00Z",
            ),
            (
                "stale_watermark_clamped_to_metrics_api_limit",
                {"incremental_field": "day", "db_incremental_field_last_value": datetime(2026, 1, 1, tzinfo=UTC)},
                None,
                "2026-05-15T00:00:00Z",
            ),
            (
                "resume_state_wins_over_watermark",
                {"incremental_field": "day", "db_incremental_field_last_value": datetime(2026, 6, 12, tzinfo=UTC)},
                KongKonnectResumeConfig(start="2026-06-14T00:00:00Z"),
                "2026-06-14T00:00:00Z",
            ),
        ]
    )
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_first_day_queried(
        self, _name: str, inputs: dict[str, Any], resume: KongKonnectResumeConfig | None, expected_start: str
    ) -> None:
        start = datetime.fromisoformat(expected_start.replace("Z", "+00:00"))
        days = (datetime(2026, 6, 15, tzinfo=UTC) - start).days + 1
        result = _driver(lookback_days=3).run(
            "daily_service_metrics", [_metrics_page()] * (2 * days), resume_state=resume, **inputs
        )

        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 2 * days
        assert result.requests[0].json()["time_range"]["start"] == expected_start


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            assert validate_credentials("tok", "us") is expected
        assert network.requests_log[0].path == "/v2/api-requests"

    def test_network_error_is_false(self) -> None:
        with scripted_network([requests.ConnectionError()]):
            assert validate_credentials("tok", "us") is False


class TestKongKonnectSourceResponse:
    def test_source_response_shape(self) -> None:
        response = _driver(region="eu").run("api_requests", [_page(0)]).response
        assert response is not None
        assert response.name == "api_requests"
        assert response.primary_keys == ["request_id"]
        # asc must match the ascending request order for the watermark to advance correctly.
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["request_start"]


def _control_plane(cp_id: str, cluster_type: str = "CLUSTER_TYPE_CONTROL_PLANE") -> dict[str, Any]:
    return {"id": cp_id, "name": cp_id, "config": {"cluster_type": cluster_type}}


def _json_response(status: int, body: dict[str, Any] | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.ok = status < 400
    response.json.return_value = body or {}
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status} Client Error", response=response)
    return response


BASE = "https://us.api.konghq.com/v2"


class TestLookupRows:
    @parameterized.expand(
        [
            ("short_page_stops", [[LIST_PAGE_SIZE, None], [2, None]], 2),
            ("total_reached_stops", [[LIST_PAGE_SIZE, LIST_PAGE_SIZE]], 1),
            ("empty_first_page", [[0, 0]], 1),
        ]
    )
    def test_control_planes_page_number_pagination(
        self, _name: str, pages: list[list[int | None]], expected_requests: int
    ) -> None:
        responses = []
        for count, total in pages:
            meta = {"page": {"total": total}} if total is not None else {}
            responses.append(
                ScriptedResponse(json={"data": [_control_plane(f"cp{i}") for i in range(count or 0)], "meta": meta})
            )
        result = _driver().run("control_planes", responses)

        assert result.raised is None
        assert len(result.rows) == sum(count or 0 for count, _ in pages)
        assert len(result.requests) == expected_requests
        assert result.params("page[number]") == [str(page) for page in range(1, expected_requests + 1)]

    def test_core_entities_fan_out_over_control_planes(self) -> None:
        result = _driver().run(
            "services",
            [
                ScriptedResponse(
                    json={
                        "data": [
                            _control_plane("cp-a"),
                            _control_plane("cp-group", "CLUSTER_TYPE_CONTROL_PLANE_GROUP"),
                            _control_plane("cp-deleted"),
                            _control_plane("cp-b"),
                        ],
                        "meta": {"page": {"total": 4}},
                    }
                ),
                ScriptedResponse(json={"data": [{"id": "svc-1"}], "offset": "next-token"}),
                ScriptedResponse(json={"data": [{"id": "svc-2"}], "offset": None}),
                ScriptedResponse(status=404),
                # decK can copy entity IDs between control planes, so the same ID shows up again here.
                ScriptedResponse(json={"data": [{"id": "svc-1"}]}),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"id": "svc-1", "control_plane_id": "cp-a"},
            {"id": "svc-2", "control_plane_id": "cp-a"},
            {"id": "svc-1", "control_plane_id": "cp-b"},
        ]
        assert result.response is not None
        assert result.response.primary_keys == ["control_plane_id", "id"]
        assert all(request.method == "GET" for request in result.requests)
        assert result.paths == [
            "/v2/control-planes",
            "/v2/control-planes/cp-a/core-entities/services",
            "/v2/control-planes/cp-a/core-entities/services",
            "/v2/control-planes/cp-deleted/core-entities/services",
            "/v2/control-planes/cp-b/core-entities/services",
        ]
        assert result.params("offset") == [None, None, "next-token", None, None]

    @parameterized.expand(
        [
            (
                "plugin_config",
                "plugins",
                {"id": "p-1", "name": "aws-lambda", "config": {"aws_secret": "shh"}},
                {"id": "p-1", "name": "aws-lambda", "control_plane_id": "cp-a"},
            ),
            (
                "upstream_health_check_headers",
                "upstreams",
                {
                    "id": "u-1",
                    "healthchecks": {
                        "active": {"headers": {"Authorization": ["Bearer shh"]}, "http_path": "/health"},
                        "passive": {"type": "http"},
                    },
                },
                {
                    "id": "u-1",
                    "healthchecks": {"active": {"http_path": "/health"}, "passive": {"type": "http"}},
                    "control_plane_id": "cp-a",
                },
            ),
        ]
    )
    def test_core_entities_drop_credential_fields(
        self, _name: str, endpoint: str, row: dict[str, Any], expected: dict[str, Any]
    ) -> None:
        with patch(f"{kong_konnect.__name__}.make_tracked_session", wraps=kong_konnect.make_tracked_session) as spy:
            result = _driver().run(
                endpoint,
                [
                    ScriptedResponse(json={"data": [_control_plane("cp-a")], "meta": {"page": {"total": 1}}}),
                    ScriptedResponse(json={"data": [row]}),
                ],
            )

        assert result.raised is None
        assert result.rows == [expected]
        # HTTP samples would capture the raw response before the fields are dropped.
        assert spy.call_args.kwargs["capture"] is False

    def test_core_entities_raise_on_auth_error(self) -> None:
        result = _driver().run(
            "consumers",
            [
                ScriptedResponse(json={"data": [_control_plane("cp-a")], "meta": {"page": {"total": 1}}}),
                ScriptedResponse(status=403),
            ],
        )

        assert isinstance(result.raised, requests.HTTPError)

    @patch.object(kong_konnect, "make_tracked_session")
    def test_consumer_group_members_fan_out_over_groups_per_control_plane(self, mock_session: MagicMock) -> None:
        def fake_get(url: str, params: dict[str, Any], timeout: int) -> MagicMock:
            routes: dict[str, dict[str, Any]] = {
                f"{BASE}/control-planes": {"data": [_control_plane("cp-a")], "meta": {"page": {"total": 1}}},
                f"{BASE}/control-planes/cp-a/core-entities/consumer_groups": {"data": [{"id": "gold"}, {"id": "free"}]},
                f"{BASE}/control-planes/cp-a/core-entities/consumer_groups/gold/consumers": {"data": [{"id": "c-1"}]},
                f"{BASE}/control-planes/cp-a/core-entities/consumer_groups/free/consumers": {"data": [{"id": "c-1"}]},
            }
            if url not in routes:
                raise AssertionError(f"unexpected request to {url}")
            return _json_response(200, routes[url])

        mock_session.return_value.get.side_effect = fake_get
        manager = _manager()

        rows = [
            row
            for batch in get_lookup_rows("tok", "us", "consumer_group_members", MagicMock(), manager)
            for row in batch
        ]

        assert rows == [
            {"id": "c-1", "control_plane_id": "cp-a", "consumer_group_id": "gold"},
            {"id": "c-1", "control_plane_id": "cp-a", "consumer_group_id": "free"},
        ]
        assert manager.safe_point.call_count == 2

    @parameterized.expand(
        [
            (
                "page_number_child_on_v1",
                "scorecard_services",
                "scorecard_id",
                "https://us.api.konghq.com/v1/scorecards",
                "https://us.api.konghq.com/v1/scorecards/{id}/catalog-services",
            ),
            (
                "page_number_child_on_v2",
                "api_product_versions",
                "api_product_id",
                "https://us.api.konghq.com/v2/api-products",
                "https://us.api.konghq.com/v2/api-products/{id}/product-versions",
            ),
        ]
    )
    def test_page_number_children_fan_out_over_parents(
        self, _name: str, endpoint: str, parent_id_field: str, parent_url: str, child_url: str
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json={"data": [{"id": "p-1"}, {"id": "p-gone"}], "meta": {"page": {"total": 2}}}),
                ScriptedResponse(json={"data": [{"id": "x-1"}], "meta": {"page": {"total": 1}}}),
                ScriptedResponse(status=404),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": "x-1", parent_id_field: "p-1"}]
        assert [request.origin + request.path for request in result.requests] == [
            parent_url,
            child_url.format(id="p-1"),
            child_url.format(id="p-gone"),
        ]
        assert result.params("sort") == ["name", "name", "name"]

    @parameterized.expand(
        [
            ("meters", "meters", "/v3/openmeter/meters", "created_at"),
            ("subscriptions", "subscriptions", "/v3/openmeter/subscriptions", "id"),
        ]
    )
    def test_metering_lists_use_v3_page_number_pagination(
        self, _name: str, endpoint: str, path: str, sort: str
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(
                    json={
                        "data": [{"id": f"m-{i}"} for i in range(LIST_PAGE_SIZE)],
                        "meta": {"page": {"number": 1, "size": LIST_PAGE_SIZE, "total": LIST_PAGE_SIZE + 1}},
                    }
                ),
                ScriptedResponse(
                    json={
                        "data": [{"id": "m-last"}],
                        "meta": {"page": {"number": 2, "size": LIST_PAGE_SIZE, "total": LIST_PAGE_SIZE + 1}},
                    }
                ),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == LIST_PAGE_SIZE + 1
        assert result.paths == [path, path]
        assert result.params("page[number]") == ["1", "2"]
        assert result.params("sort") == [sort, sort]

    def test_realm_consumers_follow_page_after_cursor_from_meta_next(self) -> None:
        result = _driver().run(
            "realm_consumers",
            [
                ScriptedResponse(json={"data": [{"id": "realm-a"}], "meta": {"next": None}}),
                ScriptedResponse(
                    json={
                        "data": [{"id": "c-1"}],
                        "meta": {"next": "/v1/realms/realm-a/consumers?page%5Bafter%5D=abc%3D%3D"},
                    }
                ),
                ScriptedResponse(json={"data": [{"id": "c-2"}], "meta": {"next": None}}),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": "c-1", "realm_id": "realm-a"}, {"id": "c-2", "realm_id": "realm-a"}]
        assert result.paths == [
            "/v1/realms",
            "/v1/realms/realm-a/consumers",
            "/v1/realms/realm-a/consumers",
        ]
        assert result.params("page[after]") == [None, None, "abc=="]


if __name__ == "__main__":
    pytest.main([__file__])
