from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.sources.rootly._config import RootlySourceConfig
from products.warehouse_sources.sources.rootly.rootly import (
    ROOTLY_BASE_URL,
    RootlyResumeConfig,
    _build_url,
    _clamp_future_value_to_now,
    _format_incremental_value,
    probe_credentials,
)
from products.warehouse_sources.sources.rootly.source import RootlySource
from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)


def _response(
    items: list[dict[str, Any]] | None, next_url: str | None = None, *, drop_data: bool = False
) -> ScriptedResponse:
    body: dict[str, Any] = {"links": {"next": next_url}}
    if not drop_data:
        body["data"] = items or []
    return ScriptedResponse(json=body)


def _feed_response(items: list[dict[str, Any]], next_cursor: str | None) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items, "meta": {"next_cursor": next_cursor}})


def _driver() -> SourceDriver:
    return SourceDriver(RootlySource(), RootlySourceConfig(api_key="rootly_test"))


class TestBuildUrl:
    def test_no_params_returns_base(self) -> None:
        assert _build_url("https://api.rootly.com/v1/users", {}) == "https://api.rootly.com/v1/users"


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("string_passthrough", "cursor-token", "cursor-token"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestClampFutureValueToNow:
    def test_string_passthrough(self) -> None:
        assert _clamp_future_value_to_now("cursor-token") == "cursor-token"


class TestPagination:
    def test_follows_links_next_and_flattens(self) -> None:
        second = "https://api.rootly.com/v1/incidents?page%5Bnumber%5D=2"

        result = _driver().run(
            "incidents",
            [
                _response([{"id": "1", "type": "incidents", "attributes": {"title": "A"}}], next_url=second),
                _response([{"id": "2", "type": "incidents", "attributes": {"title": "B"}}]),
            ],
        )

        assert result.rows == [
            {"id": "1", "type": "incidents", "title": "A"},
            {"id": "2", "type": "incidents", "title": "B"},
        ]
        assert result.urls[0].split("?")[0] == f"{ROOTLY_BASE_URL}/incidents"
        assert result.requests[0].param("page[size]") == "100"
        # The next-page URL is self-contained; the original params must not be re-appended.
        assert result.urls[1] == second
        assert set(result.queries[1]) == {"page[number]"}

    @parameterized.expand(
        [
            ("empty_collection", False),
            # A body without `data` is treated as an empty page (JSON:API always carries `data`).
            ("missing_data_key", True),
        ]
    )
    def test_empty_collection_yields_nothing(self, _name: str, drop_data: bool) -> None:
        result = _driver().run("incidents", [_response([], drop_data=drop_data)])

        assert result.rows == []
        assert len(result.requests) == 1
        assert result.saved_states == []


class TestIncrementalParams:
    @parameterized.expand(
        [
            (
                "incremental_endpoint_sorts_and_filters_on_watermark",
                "incidents",
                True,
                datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                {"page[size]": "100", "sort": "updated_at", "filter[updated_at][gt]": "2026-03-04T02:58:14+00:00"},
            ),
            (
                "incremental_first_sync_sorts_without_filter",
                "incidents",
                True,
                None,
                {"page[size]": "100", "sort": "updated_at"},
            ),
            (
                "incremental_disabled_has_no_sort_or_filter",
                "incidents",
                False,
                datetime(2026, 3, 4),
                {"page[size]": "100"},
            ),
            (
                "cursor_feed_sorts_and_filters_on_created_at",
                "alert_events",
                True,
                datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                {"page[size]": "50", "sort": "created_at", "filter[created_at][gt]": "2026-03-04T02:58:14+00:00"},
            ),
            (
                "full_refresh_endpoint_never_sorts_or_filters",
                "users",
                True,
                datetime(2026, 3, 4, tzinfo=UTC),
                {"page[size]": "100"},
            ),
        ]
    )
    def test_initial_request_params(
        self,
        _name: str,
        endpoint: str,
        should_use_incremental_field: bool,
        last_value: Any,
        expected_params: dict[str, Any],
    ) -> None:
        inputs: dict[str, Any] = {"db_incremental_field_last_value": last_value}
        if should_use_incremental_field:
            inputs["incremental_field"] = "created_at" if endpoint == "alert_events" else "updated_at"

        result = _driver().run(endpoint, [_response([{"id": "1", "attributes": {}}])], **inputs)

        assert {name: values[0] for name, values in result.queries[0].items()} == expected_params


class TestCursorFeed:
    def test_walks_next_cursor_and_keeps_the_incremental_window(self) -> None:
        result = _driver().run(
            "alert_events",
            [
                _feed_response([{"id": "e1", "type": "alert_events", "attributes": {"action": "paged"}}], "c2"),
                _feed_response([{"id": "e2", "type": "alert_events", "attributes": {"action": "resolved"}}], None),
            ],
            incremental_field="created_at",
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )

        assert result.raised is None
        assert [(row["id"], row["action"]) for row in result.rows] == [("e1", "paged"), ("e2", "resolved")]
        assert result.paths == ["/v1/alert_events", "/v1/alert_events"]
        assert result.params("page[after]") == [None, "c2"]
        assert result.params("filter[created_at][gt]") == ["2026-03-04T00:00:00+00:00"] * 2
        assert result.params("sort") == ["created_at"] * 2
        assert result.saved_states == [RootlyResumeConfig(cursor="c2")]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "alert_events",
            [_feed_response([{"id": "e9", "attributes": {}}], None)],
            resume_state=RootlyResumeConfig(cursor="c9"),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["e9"]
        assert result.params("page[after]") == ["c9"]


def _incident_events_script(request: RecordedRequest) -> ScriptedResponse:
    second_page = f"{ROOTLY_BASE_URL}/incidents/inc-1/events?page%5Bnumber%5D=2"
    if request.path == "/v1/incidents":
        return _response([{"id": "inc-1", "type": "incidents"}, {"id": "inc-2", "type": "incidents"}])
    if request.path == "/v1/incidents/inc-1/events" and request.param("page[number]") == "2":
        return _response([{"id": "ev-2", "type": "incident_events", "attributes": {"event": "Mitigated"}}])
    if request.path == "/v1/incidents/inc-1/events":
        return _response(
            [{"id": "ev-1", "type": "incident_events", "attributes": {"event": "Started"}}], next_url=second_page
        )
    if request.path == "/v1/incidents/inc-2/events":
        return ScriptedResponse(status=404, json={"errors": [{"title": "Not found", "status": "404"}]})
    raise AssertionError(f"unexpected request {request.url}")


class TestIncidentEventsFanout:
    def test_fans_out_over_incidents_and_tags_rows_with_the_incident(self) -> None:
        result = _driver().run("incident_events", _incident_events_script)

        assert result.raised is None
        assert result.rows == [
            {"id": "ev-1", "type": "incident_events", "event": "Started", "incident_id": "inc-1"},
            {"id": "ev-2", "type": "incident_events", "event": "Mitigated", "incident_id": "inc-1"},
        ]
        assert result.paths == [
            "/v1/incidents",
            "/v1/incidents/inc-1/events",
            "/v1/incidents/inc-1/events",
            "/v1/incidents/inc-2/events",
        ]
        assert result.response is not None
        assert result.response.primary_keys == ["incident_id", "id"]

    def test_resume_skips_incidents_already_synced(self) -> None:
        result = _driver().run(
            "incident_events",
            _incident_events_script,
            resume_state=RootlyResumeConfig(completed=["/incidents/inc-1/events"]),
        )

        assert result.raised is None
        assert result.rows == []
        assert result.paths == ["/v1/incidents", "/v1/incidents/inc-2/events"]


class TestProbeCredentials:
    @parameterized.expand([("ok", 200), ("unauthorized", 401), ("forbidden", 403)])
    def test_returns_status_code(self, _name: str, status_code: int) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]):
            assert probe_credentials("rootly_test", "incidents") == status_code

    @parameterized.expand(
        [
            ("top_level_endpoint", "statuses", "/v1/statuses"),
            # The child path needs an incident id, so the scope check probes the parent collection.
            ("fanout_endpoint_probes_parent", "incident_events", "/v1/incidents"),
            ("no_endpoint", None, "/v1/users"),
        ]
    )
    def test_probes_a_concrete_collection(self, _name: str, endpoint: str | None, expected_path: str) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert probe_credentials("rootly_test", endpoint) == 200

        assert [request.path for request in network.requests_log] == [expected_path]
