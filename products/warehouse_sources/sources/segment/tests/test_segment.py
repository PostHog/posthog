import datetime as dt
from typing import Any, Literal, cast

import time_machine

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver
from products.warehouse_sources.sources.segment._config import SegmentSourceConfig
from products.warehouse_sources.sources.segment.segment import (
    SegmentResumeConfig,
    _base_url,
    _extract_rows,
    _next_cursor,
    _redact_rows,
)
from products.warehouse_sources.sources.segment.settings import SEGMENT_ENDPOINTS
from products.warehouse_sources.sources.segment.source import SegmentSource


def _driver(region: str = "api") -> SourceDriver:
    return SourceDriver(
        SegmentSource(), SegmentSourceConfig(api_token="tok", region=cast(Literal["api", "eu1"], region))
    )


def _page(body: dict[str, Any]) -> ScriptedResponse:
    return ScriptedResponse(json=body)


class TestBaseUrl:
    @parameterized.expand(
        [
            ("us", "api", "https://api.segmentapis.com"),
            ("eu", "eu1", "https://eu1.api.segmentapis.com"),
            # An unknown region falls back to the US host rather than building a broken URL.
            ("unknown", "mars", "https://api.segmentapis.com"),
        ]
    )
    def test_base_url(self, _name: str, region: str, expected: str) -> None:
        assert _base_url(region) == expected


class TestExtractRows:
    @parameterized.expand(
        [
            ("sources_key", {"data": {"sources": [{"id": "s1"}], "pagination": {}}}, [{"id": "s1"}]),
            # The array key isn't always the endpoint name: audit-events returns it under "events".
            ("events_key", {"data": {"events": [{"id": "e1"}], "pagination": {}}}, [{"id": "e1"}]),
            ("labels_key", {"data": {"labels": [{"key": "env", "value": "dev"}]}}, [{"key": "env", "value": "dev"}]),
            ("empty_list", {"data": {"sources": [], "pagination": {}}}, []),
            ("no_data", {}, []),
            ("data_not_dict", {"data": []}, []),
        ]
    )
    def test_extract_rows(self, _name: str, body: dict[str, Any], expected: list[dict[str, Any]]) -> None:
        assert _extract_rows(body) == expected

    def test_pagination_object_is_never_returned_as_rows(self) -> None:
        # `pagination` is a dict, not a list, so it must not be mistaken for the resource array.
        body = {"data": {"pagination": {"next": "x"}, "sources": [{"id": "s1"}]}}
        assert _extract_rows(body) == [{"id": "s1"}]


class TestRedactRows:
    def test_no_redacted_fields_returns_rows_unchanged(self) -> None:
        rows = [{"id": "1", "settings": {"k": "v"}}]
        assert _redact_rows(rows, frozenset()) == rows


class TestNextCursor:
    @parameterized.expand(
        [
            ("has_next", {"data": {"pagination": {"next": "Mw=="}}}, "Mw=="),
            ("next_null", {"data": {"pagination": {"next": None}}}, None),
            ("next_empty", {"data": {"pagination": {"next": ""}}}, None),
            ("no_pagination", {"data": {"sources": []}}, None),
            ("no_data", {}, None),
        ]
    )
    def test_next_cursor(self, _name: str, body: dict[str, Any], expected: str | None) -> None:
        assert _next_cursor(body) == expected


class TestGetRows:
    def test_paginates_until_next_is_absent(self) -> None:
        result = _driver().run(
            "sources",
            [
                _page({"data": {"sources": [{"id": "s1"}], "pagination": {"next": "c1"}}}),
                _page({"data": {"sources": [{"id": "s2"}], "pagination": {"next": "c2"}}}),
                _page({"data": {"sources": [{"id": "s3"}], "pagination": {"next": None}}}),
            ],
        )
        assert result.rows == [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}]
        assert result.params("pagination[cursor]") == [None, "c1", "c2"]
        assert result.saved_states == [SegmentResumeConfig(cursor="c1"), SegmentResumeConfig(cursor="c2")]

    def test_resume_starts_from_saved_cursor(self) -> None:
        result = _driver().run(
            "sources",
            [_page({"data": {"sources": [{"id": "s9"}], "pagination": {"next": None}}})],
            resume_state=SegmentResumeConfig(cursor="resumed"),
        )

        assert result.rows == [{"id": "s9"}]
        assert result.requests[0].param("pagination[cursor]") == "resumed"

    def test_credential_fields_are_redacted(self) -> None:
        # Credential-like config must never reach the queryable warehouse table.
        cases = [
            ("destinations", {"id": "d1", "settings": {"apiKey": "secret"}}, {"id": "d1"}),
            ("warehouses", {"id": "w1", "settings": {"password": "secret"}}, {"id": "w1"}),
            ("sources", {"id": "s1", "writeKeys": ["wk_secret"]}, {"id": "s1"}),
        ]
        for endpoint, raw_row, expected_row in cases:
            result = _driver().run(endpoint, [_page({"data": {endpoint: [raw_row], "pagination": {"next": None}}})])
            assert result.rows == [expected_row], endpoint

    def test_single_object_endpoint_yields_one_row_and_no_pagination(self) -> None:
        result = _driver().run(
            "workspace", [_page({"data": {"workspace": {"id": "w1", "name": "Acme", "slug": "acme"}}})]
        )

        assert result.rows == [{"id": "w1", "name": "Acme", "slug": "acme"}]
        # The workspace endpoint hits its bare path once, with no pagination params.
        assert result.urls == ["https://api.segmentapis.com/"]
        assert result.saved_states == []


class TestSegmentSource:
    @staticmethod
    def _empty_page(_request: Any) -> ScriptedResponse:
        return _page({"data": {"pagination": {}}})

    @parameterized.expand([(name,) for name in SEGMENT_ENDPOINTS])
    def test_source_response_carries_endpoint_primary_keys(self, endpoint: str) -> None:
        result = _driver().run(endpoint, self._empty_page)

        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == SEGMENT_ENDPOINTS[endpoint].primary_keys

    @parameterized.expand(
        [
            ("audit_events_partitions_on_timestamp", "audit_events", "datetime", ["timestamp"]),
            ("sources_unpartitioned", "sources", None, None),
        ]
    )
    def test_partitioning(
        self, _name: str, endpoint: str, expected_mode: str | None, expected_keys: list[str] | None
    ) -> None:
        result = _driver().run(endpoint, self._empty_page)

        assert result.response is not None
        assert result.response.partition_mode == expected_mode
        assert result.response.partition_keys == expected_keys


def _list(key: str, rows: list[dict[str, Any]], next_cursor: str | None = None) -> ScriptedResponse:
    return _page({"data": {key: rows, "pagination": {"next": next_cursor}}})


_TRACKING_PLAN_PAGES = [
    _list("trackingPlans", [{"id": "tp_b"}], "plans2"),
    _list("trackingPlans", [{"id": "tp_a"}]),
]


class TestFanOut:
    def test_tracking_plan_rules_walk_every_plan_and_child_page(self) -> None:
        result = _driver().run(
            "tracking_plan_rules",
            [
                *_TRACKING_PLAN_PAGES,
                _list("rules", [{"type": "TRACK", "key": "Clicked", "version": 1}], "rules2"),
                _list("rules", [{"type": "IDENTIFY", "version": 1}]),
                _list("rules", []),
            ],
        )

        assert result.paths == [
            "/tracking-plans",
            "/tracking-plans",
            "/tracking-plans/tp_a/rules",
            "/tracking-plans/tp_a/rules",
            "/tracking-plans/tp_b/rules",
        ]
        assert result.params("pagination[cursor]") == [None, "plans2", None, "rules2", None]
        assert result.rows == [
            {"type": "TRACK", "key": "Clicked", "version": 1, "trackingPlanId": "tp_a"},
            {"type": "IDENTIFY", "key": "", "version": 1, "trackingPlanId": "tp_a"},
        ]
        assert result.saved_states == [
            SegmentResumeConfig(cursor="rules2", parent_id="tp_a"),
            SegmentResumeConfig(parent_id="tp_a", parent_done=True),
            SegmentResumeConfig(parent_id="tp_b", parent_done=True),
        ]

    @parameterized.expand(
        [
            (
                "known_parent_resumes_at_its_child_cursor",
                SegmentResumeConfig(cursor="rules2", parent_id="tp_b"),
                ["/tracking-plans/tp_b/rules"],
                ["rules2"],
            ),
            (
                "deleted_parent_continues_at_the_next_parent",
                SegmentResumeConfig(cursor="gone_cursor", parent_id="tp_aa"),
                ["/tracking-plans/tp_b/rules"],
                [None],
            ),
            (
                "done_parent_continues_at_the_next_parent",
                SegmentResumeConfig(parent_id="tp_a", parent_done=True),
                ["/tracking-plans/tp_b/rules"],
                [None],
            ),
            ("done_last_parent_reads_no_child", SegmentResumeConfig(parent_id="tp_b", parent_done=True), [], []),
        ]
    )
    def test_resume(
        self,
        _name: str,
        state: SegmentResumeConfig,
        expected_child_paths: list[str],
        expected_child_cursors: list[str | None],
    ) -> None:
        child_pages = [_list("rules", [{"type": "TRACK", "key": "k", "version": 1}]) for _ in expected_child_paths]
        result = _driver().run("tracking_plan_rules", [*_TRACKING_PLAN_PAGES, *child_pages], resume_state=state)

        assert result.paths[2:] == expected_child_paths
        assert result.params("pagination[cursor]")[2:] == expected_child_cursors

    @parameterized.expand([("not_found_is_skipped", 404, None), ("forbidden_fails", 403, requests.HTTPError)])
    def test_child_error(self, _name: str, status: int, expected_error: type[BaseException] | None) -> None:
        result = _driver().run(
            "tracking_plan_rules",
            [
                *_TRACKING_PLAN_PAGES,
                ScriptedResponse(status=status, json={"errors": []}),
                _list("rules", [{"type": "TRACK", "key": "k", "version": 1}]),
            ],
        )

        if expected_error is None:
            assert result.raised is None
            assert result.rows == [{"type": "TRACK", "key": "k", "version": 1, "trackingPlanId": "tp_b"}]
        else:
            assert isinstance(result.raised, expected_error)
            assert result.rows == []

    @parameterized.expand(
        [
            ("fresh_run", None, "2026-03-03T00:00:00.000Z", "2026-03-15T00:00:00.000Z"),
            (
                "resumed_run_keeps_its_window",
                SegmentResumeConfig(window_end="2026-03-14T00:00:00.000Z"),
                "2026-03-02T00:00:00.000Z",
                "2026-03-14T00:00:00.000Z",
            ),
            (
                "resumed_window_past_the_lookback_limit_is_replaced",
                SegmentResumeConfig(window_end="2026-03-13T00:00:00.000Z"),
                "2026-03-03T00:00:00.000Z",
                "2026-03-15T00:00:00.000Z",
            ),
        ]
    )
    def test_delivery_metrics_request_a_whole_day_window_per_destination(
        self, _name: str, resume_state: SegmentResumeConfig | None, window_start: str, window_end: str
    ) -> None:
        summary = {
            "sourceId": "src1",
            "destinationMetadataId": "meta1",
            "metrics": [
                {"metricName": "successes", "total": 10},
                {"metricName": "discarded", "total": 2, "breakdown": [{"metricName": "dropped", "value": 2}]},
            ],
        }
        with time_machine.travel(dt.datetime(2026, 3, 15, 10, 30, tzinfo=dt.UTC), tick=False):
            result = _driver().run(
                "destination_delivery_metrics",
                [
                    _list("destinations", [{"id": "d1", "sourceId": "src1"}, {"id": "d_no_source"}]),
                    _page({"data": {"deliveryMetricsSummary": summary}}),
                ],
                resume_state=resume_state,
            )

        window = {
            "destinationId": "d1",
            "sourceId": "src1",
            "destinationMetadataId": "meta1",
            "windowStart": window_start,
            "windowEnd": window_end,
        }
        assert result.paths == ["/destinations", "/destinations/d1/delivery-metrics"]
        request = result.requests[1]
        assert (request.param("sourceId"), request.param("granularity")) == ("src1", "DAY")
        assert (request.param("startTime"), request.param("endTime")) == (window["windowStart"], window["windowEnd"])
        assert result.rows == [
            {"metricName": "successes", "total": 10, **window},
            {"metricName": "discarded", "total": 2, "breakdown": [{"metricName": "dropped", "value": 2}], **window},
        ]

    def test_reverse_etl_syncs_read_each_model_subscription(self) -> None:
        result = _driver().run(
            "reverse_etl_syncs",
            [
                _list("models", [{"id": "m1", "sourceId": "retl_src"}]),
                _list(
                    "destinations",
                    [{"id": "d_retl", "sourceId": "retl_src"}, {"id": "d_events", "sourceId": "web_src"}],
                ),
                _list(
                    "subscriptions",
                    [{"id": "sub1", "modelId": "m1"}, {"id": "sub_event", "destinationId": "d_retl"}],
                ),
                _list("syncStatuses", [{"syncId": "s1", "modelId": "m1"}], "syncs2"),
                _list("syncStatuses", [{"syncId": "s2", "modelId": "m1"}]),
            ],
        )

        assert result.paths == [
            "/reverse-etl-models",
            "/destinations",
            "/destinations/d_retl/subscriptions",
            "/reverse-etl-models/m1/subscriptionId/sub1/syncs",
            "/reverse-etl-models/m1/subscriptionId/sub1/syncs",
        ]
        assert [(request.param("count"), request.param("cursor")) for request in result.requests[3:]] == [
            ("100", None),
            ("100", "syncs2"),
        ]
        assert result.rows == [
            {"syncId": "s1", "modelId": "m1", "subscriptionId": "sub1"},
            {"syncId": "s2", "modelId": "m1", "subscriptionId": "sub1"},
        ]

    def test_event_volume_flattens_each_source_series_across_pages(self) -> None:
        with time_machine.travel(dt.datetime(2026, 3, 15, 10, 30, tzinfo=dt.UTC), tick=False):
            result = _driver().run(
                "event_volume",
                [
                    _page(
                        {
                            "data": {
                                "result": [
                                    {
                                        "source": {"id": "src1", "name": "Web", "slug": "web"},
                                        "total": 7,
                                        "series": [
                                            {"time": "2026-02-15T00:00:00Z", "count": 3},
                                            {"time": "2026-02-16T00:00:00Z", "count": 4},
                                        ],
                                    }
                                ],
                                "pagination": {"next": "vol2"},
                            }
                        }
                    ),
                    _page(
                        {
                            "data": {
                                "result": [
                                    {"source": {"id": "src2"}, "series": [{"time": "2026-02-15T00:00:00Z", "count": 1}]}
                                ]
                            }
                        }
                    ),
                ],
            )

        assert result.paths == ["/events/volume", "/events/volume"]
        first = result.requests[0]
        assert (first.param("granularity"), first.param("groupBy")) == ("DAY", "source")
        assert (first.param("startTime"), first.param("endTime")) == (
            "2026-02-15T00:00:00.000Z",
            "2026-03-15T00:00:00.000Z",
        )
        assert result.params("pagination[cursor]") == [None, "vol2"]
        assert result.requests[1].param("startTime") == "2026-02-15T00:00:00.000Z"
        assert result.rows == [
            {"sourceId": "src1", "sourceName": "Web", "sourceSlug": "web", "time": "2026-02-15T00:00:00Z", "count": 3},
            {"sourceId": "src1", "sourceName": "Web", "sourceSlug": "web", "time": "2026-02-16T00:00:00Z", "count": 4},
            {"sourceId": "src2", "sourceName": None, "sourceSlug": None, "time": "2026-02-15T00:00:00Z", "count": 1},
        ]

    @parameterized.expand(
        [
            ("workspace", "workspace_mtu_usage", "/usage/mtu/daily", "dailyWorkspaceMTUUsage", {}),
            (
                "per_source",
                "source_mtu_usage",
                "/usage/mtu/sources/daily",
                "dailyPerSourceMTUUsage",
                {"sourceId": "s1"},
            ),
        ]
    )
    def test_mtu_usage_reads_the_current_and_previous_usage_month(
        self, _name: str, endpoint: str, path: str, key: str, extra: dict[str, Any]
    ) -> None:
        snapshot = {"periodStart": 1, "periodEnd": 2, "identified": "5", "timestamp": "2026-01-02T00:00:00Z", **extra}
        with time_machine.travel(dt.datetime(2026, 1, 15, tzinfo=dt.UTC), tick=False):
            result = _driver().run(endpoint, [_list(key, [snapshot]), _list(key, [snapshot], "next"), _list(key, [])])

        assert result.paths == [path, path, path]
        assert result.params("period") == ["2025-12-01", "2026-01-01", "2026-01-01"]
        assert result.params("pagination[cursor]") == [None, None, "next"]
        assert result.rows == [snapshot, snapshot]

    def test_warehouse_syncs_read_every_warehouse(self) -> None:
        report = {"sourceId": "src1", "start": "2026-03-01T00:00:00Z", "status": "SUCCESS", "count": 10}
        result = _driver().run(
            "warehouse_syncs",
            [
                _list("warehouses", [{"id": "wh_b"}, {"id": "wh_a", "settings": {"password": "secret"}}]),
                _list("reports", [report], "reports2"),
                _list("reports", []),
                _list("reports", [{**report, "sourceId": "src2"}]),
            ],
        )

        assert result.paths == [
            "/warehouses",
            "/warehouses/wh_a/syncs",
            "/warehouses/wh_a/syncs",
            "/warehouses/wh_b/syncs",
        ]
        assert result.params("pagination[cursor]") == [None, None, "reports2", None]
        assert result.rows == [{**report, "warehouseId": "wh_a"}, {**report, "sourceId": "src2", "warehouseId": "wh_b"}]

    def test_delivery_overview_reads_each_stage_and_skips_reverse_etl(self) -> None:
        def respond(request: Any) -> ScriptedResponse:
            listings = {
                "/sources": _list("sources", [{"id": "src1"}, {"id": "retl_src"}]),
                "/destinations": _list(
                    "destinations", [{"id": "d1", "sourceId": "src1"}, {"id": "d_retl", "sourceId": "retl_src"}]
                ),
                "/reverse-etl-models": _list("models", [{"id": "m1", "sourceId": "retl_src"}]),
            }
            if request.path in listings:
                return listings[request.path]
            point = {"time": "2026-03-01T00:00:00Z", "count": 2}
            return _page({"data": {"total": 2, "dataset": [{"total": 2, "series": [point]}], "pagination": {}}})

        with time_machine.travel(dt.datetime(2026, 3, 15, 10, 30, tzinfo=dt.UTC), tick=False):
            result = _driver().run("delivery_overview", respond)

        metric_requests = [request for request in result.requests if request.path.startswith("/delivery-overview/")]
        assert sorted(
            (request.path, request.param("sourceId"), request.param("destinationConfigId"))
            for request in metric_requests
        ) == [
            ("/delivery-overview/failed-delivery", "src1", "d1"),
            ("/delivery-overview/failed-on-ingest", "src1", None),
            ("/delivery-overview/filtered-at-destination", "src1", "d1"),
            ("/delivery-overview/filtered-at-source", "src1", None),
            ("/delivery-overview/successful-delivery", "src1", "d1"),
            ("/delivery-overview/successfully-received", "src1", None),
        ]
        assert {(request.param("granularity"), request.param("startTime")) for request in metric_requests} == {
            ("DAY", "2026-02-15T00:00:00.000Z")
        }
        assert sorted((row["stage"], row["destinationId"]) for row in result.rows) == [
            ("failed-delivery", "d1"),
            ("failed-on-ingest", ""),
            ("filtered-at-destination", "d1"),
            ("filtered-at-source", ""),
            ("successful-delivery", "d1"),
            ("successfully-received", ""),
        ]
        assert {(row["sourceId"], row["time"], row["count"]) for row in result.rows} == {
            ("src1", "2026-03-01T00:00:00Z", 2)
        }
