import gzip
import json
from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.fullstory.fullstory import (
    FullStoryExportFailedError,
    FullStoryResumeConfig,
    fullstory_source,
    get_events,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the fullstory module.
FULLSTORY_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.fullstory.fullstory.make_tracked_session"
)


def _response(
    items: list[dict[str, Any]] | None,
    *,
    next_token: str | None = None,
    drop_results: bool = False,
    list_key: str = "results",
    cursor_key: str = "next_page_token",
) -> Response:
    body: dict[str, Any] = {}
    if not drop_results:
        body[list_key] = items or []
    if next_token:
        body[cursor_key] = next_token
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: FullStoryResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response], urls: list[str] | None = None) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        if urls is not None:
            urls.append(request.url)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: mock.MagicMock, endpoint: str = "users"):
    return fullstory_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


class TestPagination:
    @pytest.mark.parametrize(
        "endpoint, list_key, cursor_key, cursor_param",
        [
            ("users", "results", "next_page_token", "page_token"),
            ("segments", "segments", "nextPaginationToken", "paginationToken"),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_page_token(self, MockSession, endpoint, list_key, cursor_key, cursor_param) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response([{"id": "u1"}], next_token="tok1", list_key=list_key, cursor_key=cursor_key),
                _response([{"id": "u2"}], list_key=list_key, cursor_key=cursor_key),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source(manager, endpoint))

        assert [r["id"] for r in rows] == ["u1", "u2"]
        # First page has no cursor; second page carries the saved token.
        assert cursor_param not in params[0]
        assert params[1][cursor_param] == "tok1"
        # Checkpoint saved once after the first page (points at the next page); the tokenless page ends it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == FullStoryResumeConfig(next_page_token="tok1")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_token(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "u_resumed"}])])

        manager = _make_manager(FullStoryResumeConfig(next_page_token="tok_resume"))
        _rows(_source(manager))

        assert params[0]["page_token"] == "tok_resume"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_stops_even_with_cursor_and_no_checkpoint(self, MockSession) -> None:
        # A tokened-but-empty page must not loop; stop after one request without saving state.
        session = MockSession.return_value
        _wire(session, [_response([], next_token="tok_loop")])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


class TestSessionsFanout:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_queries_sessions_per_identified_user(self, MockSession) -> None:
        session = MockSession.return_value
        urls: list[str] = []
        params = _wire(
            session,
            [
                _response([{"id": "fs1", "uid": "a/b c"}]),
                _response([{"id": "1:2", "app_url": "https://app.fullstory.com/s/1:2", "created_time": "t"}]),
            ],
            urls,
        )

        rows = _rows(_source(_make_manager(), "sessions"))

        assert params[0]["is_identified"] == "true"
        assert urls[1].endswith("/v2/sessions?uid=a%2Fb%20c")
        assert rows == [
            {
                "id": "1:2",
                "app_url": "https://app.fullstory.com/s/1:2",
                "created_time": "t",
                "user_id": "fs1",
                "uid": "a/b c",
            }
        ]


def _json_response(body: dict[str, Any]) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    return resp


def _export_file(rows: list[dict[str, Any]]) -> bytes:
    return gzip.compress("".join(json.dumps(row) + "\n" for row in rows).encode())


class _FakeExportApi:
    def __init__(self, operation_states: dict[str, list[dict[str, Any]]], files: dict[str, bytes]) -> None:
        self.operation_states = operation_states
        self.files = files
        self.created: list[dict[str, Any]] = []
        self.api = mock.MagicMock()
        self.api.post.side_effect = self._post
        self.api.get.side_effect = self._get
        self.download = mock.MagicMock()
        self.download.get.side_effect = self._download

    def session_factory(self, **kwargs: Any) -> mock.MagicMock:
        return self.api if "headers" in kwargs else self.download

    def _post(self, url: str, json: dict[str, Any], **_: Any) -> mock.MagicMock:
        self.created.append(json)
        return _json_response({"operationId": f"op{len(self.created)}"})

    def _get(self, url: str, **_: Any) -> mock.MagicMock:
        if "/operations/v1/" in url:
            return _json_response(self.operation_states[url.rsplit("/", 1)[-1]].pop(0))
        export_id = url.split("/exports/")[1].split("/")[0]
        return _json_response({"location": f"https://storage.example.com/{export_id}"})

    def _download(self, url: str, **_: Any) -> mock.MagicMock:
        download = mock.MagicMock()
        download.iter_content.return_value = [self.files[url.rsplit("/", 1)[-1]]]
        response = mock.MagicMock()
        response.__enter__.return_value = download
        return response


def _completed(export_id: str) -> dict[str, Any]:
    return {"state": "COMPLETED", "results": {"searchExportId": export_id}}


class TestEventsExport:
    def _run(self, fake: _FakeExportApi, manager: mock.MagicMock, watermark: Any = None) -> list[dict[str, Any]]:
        with (
            time_machine.travel(datetime(2026, 3, 3, 1, 0, tzinfo=UTC), tick=False),
            mock.patch(FULLSTORY_SESSION_PATCH, side_effect=fake.session_factory),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.fullstory.fullstory.time.sleep"
            ),
        ):
            return [row for batch in get_events("key", manager, watermark) for row in batch]

    def test_exports_daily_windows_after_the_watermark(self) -> None:
        fake = _FakeExportApi(
            operation_states={"op1": [{"state": "PENDING"}, _completed("e1")], "op2": [_completed("e2")]},
            files={"e1": _export_file([{"EventStart": "a"}, {"EventStart": "b"}]), "e2": _export_file([])},
        )

        rows = self._run(fake, _make_manager(), watermark="2026-03-01T12:00:00Z")

        assert rows == [{"EventStart": "a"}, {"EventStart": "b"}]
        assert [c["timeRange"] for c in fake.created] == [
            {"start": "2026-03-01T12:00:00.001Z", "end": "2026-03-02T12:00:00.001Z"},
            {"start": "2026-03-02T12:00:00.001Z", "end": "2026-03-03T00:00:00.000Z"},
        ]
        assert all(c["segmentTimeRange"] == c["timeRange"] for c in fake.created)
        assert {(c["segmentId"], c["type"], c["format"]) for c in fake.created} == {
            ("everyone", "TYPE_EVENT", "FORMAT_NDJSON")
        }

    def test_resume_reuses_the_saved_operation_and_skips_written_rows(self) -> None:
        fake = _FakeExportApi(
            operation_states={"saved": [_completed("e1")]},
            files={"e1": _export_file([{"n": 1}, {"n": 2}, {"n": 3}])},
        )
        manager = _make_manager(
            FullStoryResumeConfig(
                export_window_start="2026-03-02T00:00:00.000Z",
                export_window_end="2026-03-03T00:00:00.000Z",
                export_operation_id="saved",
                export_rows_done=2,
            )
        )

        rows = self._run(fake, manager, watermark="2026-01-01T00:00:00Z")

        assert rows == [{"n": 3}]
        assert fake.created == []
        assert manager.save_state.call_args.args[0].export_rows_done == 3

    def test_failed_saved_operation_exports_the_window_again(self) -> None:
        fake = _FakeExportApi(
            operation_states={"saved": [{"state": "FAILED", "errorDetails": "expired"}], "op1": [_completed("e1")]},
            files={"e1": _export_file([{"n": 1}, {"n": 2}])},
        )
        manager = _make_manager(
            FullStoryResumeConfig(
                export_window_start="2026-03-02T00:00:00.000Z",
                export_window_end="2026-03-03T00:00:00.000Z",
                export_operation_id="saved",
                export_rows_done=1,
            )
        )

        rows = self._run(fake, manager)

        assert rows == [{"n": 1}, {"n": 2}]
        assert [c["timeRange"]["start"] for c in fake.created] == ["2026-03-02T00:00:00.000Z"]

    def test_failed_new_operation_raises(self) -> None:
        fake = _FakeExportApi(operation_states={"op1": [{"state": "FAILED", "errorDetails": "boom"}]}, files={})

        with pytest.raises(FullStoryExportFailedError, match="boom"):
            self._run(fake, _make_manager(), watermark="2026-03-02T12:00:00Z")


class TestValidateCredentials:
    @mock.patch(FULLSTORY_SESSION_PATCH)
    def test_probe_sends_basic_auth_header(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("key123")

        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Basic key123"
