import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.demodesk.demodesk import (
    DemodeskPagePaginator,
    DemodeskResumeConfig,
    demodesk_source,
    to_iso8601,
    validate_credentials,
)

_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source"
    ".rest_client.make_tracked_session"
)


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestDemodeskPagePaginator:
    @pytest.mark.parametrize(
        ("body", "expected_has_next"),
        [
            ({"data": [], "meta": {"currentPage": 1, "hasNextPage": True}}, True),
            ({"data": [], "meta": {"currentPage": 1, "hasNextPage": False}}, False),
            # An endpoint without pagination metadata must stop after its first page instead of
            # looping on page=1 forever.
            ({"data": []}, False),
        ],
    )
    def test_update_state_stops_unless_has_next_page(self, body: dict[str, Any], expected_has_next: bool) -> None:
        paginator = DemodeskPagePaginator()
        paginator.update_state(_make_http_response(body))
        assert paginator.has_next_page is expected_has_next

    def test_pages_advance_from_one(self) -> None:
        paginator = DemodeskPagePaginator()
        request = Request(method="GET", url="https://demodesk.com/api/v1/demos")
        paginator.init_request(request)
        assert request.params["page"] == 1

        paginator.update_state(_make_http_response({"data": [], "meta": {"hasNextPage": True}}))
        paginator.update_request(request)
        assert request.params["page"] == 2

    def test_resume_state_round_trip(self) -> None:
        paginator = DemodeskPagePaginator()
        paginator.update_state(_make_http_response({"data": [], "meta": {"hasNextPage": True}}))
        assert paginator.get_resume_state() == {"page": 2}

        resumed = DemodeskPagePaginator()
        resumed.set_resume_state({"page": 5})
        request = Request(method="GET", url="https://demodesk.com/api/v1/demos")
        resumed.init_request(request)
        assert request.params["page"] == 5

    def test_no_resume_state_on_terminal_page(self) -> None:
        paginator = DemodeskPagePaginator()
        paginator.update_state(_make_http_response({"data": [], "meta": {"hasNextPage": False}}))
        assert paginator.get_resume_state() is None


class RequestCapture:
    def __init__(self, responses: list[Response] | None = None, by_url: dict[str, list[Response]] | None = None):
        self.requests: list[Request] = []
        self._responses = iter(responses or [])
        self._by_url = {url: iter(items) for url, items in (by_url or {}).items()}

    def send(self, request: Request, *_args: Any, **_kwargs: Any) -> Response:
        # Requests are mutated in place by the paginator between pages, so keep a shallow copy.
        copied = Request(method=request.method, url=request.url, headers=dict(request.headers or {}))
        copied.params = dict(request.params or {})
        # The mocked session skips prepare_request, where auth is normally applied; the auth
        # classes only touch `.headers`, so applying them to the copy records what would be sent.
        if request.auth is not None:
            request.auth(copied)
        self.requests.append(copied)
        for url, response_iter in self._by_url.items():
            if request.url and request.url.endswith(url):
                return next(response_iter)
        return next(self._responses)


def _drive(
    endpoint: str,
    capture: RequestCapture,
    manager: MagicMock | None = None,
    *,
    incremental: bool = False,
    last_value: Any = None,
    incremental_field_name: str | None = None,
) -> tuple[MagicMock, list[dict[str, Any]]]:
    if manager is None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

    with patch(_SESSION_PATCH) as MockSession:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.side_effect = lambda req: req
        mock_session.send.side_effect = capture.send

        resource = demodesk_source(
            api_key="test-key",
            endpoint=endpoint,
            team_id=123,
            job_id="test_job",
            resumable_source_manager=manager,
            db_incremental_field_last_value=last_value,
            should_use_incremental_field=incremental,
            incremental_field_name=incremental_field_name,
        )
        rows: list[dict[str, Any]] = []
        for page in cast(Iterable[Any], resource):
            rows.extend(page if isinstance(page, list) else [page])
        return manager, rows


class TestDemodeskV1Demos:
    def _pages(self) -> list[Response]:
        return [
            _make_http_response(
                {
                    "data": [
                        {
                            "id": "1",
                            "type": "demos",
                            "attributes": {"account": "Acme intro", "status": "ended"},
                            "relationships": {"user": {"data": {"id": "9", "type": "users"}}},
                        }
                    ],
                    "meta": {"currentPage": 1, "hasNextPage": True},
                }
            ),
            _make_http_response(
                {
                    "data": [{"id": "2", "type": "demos", "attributes": {"account": "Acme follow-up"}}],
                    "meta": {"currentPage": 2, "hasNextPage": False},
                }
            ),
        ]

    def test_pages_follow_has_next_page_and_checkpoint_each_page(self) -> None:
        capture = RequestCapture(self._pages())
        manager, rows = _drive("demos", capture)

        assert [r.params.get("page") for r in capture.requests] == [1, 2]
        # Every page must request the team-wide view; without the filter only the key owner's
        # meetings sync.
        assert all(r.params.get("filter[all_team_members_dashboard]") == "true" for r in capture.requests)
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [DemodeskResumeConfig(page=2)]

    def test_v1_sends_api_key_header_not_bearer(self) -> None:
        capture = RequestCapture(self._pages())
        _drive("demos", capture)

        first = capture.requests[0]
        assert first.headers.get("api-key") == "test-key"
        assert "Authorization" not in first.headers

    def test_attributes_are_flattened_into_row_root(self) -> None:
        capture = RequestCapture(self._pages())
        _, rows = _drive("demos", capture)

        assert rows[0]["id"] == "1"
        assert rows[0]["account"] == "Acme intro"
        assert "attributes" not in rows[0]
        assert rows[0]["relationships"]["user"]["data"]["id"] == "9"

    def test_resume_seeds_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = DemodeskResumeConfig(page=7)

        capture = RequestCapture([_make_http_response({"data": [], "meta": {"currentPage": 7, "hasNextPage": False}})])
        _drive("demos", capture, manager)

        assert [r.params.get("page") for r in capture.requests] == [7]

    def test_terminal_single_page_saves_no_state(self) -> None:
        capture = RequestCapture(
            [
                _make_http_response(
                    {"data": [{"id": "1", "type": "demos", "attributes": {}}], "meta": {"hasNextPage": False}}
                )
            ]
        )
        manager, _ = _drive("demos", capture)
        manager.save_state.assert_not_called()


class TestDemodeskV2Recordings:
    def _pages(self) -> list[Response]:
        return [
            _make_http_response(
                {
                    "data": [{"recordingId": "10", "recordingToken": "tokA", "createdAt": "2026-01-01T00:00:00Z"}],
                    "meta": {"hasNext": True, "limit": 100, "nextCursor": "cur-1"},
                }
            ),
            _make_http_response(
                {
                    "data": [{"recordingId": "11", "recordingToken": "tokB", "createdAt": "2026-01-02T00:00:00Z"}],
                    "meta": {"hasNext": False, "limit": 100, "nextCursor": None},
                }
            ),
        ]

    def test_cursor_pagination_follows_next_cursor_and_checkpoints(self) -> None:
        capture = RequestCapture(self._pages())
        manager, rows = _drive("recordings", capture)

        assert [r.params.get("cursor") for r in capture.requests] == [None, "cur-1"]
        assert all(r.params.get("limit") == 100 for r in capture.requests)
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [DemodeskResumeConfig(cursor="cur-1")]
        assert [row["recordingId"] for row in rows] == ["10", "11"]

    def test_v2_sends_bearer_auth(self) -> None:
        capture = RequestCapture(self._pages())
        _drive("recordings", capture)

        assert capture.requests[0].headers.get("Authorization") == "Bearer test-key"

    def test_resume_seeds_cursor(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = DemodeskResumeConfig(cursor="cur-resumed")

        capture = RequestCapture([_make_http_response({"data": [], "meta": {"hasNext": False, "limit": 100}})])
        _drive("recordings", capture, manager)

        assert [r.params.get("cursor") for r in capture.requests] == ["cur-resumed"]

    @pytest.mark.parametrize(
        ("incremental_field_name", "expected_param"),
        [
            ("updatedAt", "filter[updated_at_gteq]"),
            ("createdAt", "filter[created_at_gteq]"),
            # No explicit choice falls back to the default cursor field.
            (None, "filter[updated_at_gteq]"),
        ],
    )
    def test_incremental_sync_with_watermark_sends_server_side_filter(
        self, incremental_field_name: str | None, expected_param: str
    ) -> None:
        capture = RequestCapture([_make_http_response({"data": [], "meta": {"hasNext": False, "limit": 100}})])
        _drive(
            "recordings",
            capture,
            incremental=True,
            last_value=datetime(2026, 1, 15, 12, 30, tzinfo=UTC),
            incremental_field_name=incremental_field_name,
        )

        assert capture.requests[0].params.get(expected_param) == "2026-01-15T12:30:00Z"

    @pytest.mark.parametrize(
        ("incremental", "last_value"),
        [
            # The first incremental sync has no watermark yet and must fetch the full history.
            (True, None),
            (False, None),
            # A full refresh must ignore a stale watermark left over from an earlier incremental run.
            (False, datetime(2026, 1, 15, tzinfo=UTC)),
        ],
    )
    def test_no_filter_without_watermarked_incremental_sync(self, incremental: bool, last_value: Any) -> None:
        capture = RequestCapture([_make_http_response({"data": [], "meta": {"hasNext": False, "limit": 100}})])
        _drive("recordings", capture, incremental=incremental, last_value=last_value)

        sent = capture.requests[0].params
        assert "filter[updated_at_gteq]" not in sent
        assert "filter[created_at_gteq]" not in sent


class TestDemodeskFanout:
    def test_child_rows_carry_parent_token_and_404_parents_are_skipped(self) -> None:
        capture = RequestCapture(
            by_url={
                "/v2/recordings": [
                    _make_http_response(
                        {
                            "data": [{"recordingToken": "tokA"}, {"recordingToken": "tokB"}],
                            "meta": {"hasNext": False, "limit": 100},
                        }
                    )
                ],
                # tokA was deleted between the listing and the child fetch; the fan-out must skip
                # it instead of failing the whole sync.
                "/v2/recordings/tokA/summaries": [_make_http_response({"error": {"code": "not_found"}}, 404)],
                "/v2/recordings/tokB/summaries": [
                    _make_http_response({"data": [{"summaryId": "s1", "content": "Recap"}]})
                ],
            }
        )
        _, rows = _drive("recording_summaries", capture)

        assert len(rows) == 1
        assert rows[0]["summaryId"] == "s1"
        assert rows[0]["recordingToken"] == "tokB"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid", "expected_message_part"),
        [
            (200, True, None),
            (401, False, "rejected the API key"),
            (403, False, "rejected the API key"),
            (500, False, "HTTP 500"),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_valid: bool, expected_message_part: str | None) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.demodesk.demodesk.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.get.return_value = _make_http_response({}, status_code)
            is_valid, message = validate_credentials("test-key")

        assert is_valid is expected_valid
        if expected_message_part is None:
            assert message is None
        else:
            assert message is not None and expected_message_part in message


class TestToIso8601:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2026, 1, 15, 12, 30, tzinfo=UTC), "2026-01-15T12:30:00Z"),
            # A naive watermark from the schema config is treated as UTC, not local time.
            (datetime(2026, 1, 15, 12, 30), "2026-01-15T12:30:00Z"),
            ("2026-01-15T12:30:00Z", "2026-01-15T12:30:00Z"),
        ],
    )
    def test_formats_watermark(self, value: Any, expected: str) -> None:
        assert to_iso8601(value) == expected
