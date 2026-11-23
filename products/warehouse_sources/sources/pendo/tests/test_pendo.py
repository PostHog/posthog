from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine
from unittest.mock import patch

from products.warehouse_sources.sources.pendo._config import PendoSourceConfig
from products.warehouse_sources.sources.pendo.pendo import PendoResumeConfig, _with_bucket_id, validate_credentials
from products.warehouse_sources.sources.pendo.settings import ENDPOINTS, PENDO_ENDPOINTS
from products.warehouse_sources.sources.pendo.source import PendoSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network

PENDO_PATH = "products.warehouse_sources.sources.pendo.pendo"


def _driver() -> SourceDriver:
    return SourceDriver(PendoSource(), PendoSourceConfig(integration_key="key", region="us"))


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid, expected_substr",
        [
            (200, True, None),
            (401, False, "Invalid Pendo integration key"),
            (403, False, "Invalid Pendo integration key"),
            (500, False, "unexpected status code"),
        ],
    )
    def test_status_mapping(self, status: int, expected_valid: bool, expected_substr: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
            is_valid, message = validate_credentials("key", "us")

        assert network.requests_log[0].path == "/api/v1/page"
        assert is_valid is expected_valid
        if expected_substr is None:
            assert message is None
        else:
            assert message is not None
            assert expected_substr in message

    def test_swallows_network_exceptions(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            is_valid, message = validate_credentials("key", "us")

        assert network.requests_log[0].path == "/api/v1/page"
        assert is_valid is False
        assert message is not None

    def test_redacts_the_integration_key(self) -> None:
        with scripted_network([ScriptedResponse(status=200, json={})]) as network:
            validate_credentials("secret-key", "us")

        assert network.session_options[0]["redact_values"] == ("secret-key",)


class TestGetRowsListEndpoint:
    @patch(f"{PENDO_PATH}.LIST_CHUNK_SIZE", 2)
    def test_resumes_from_saved_offset(self) -> None:
        items = [{"id": i} for i in range(5)]

        result = _driver().run("pages", [ScriptedResponse(json=items)], resume_state=PendoResumeConfig(offset=4))

        assert result.raised is None
        assert result.paths == ["/api/v1/page"]
        assert [row["id"] for row in result.rows] == [4]

    @pytest.mark.parametrize("endpoint, expected_expand", [("pages", "*"), ("reports", None), ("segments", None)])
    def test_expands_to_every_app_only_for_app_scoped_objects(self, endpoint: str, expected_expand: str | None) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[{"id": "a"}])])

        assert result.raised is None
        assert result.requests[0].param("expand") == expected_expand


class TestGetRowsFanOut:
    def test_walks_sorted_parent_ids_after_the_resume_point_and_skips_deleted_parents(self) -> None:
        guides = [{"id": "g3"}, {"id": "g1"}, {"id": "g2"}, {"id": "g4"}, {"name": "no id"}]
        g3_history = [{"id": "g3", "stableVersionId": "g3-v2"}, {"id": "g3", "stableVersionId": "g3-v1"}]
        g4_history = [{"id": "g4", "stableVersionId": "g4-v1"}]

        result = _driver().run(
            "guide_history",
            [
                ScriptedResponse(json=guides),
                ScriptedResponse(status=404, json={"message": "guide not found"}),
                ScriptedResponse(json=g3_history),
                ScriptedResponse(json={"results": g4_history}),
            ],
            resume_state=PendoResumeConfig(last_id="g1"),
        )

        assert result.raised is None
        assert result.paths == [
            "/api/v1/guide",
            "/api/v1/guide/g2/history",
            "/api/v1/guide/g3/history",
            "/api/v1/guide/g4/history",
        ]
        assert result.requests[0].param("expand") == "*"
        assert result.requests[1].param("expand") is None
        assert result.rows == g3_history + g4_history
        assert result.saved_states == [
            PendoResumeConfig(last_id="g2"),
            PendoResumeConfig(last_id="g3"),
            PendoResumeConfig(last_id="g4"),
        ]

    def test_quotes_the_parent_id_in_the_child_path(self) -> None:
        result = _driver().run(
            "guide_history",
            [ScriptedResponse(json=[{"id": "a/b c"}]), ScriptedResponse(json=[])],
        )

        assert result.raised is None
        assert result.urls[1].endswith("/api/v1/guide/a%2Fb%20c/history")

    @pytest.mark.parametrize("status", [400, 401])
    def test_raises_child_errors_other_than_not_found(self, status: int) -> None:
        result = _driver().run(
            "guide_history",
            [ScriptedResponse(json=[{"id": "g1"}]), ScriptedResponse(status=status, json={})],
        )

        assert result.raised is not None
        assert f"{status} Client Error" in str(result.raised)
        assert result.rows == []
        assert result.saved_states == []


class TestGetRowsAggregation:
    @patch(f"{PENDO_PATH}.AGGREGATION_PAGE_SIZE", 2)
    def test_paginates_via_filter_cursor_and_limit(self) -> None:
        # Pendo's aggregation pipeline has no skip/offset stage (a "skip" step is rejected with
        # a 400 "unknown step type" error), so paging must use a `>` filter cursor on the sort field.
        page1 = {"results": [{"visitorId": "1"}, {"visitorId": "2"}]}
        page2 = {"results": [{"visitorId": "3"}]}

        result = _driver().run("visitors", [ScriptedResponse(json=page1), ScriptedResponse(json=page2)])

        assert result.raised is None
        assert [row["visitorId"] for row in result.rows] == ["1", "2", "3"]
        assert result.saved_states == [PendoResumeConfig(last_id="2"), PendoResumeConfig(last_id="3")]
        assert result.requests[0].method == "POST"
        assert result.requests[0].url == "https://app.pendo.io/api/v1/aggregation"

        first_pipeline = result.requests[0].json()["request"]["pipeline"]
        assert {"source": {"visitors": None}} in first_pipeline
        assert {"sort": ["visitorId"]} in first_pipeline
        assert {"limit": 2} in first_pipeline
        assert not any("filter" in step for step in first_pipeline)

        second_pipeline = result.requests[1].json()["request"]["pipeline"]
        assert {"filter": 'visitorId>"2"'} in second_pipeline

    def test_escapes_quotes_in_the_filter_cursor(self) -> None:
        # visitorId is set by the customer's own tracking code, so a value containing a `"`
        # must not be able to break out of the filter string literal and alter the expression.
        result = _driver().run(
            "visitors",
            [ScriptedResponse(json={"results": []})],
            resume_state=PendoResumeConfig(last_id='ab"cd'),
        )

        assert result.raised is None
        pipeline = result.requests[0].json()["request"]["pipeline"]
        assert {"filter": 'visitorId>"ab\\"cd"'} in pipeline


DAY_MS = 24 * 60 * 60 * 1000


def _ms(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp() * 1000)


def _event_window_starts(result: Any) -> list[int]:
    return [request.json()["request"]["pipeline"][0]["source"]["timeSeries"]["first"] for request in result.requests]


class TestGetRowsEvents:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self) -> Iterator[None]:
        with time_machine.travel(datetime(2026, 3, 10, 6, 0, tzinfo=UTC), tick=False):
            yield

    def test_full_refresh_walks_the_lookback_up_to_the_last_started_anchor(self) -> None:
        result = _driver().run("page_events", always(ScriptedResponse(json={"results": []})))

        assert result.raised is None
        windows = _event_window_starts(result)
        assert windows[0] == _ms("2025-12-09T12:00:00")
        # Today's noon-UTC anchor is still in the future at 06:00 UTC.
        assert windows[-1] == _ms("2026-03-09T12:00:00")
        assert all(later - earlier == DAY_MS for earlier, later in zip(windows, windows[1:]))

        source = result.requests[0].json()["request"]["pipeline"][0]["source"]
        assert source["pageEvents"] == {"appId": 'expandAppIds("*")'}
        assert source["timeSeries"]["period"] == "dayRange"
        assert source["timeSeries"]["count"] == 1

    @pytest.mark.parametrize("utc_offset_hours", [-11, -5, 0, 10, 12, 14])
    def test_incremental_rereads_the_watermark_day_and_the_reprocessing_week(self, utc_offset_hours: int) -> None:
        watermark = _ms("2026-03-05T00:00:00") - utc_offset_hours * 60 * 60 * 1000

        result = _driver().run(
            "page_events",
            always(ScriptedResponse(json={"results": []})),
            incremental_field="day",
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        windows = _event_window_starts(result)
        assert any(watermark <= anchor < watermark + DAY_MS for anchor in windows)
        assert windows[0] <= watermark - 7 * DAY_MS + DAY_MS

    @patch(f"{PENDO_PATH}.EVENT_BATCH_SIZE", 1)
    def test_resumes_from_saved_day_and_keys_buckets_without_measures(self) -> None:
        bucket = {"day": _ms("2026-03-09T05:00:00"), "trackTypeId": "t1", "visitorId": "v1", "tabId": "a"}
        first_read = {**bucket, "numEvents": 1, "numMinutes": 1, "lastTime": 1, "lastKeyFrameTimestamp": 1}
        re_read = {**bucket, "numEvents": 7, "numMinutes": 3, "lastTime": 2, "lastKeyFrameTimestamp": 2}
        other_tab = {**bucket, "tabId": "b", "numEvents": 1, "numMinutes": 1, "lastTime": 1}

        result = _driver().run(
            "track_events",
            [
                ScriptedResponse(json={"results": [first_read, other_tab]}),
                ScriptedResponse(json={"results": [re_read]}),
            ],
            resume_state=PendoResumeConfig(next_day="2026-03-08"),
        )

        assert result.raised is None
        assert _event_window_starts(result) == [_ms("2026-03-08T12:00:00"), _ms("2026-03-09T12:00:00")]
        # The first of the day's two batches leaves the cursor on that day.
        assert result.committed_states == [
            PendoResumeConfig(next_day="2026-03-08"),
            PendoResumeConfig(next_day="2026-03-09"),
            PendoResumeConfig(next_day="2026-03-10"),
        ]
        first_id, other_tab_id, re_read_id = (row["id"] for row in result.rows)
        assert first_id == re_read_id
        assert first_id != other_tab_id

    @pytest.mark.parametrize("endpoint, event_source", [("guide_events", "guideEvents"), ("poll_events", "pollEvents")])
    @pytest.mark.parametrize(
        "start_time, expected_day",
        [
            # Pendo names the window by its start in the subscription's timezone.
            (_ms("2026-03-09T05:00:00"), _ms("2026-03-09T05:00:00")),
            (str(_ms("2026-03-09T05:00:00")), _ms("2026-03-09T05:00:00")),
            # With no startTime, the row falls back to the requested UTC day.
            (None, _ms("2026-03-09T00:00:00")),
        ],
    )
    def test_raw_events_get_a_stable_hash_id_and_the_window_day(
        self, endpoint: str, event_source: str, start_time: Any, expected_day: int
    ) -> None:
        event: dict[str, Any] = {
            "type": "guideSeen",
            "guideId": "g1",
            "visitorId": "v1",
            "browserTime": _ms("2026-03-09T08:00:00"),
        }
        other = {**event, "browserTime": event["browserTime"] + 1}
        body: dict[str, Any] = {"results": [event, other]}
        if start_time is not None:
            body["startTime"] = start_time

        result = _driver().run(
            endpoint,
            [ScriptedResponse(json=body)],
            resume_state=PendoResumeConfig(next_day="2026-03-09"),
        )

        assert result.raised is None
        assert result.requests[0].json()["request"]["pipeline"][0]["source"][event_source] == {
            "appId": 'expandAppIds("*")'
        }
        first, second = result.rows
        assert {key: first[key] for key in event} == event
        assert first["day"] == second["day"] == expected_day
        assert first["id"] != second["id"]
        # The id ignores the day, so a re-read of the event lands on the same row.
        assert first["id"] == _with_bucket_id(event)["id"]

    def test_survey_responses_keep_their_pendo_id_and_send_no_app_filter(self) -> None:
        response = {"id": "r1", "surveyId": "s1", "visitorId": "v1", "lastUpdatedAt": _ms("2026-03-09T08:00:00")}

        result = _driver().run(
            "survey_responses",
            [ScriptedResponse(json={"results": [response]})],
            resume_state=PendoResumeConfig(next_day="2026-03-09"),
        )

        assert result.raised is None
        assert result.rows == [response]
        assert result.requests[0].json()["request"]["pipeline"][0]["source"]["surveyResponses"] is None


class TestPendoSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = PENDO_ENDPOINTS[endpoint]
        payload: object = [] if config.path else {"results": []}

        result = _driver().run(endpoint, always(ScriptedResponse(json=payload)))

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == config.primary_keys
        # Pendo timestamps are epoch-ms, so we intentionally ship unpartitioned full-refresh tables.
        assert result.response.partition_mode is None
        assert result.response.partition_keys is None
