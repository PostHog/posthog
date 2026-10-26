from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.roark import RoarkSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.roark.roark import (
    RoarkResumeConfig,
    _explode_transcript,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.roark.settings import ENDPOINTS, ROARK_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.roark.source import RoarkSource


def _driver(api_key: str = "key") -> SourceDriver:
    return SourceDriver(RoarkSource(), RoarkSourceConfig(api_key=api_key))


def _resp(body: Any, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


def _cursor_page(items: list[dict[str, Any]], has_more: bool, next_cursor: str | None = None) -> ScriptedResponse:
    return _resp({"data": items, "pagination": {"hasMore": has_more, "nextCursor": next_cursor}})


def _offset_page(items: list[dict[str, Any]], has_more: bool) -> ScriptedResponse:
    return _resp({"data": items, "pagination": {"hasMore": has_more}})


class TestCursorPagination:
    def test_walks_cursor_until_has_more_false(self) -> None:
        result = _driver().run(
            "agent",
            [
                _cursor_page([{"id": "1"}], has_more=True, next_cursor="c1"),
                _cursor_page([{"id": "2"}], has_more=True, next_cursor="c2"),
                _cursor_page([{"id": "3"}], has_more=False, next_cursor=None),
            ],
        )

        assert [r["id"] for r in result.rows] == ["1", "2", "3"]
        # The `after` param advances to the cursor of the previously-fetched page; the first page
        # carries none.
        assert result.params("after") == [None, "c1", "c2"]
        assert result.requests[0].param("limit") == "50"
        # A checkpoint is saved after each non-final page, recording the NEXT page's cursor.
        assert result.saved_states == [RoarkResumeConfig(after="c1"), RoarkResumeConfig(after="c2")]

    def test_resume_starts_from_saved_cursor(self) -> None:
        result = _driver().run(
            "agent",
            [_cursor_page([{"id": "9"}], has_more=False, next_cursor=None)],
            resume_state=RoarkResumeConfig(after="saved-cursor"),
        )

        assert [r["id"] for r in result.rows] == ["9"]
        # The initial (cursor-less) page is never fetched on resume.
        assert result.params("after") == ["saved-cursor"]


class TestOffsetPagination:
    def test_walks_offset_advancing_by_rows_returned(self) -> None:
        # A non-final page returning fewer rows than max_page_size must advance the offset by the
        # rows actually returned, or rows in the gap would be skipped on the next request.
        result = _driver().run(
            "issue",
            [
                _offset_page([{"id": "1"}, {"id": "2"}, {"id": "3"}], has_more=True),
                _offset_page([{"id": "4"}], has_more=False),
            ],
        )

        assert [r["id"] for r in result.rows] == ["1", "2", "3", "4"]
        assert result.requests[0].param("offset") == "0"
        assert result.requests[0].param("limit") == "100"
        # Offset advances by rows RECEIVED (3), not the requested page size.
        assert result.requests[1].param("offset") == "3"
        assert result.saved_states == [RoarkResumeConfig(offset=3)]

    def test_resume_starts_from_saved_offset(self) -> None:
        result = _driver().run("issue", [_offset_page([], has_more=False)], resume_state=RoarkResumeConfig(offset=200))

        assert result.params("offset") == ["200"]


class TestUnpaginated:
    def test_single_fetch_envelope(self) -> None:
        result = _driver().run("metric_definition", [_resp({"data": [{"id": "1"}, {"id": "2"}]})])

        assert [r["id"] for r in result.rows] == ["1", "2"]
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_handles_bare_top_level_list_response(self) -> None:
        # Unpaginated endpoints may return a bare list instead of a `{"data": [...]}` envelope; those
        # rows must still be synced rather than silently dropped.
        result = _driver().run("metric_definition", [_resp([{"id": "1"}, {"id": "2"}])])

        assert [r["id"] for r in result.rows] == ["1", "2"]


class TestFanout:
    @parameterized.expand(
        [
            ("call_metric", "/v1/call", "callId", "/v1/call/{}/metrics", {"limit": "100", "sortBy": "createdAt"}),
            (
                "metric_collection_job_metric_value",
                "/v1/metric/collection-jobs",
                "jobId",
                "/v1/metric/collection-jobs/{}/metric-values",
                {"limit": "50", "sortBy": None},
            ),
        ]
    )
    def test_fetches_each_parent_and_skips_missing_ones(
        self, endpoint: str, parent_path: str, parent_column: str, child_path: str, parent_params: dict[str, str | None]
    ) -> None:
        metric = {"metricDefinitionId": "m1", "values": [{"value": 0.5, "captureStatus": "SUCCESS"}]}
        result = _driver().run(
            endpoint,
            [
                _cursor_page([{"id": "p1"}, {"id": "p2"}], has_more=True, next_cursor="c1"),
                _resp({"data": [metric, {"metricDefinitionId": "m2", "values": []}]}),
                _resp({"message": "Not found"}, status=404),
                _cursor_page([{"id": "p3"}], has_more=False),
                _resp({"data": []}),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {**metric, parent_column: "p1"},
            {"metricDefinitionId": "m2", "values": [], parent_column: "p1"},
        ]
        assert result.paths == [
            parent_path,
            child_path.format("p1"),
            child_path.format("p2"),
            parent_path,
            child_path.format("p3"),
        ]
        for name, value in parent_params.items():
            assert result.requests[0].param(name) == value
        assert result.requests[3].param("after") == "c1"
        # The child endpoints document no page size, so none is sent.
        assert result.requests[1].param("limit") is None
        # Saved child paths are relative to the base URL, which already carries `/v1`.
        assert result.saved_states[-1] == RoarkResumeConfig(
            completed=[child_path.format(p).removeprefix("/v1") for p in ("p1", "p2", "p3")]
        )

    def test_transcript_yields_one_row_per_entry(self) -> None:
        entries: list[dict[str, Any]] = [
            {"participantId": "pa", "role": "AGENT", "text": "Hello", "startOffsetMs": 0, "endOffsetMs": 900},
            {"participantId": None, "role": None, "text": "(noise)", "startOffsetMs": 900, "endOffsetMs": 1200},
        ]
        agent = {"id": "pa", "type": "AGENT", "agentId": "agent-1"}
        result = _driver().run(
            "call_transcript",
            [
                _cursor_page([{"id": "c1"}, {"id": "c2"}, {"id": "c3"}], has_more=False),
                _resp(
                    {"data": {"transcriptionSource": "ROARK_POST_CALL", "participants": [agent], "entries": entries}}
                ),
                # A call with no transcript answers with a null source and no entries.
                _resp({"data": {"transcriptionSource": None, "participants": [], "entries": []}}),
                _resp({"data": {"transcriptionSource": "ROARK_POST_CALL", "participants": [], "entries": entries[:1]}}),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {
                **entries[0],
                "callId": "c1",
                "entryIndex": 0,
                "transcriptionSource": "ROARK_POST_CALL",
                "participant": agent,
            },
            {
                **entries[1],
                "callId": "c1",
                "entryIndex": 1,
                "transcriptionSource": "ROARK_POST_CALL",
                "participant": None,
            },
            {
                **entries[0],
                "callId": "c3",
                "entryIndex": 0,
                "transcriptionSource": "ROARK_POST_CALL",
                "participant": None,
            },
        ]

    def test_transcript_skips_malformed_entries(self) -> None:
        rows = _explode_transcript(
            {"callId": "c1", "participants": [None], "entries": [None, {"participantId": "pa", "text": "Hi"}]}
        )

        assert [(row["callId"], row["entryIndex"], row["text"]) for row in rows] == [("c1", 1, "Hi")]

    def test_resume_skips_completed_parents(self) -> None:
        result = _driver().run(
            "call_metric",
            [
                _cursor_page([{"id": "p1"}, {"id": "p2"}], has_more=False),
                _resp({"data": [{"metricDefinitionId": "m1", "values": []}]}),
            ],
            resume_state=RoarkResumeConfig(completed=["/call/p1/metrics"]),
        )

        assert result.raised is None
        assert [row["callId"] for row in result.rows] == ["p2"]
        assert result.paths == ["/v1/call", "/v1/call/p2/metrics"]


class TestRetryAndFailLoud:
    @parameterized.expand([("throttled", 429), ("server_error", 500), ("unavailable", 503)])
    def test_retryable_status_is_reissued_then_recovers(self, _name: str, status: int) -> None:
        # Roark documents 429s and transient 5xx as retryable; the client re-issues them.
        result = _driver().run("agent", [_resp({}, status=status), _cursor_page([{"id": "ok"}], has_more=False)])

        assert [r["id"] for r in result.rows] == ["ok"]
        assert len(result.requests) == 2

    def test_persistent_5xx_exhausts_retries_and_raises(self) -> None:
        result = _driver().run("agent", always(_resp({}, status=500)))

        assert isinstance(result.raised, RESTClientRetryableError)

    def test_auth_error_fails_loud_without_retry(self) -> None:
        # A bad/revoked token surfaces as an HTTPError from raise_for_status — retrying never helps.
        result = _driver().run("agent", [_resp({"error": "unauthorized"}, status=401)])

        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1


class TestRoarkSourceResponse:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_every_endpoint_builds_a_response(self, endpoint: str) -> None:
        result = _driver().run(endpoint, always(_resp({"data": []})))

        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ROARK_ENDPOINTS[endpoint].primary_keys
