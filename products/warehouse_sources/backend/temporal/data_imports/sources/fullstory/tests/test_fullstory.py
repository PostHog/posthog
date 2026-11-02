import gzip
import json
from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fullstory.fullstory import (
    FullStoryExportFailedError,
    FullStoryResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fullstory.source import FullStorySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fullstory import (
    FullStorySourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(FullStorySource(), FullStorySourceConfig(api_key="key"))


def _response(
    items: list[dict[str, Any]],
    *,
    next_token: str | None = None,
    list_key: str = "results",
    cursor_key: str = "next_page_token",
) -> ScriptedResponse:
    body: dict[str, Any] = {list_key: items}
    if next_token:
        body[cursor_key] = next_token
    return ScriptedResponse(json=body)


class TestPagination:
    @pytest.mark.parametrize(
        "endpoint, list_key, cursor_key, cursor_param",
        [
            ("users", "results", "next_page_token", "page_token"),
            ("segments", "segments", "nextPaginationToken", "paginationToken"),
        ],
    )
    def test_paginates_via_page_token(self, endpoint: str, list_key: str, cursor_key: str, cursor_param: str) -> None:
        result = _driver().run(
            endpoint,
            [
                _response([{"id": "u1"}], next_token="tok1", list_key=list_key, cursor_key=cursor_key),
                _response([{"id": "u2"}], list_key=list_key, cursor_key=cursor_key),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["u1", "u2"]
        # First page has no cursor; second page carries the saved token.
        assert result.params(cursor_param) == [None, "tok1"]
        # Checkpoint saved once after the first page (points at the next page); the tokenless page ends it.
        assert result.saved_states == [FullStoryResumeConfig(next_page_token="tok1")]

    def test_resumes_from_saved_token(self) -> None:
        result = _driver().run(
            "users",
            [_response([{"id": "u_resumed"}])],
            resume_state=FullStoryResumeConfig(next_page_token="tok_resume"),
        )

        assert result.raised is None
        assert result.rows == [{"id": "u_resumed"}]
        assert result.params("page_token") == ["tok_resume"]

    def test_empty_page_stops_even_with_cursor_and_no_checkpoint(self) -> None:
        # A tokened-but-empty page must not loop; stop after one request without saving state.
        result = _driver().run("users", [_response([], next_token="tok_loop")])

        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 1
        assert result.saved_states == []


class TestSessionsFanout:
    def test_queries_sessions_per_identified_user(self) -> None:
        result = _driver().run(
            "sessions",
            [
                _response([{"id": "fs1", "uid": "a/b c"}]),
                _response([{"id": "1:2", "app_url": "https://app.fullstory.com/s/1:2", "created_time": "t"}]),
            ],
        )

        assert result.raised is None
        assert result.requests[0].param("is_identified") == "true"
        assert result.requests[1].url.endswith("/v2/sessions?uid=a%2Fb%20c")
        assert result.rows == [
            {
                "id": "1:2",
                "app_url": "https://app.fullstory.com/s/1:2",
                "created_time": "t",
                "user_id": "fs1",
                "uid": "a/b c",
            }
        ]


def _export_file(rows: list[dict[str, Any]]) -> bytes:
    return gzip.compress("".join(json.dumps(row) + "\n" for row in rows).encode())


def _completed(export_id: str) -> ScriptedResponse:
    return ScriptedResponse(json={"state": "COMPLETED", "results": {"searchExportId": export_id}})


def _location(export_id: str) -> ScriptedResponse:
    return ScriptedResponse(json={"location": f"https://storage.example.com/{export_id}"})


class TestEventsExport:
    @staticmethod
    def _run(
        script: Script, *, resume_state: FullStoryResumeConfig | None = None, watermark: Any = None
    ) -> DriveResult:
        with time_machine.travel(datetime(2026, 3, 3, 1, 0, tzinfo=UTC), tick=False):
            return _driver().run(
                "events",
                script,
                resume_state=resume_state,
                incremental_field="EventStart",
                db_incremental_field_last_value=watermark,
            )

    def test_exports_daily_windows_after_the_watermark(self) -> None:
        result = self._run(
            [
                ScriptedResponse(json={"operationId": "op1"}),
                ScriptedResponse(json={"state": "PENDING"}),
                _completed("e1"),
                _location("e1"),
                ScriptedResponse(body=_export_file([{"EventStart": "a"}, {"EventStart": "b"}])),
                ScriptedResponse(json={"operationId": "op2"}),
                _completed("e2"),
                _location("e2"),
                ScriptedResponse(body=_export_file([])),
            ],
            watermark="2026-03-01T12:00:00Z",
        )

        assert result.raised is None
        assert result.rows == [{"EventStart": "a"}, {"EventStart": "b"}]
        assert result.paths == [
            "/segments/v1/exports",
            "/operations/v1/op1",
            "/operations/v1/op1",
            "/search/v1/exports/e1/results",
            "/e1",
            "/segments/v1/exports",
            "/operations/v1/op2",
            "/search/v1/exports/e2/results",
            "/e2",
        ]
        created = [request.json() for request in result.requests if request.method == "POST"]
        assert [body["timeRange"] for body in created] == [
            {"start": "2026-03-01T12:00:00.001Z", "end": "2026-03-02T12:00:00.001Z"},
            {"start": "2026-03-02T12:00:00.001Z", "end": "2026-03-03T00:00:00.000Z"},
        ]
        assert all(body["segmentTimeRange"] == body["timeRange"] for body in created)
        assert {(body["segmentId"], body["type"], body["format"]) for body in created} == {
            ("everyone", "TYPE_EVENT", "FORMAT_NDJSON")
        }

    def test_resume_reuses_the_saved_operation_and_skips_written_rows(self) -> None:
        result = self._run(
            [
                _completed("e1"),
                _location("e1"),
                ScriptedResponse(body=_export_file([{"n": 1}, {"n": 2}, {"n": 3}])),
            ],
            resume_state=FullStoryResumeConfig(
                export_window_start="2026-03-02T00:00:00.000Z",
                export_window_end="2026-03-03T00:00:00.000Z",
                export_operation_id="saved",
                export_rows_done=2,
            ),
            watermark="2026-01-01T00:00:00Z",
        )

        assert result.raised is None
        assert result.rows == [{"n": 3}]
        assert result.paths == ["/operations/v1/saved", "/search/v1/exports/e1/results", "/e1"]
        assert result.saved_states[-1].export_rows_done == 3

    def test_failed_saved_operation_exports_the_window_again(self) -> None:
        result = self._run(
            [
                ScriptedResponse(json={"state": "FAILED", "errorDetails": "expired"}),
                ScriptedResponse(json={"operationId": "op1"}),
                _completed("e1"),
                _location("e1"),
                ScriptedResponse(body=_export_file([{"n": 1}, {"n": 2}])),
            ],
            resume_state=FullStoryResumeConfig(
                export_window_start="2026-03-02T00:00:00.000Z",
                export_window_end="2026-03-03T00:00:00.000Z",
                export_operation_id="saved",
                export_rows_done=1,
            ),
        )

        assert result.raised is None
        assert result.rows == [{"n": 1}, {"n": 2}]
        assert result.paths[:2] == ["/operations/v1/saved", "/segments/v1/exports"]
        assert result.requests[1].json()["timeRange"]["start"] == "2026-03-02T00:00:00.000Z"

    def test_failed_new_operation_raises(self) -> None:
        result = self._run(
            [
                ScriptedResponse(json={"operationId": "op1"}),
                ScriptedResponse(json={"state": "FAILED", "errorDetails": "boom"}),
            ],
            watermark="2026-03-02T12:00:00Z",
        )

        assert isinstance(result.raised, FullStoryExportFailedError)
        assert "boom" in str(result.raised)


class TestValidateCredentials:
    def test_probe_sends_basic_auth_header(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("key123") is True

        assert network.requests_log[0].headers["authorization"] == "Basic key123"
