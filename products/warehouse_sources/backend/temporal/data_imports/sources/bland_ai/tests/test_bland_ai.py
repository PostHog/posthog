import json
from datetime import UTC, date, datetime
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.bland_ai.bland_ai import (
    BASE_URL,
    PAGE_SIZE,
    BlandAIResumeConfig,
    _format_start_date,
    bland_ai_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bland_ai.settings import ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the bland_ai module.
BLAND_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.bland_ai.bland_ai.make_tracked_session"
)


def _response(body: Any, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: BlandAIResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's url/params/auth AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(
    endpoint: str,
    manager: mock.MagicMock,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
):
    return bland_ai_source(
        api_key="key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestFormatStartDate:
    @parameterized.expand(
        [
            ("none", None, None),
            # A naive watermark is stamped UTC so the server-side filter is unambiguous.
            ("naive_datetime", datetime(2026, 1, 2, 3, 4, 5), "2026-01-02T03:04:05+00:00"),
            ("aware_datetime", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "2026-01-02T03:04:05+00:00"),
            ("date", date(2026, 1, 2), "2026-01-02"),
            ("iso_string", "2026-01-02T03:04:05+00:00", "2026-01-02T03:04:05+00:00"),
        ]
    )
    def test_format_start_date(self, _name: str, value: Any, expected: str | None) -> None:
        assert _format_start_date(value) == expected


class TestValidateCredentials:
    @parameterized.expand(
        [("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False), ("error", 500, False)]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        with mock.patch(BLAND_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
            assert validate_credentials("key") is expected

    @mock.patch(BLAND_SESSION_PATCH)
    def test_swallows_exceptions(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key") is False

    @mock.patch(BLAND_SESSION_PATCH)
    def test_sends_raw_api_key_in_authorization_header(self, mock_session: mock.MagicMock) -> None:
        # Bland expects the raw key, not a "Bearer "-prefixed value.
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("sk-raw-key")
        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["authorization"] == "sk-raw-key"


class TestCallsPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_by_offset_until_total_count(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        page_one = [{"call_id": f"c{i}", "created_at": "2026-01-01T00:00:00+00:00"} for i in range(PAGE_SIZE)]
        page_two = [{"call_id": "clast", "created_at": "2026-01-02T00:00:00+00:00"}]
        snapshots = _wire(
            session,
            [
                _response({"total_count": PAGE_SIZE + 1, "count": PAGE_SIZE, "calls": page_one}),
                _response({"total_count": PAGE_SIZE + 1, "count": 1, "calls": page_two}),
            ],
        )

        rows = _rows(_source("calls", _make_manager()))

        assert len(rows) == PAGE_SIZE + 1
        assert rows[-1]["call_id"] == "clast"
        # Reaching total_count terminates without requesting a third page.
        assert session.send.call_count == 2
        assert snapshots[0]["url"] == f"{BASE_URL}/v1/calls"
        assert snapshots[0]["params"]["from"] == 0
        assert snapshots[0]["params"]["limit"] == PAGE_SIZE
        # Ascending creation order so index offsets stay stable while new calls append.
        assert snapshots[0]["params"]["ascending"] == "true"
        assert snapshots[0]["params"]["sort_by"] == "created_at"
        assert snapshots[1]["params"]["from"] == PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_short_page_when_total_count_overcounts(self, MockSession: mock.MagicMock) -> None:
        # total_count can drift from what's actually returned; a short page must still terminate.
        session = MockSession.return_value
        _wire(session, [_response({"total_count": 50, "count": 2, "calls": [{"call_id": "c1"}, {"call_id": "c2"}]})])

        rows = _rows(_source("calls", _make_manager()))

        assert [r["call_id"] for r in rows] == ["c1", "c2"]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sends_raw_api_key_auth(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"total_count": 1, "count": 1, "calls": [{"call_id": "c1"}]})])

        _rows(_source("calls", _make_manager()))

        # The framework auth injects the raw key (no "Bearer" prefix) into the authorization header.
        auth = snapshots[0]["auth"]
        assert auth.api_key == "key"
        assert auth.name == "authorization"
        assert auth.location == "header"
        assert session.headers.get("Accept") == "application/json"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_watermark_becomes_start_date_filter(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"total_count": 1, "count": 1, "calls": [{"call_id": "c1"}]})])

        rows = _rows(
            _source(
                "calls",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 5, tzinfo=UTC),
            )
        )

        assert [r["call_id"] for r in rows] == ["c1"]
        # The watermark is sent server-side as the inclusive `start_date` filter.
        assert snapshots[0]["params"]["start_date"] == "2026-01-05T00:00:00+00:00"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_each_page_with_filter(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        page_one = [{"call_id": f"c{i}"} for i in range(PAGE_SIZE)]
        _wire(
            session,
            [
                _response({"total_count": PAGE_SIZE + 1, "count": PAGE_SIZE, "calls": page_one}),
                _response({"total_count": PAGE_SIZE + 1, "count": 1, "calls": [{"call_id": "clast"}]}),
            ],
        )

        manager = _make_manager()
        _rows(
            _source(
                "calls",
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 5, tzinfo=UTC),
            )
        )

        # State is saved once (after page one; page two hits total_count) and carries both the next
        # offset and the exact filter, so a resume continues the same result set.
        manager.save_state.assert_called_once()
        saved = manager.save_state.call_args.args[0]
        assert saved.offset == PAGE_SIZE
        assert saved.start_date == "2026-01-05T00:00:00+00:00"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset_and_filter(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        saved_filter = "2026-01-05T00:00:00+00:00"
        snapshots = _wire(session, [_response({"total_count": 3, "count": 1, "calls": [{"call_id": "c3"}]})])

        # Old-format state (no fanout_state) must still seed the paginator.
        manager = _make_manager(BlandAIResumeConfig(offset=2, start_date=saved_filter))
        rows = _rows(
            _source(
                "calls",
                manager,
                should_use_incremental_field=True,
                # The checkpointed watermark has advanced past the interrupted run's filter; the
                # resumed run must reuse the saved filter or the saved offset points at the wrong rows.
                db_incremental_field_last_value=datetime(2026, 1, 7, tzinfo=UTC),
            )
        )

        assert [r["call_id"] for r in rows] == ["c3"]
        assert snapshots[0]["params"]["from"] == 2
        assert snapshots[0]["params"]["start_date"] == saved_filter

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_account_yields_nothing(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"total_count": 0, "count": 0, "calls": []})])

        manager = _make_manager()
        assert _rows(_source("calls", manager)) == []
        manager.save_state.assert_not_called()


class TestCallTranscripts:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_hydrates_each_call_and_injects_parent_keys(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response(
                    {
                        "total_count": 2,
                        "count": 2,
                        "calls": [
                            {"call_id": "c1", "created_at": "2026-01-01T00:00:00+00:00"},
                            {"call_id": "c2", "created_at": "2026-01-02T00:00:00+00:00"},
                        ],
                    }
                ),
                _response(
                    {
                        "call_id": "c1",
                        "transcripts": [
                            {"id": 1, "text": "hello", "user": "assistant", "created_at": "2026-01-01T00:00:01+00:00"},
                            {"id": 2, "text": "hi", "user": "user", "created_at": "2026-01-01T00:00:05+00:00"},
                        ],
                    }
                ),
                # A call with no transcripts (e.g. unanswered) must not break the batch.
                _response({"call_id": "c2", "transcripts": None}),
            ],
        )

        rows = _rows(_source("call_transcripts", _make_manager()))

        assert [r["id"] for r in rows] == [1, 2]
        # Rows carry the parent call id (composite primary key) and the parent's creation time
        # (the incremental/partition field — utterance timestamps aren't monotonic across calls).
        assert all(r["call_id"] == "c1" for r in rows)
        assert all(r["call_created_at"] == "2026-01-01T00:00:00+00:00" for r in rows)
        assert rows[0]["text"] == "hello"
        # One list request plus one hydration request per listed call.
        assert [s["url"] for s in snapshots] == [
            f"{BASE_URL}/v1/calls",
            f"{BASE_URL}/v1/calls/c1",
            f"{BASE_URL}/v1/calls/c2",
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_fanout_state_with_filter(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(
                    {
                        "total_count": 1,
                        "count": 1,
                        "calls": [{"call_id": "c1", "created_at": "2026-01-05T00:00:00+00:00"}],
                    }
                ),
                _response({"call_id": "c1", "transcripts": [{"id": 1}]}),
            ],
        )

        manager = _make_manager()
        _rows(
            _source(
                "call_transcripts",
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 5, tzinfo=UTC),
            )
        )

        assert manager.save_state.call_count > 0
        saved = manager.save_state.call_args.args[0]
        # The final checkpoint records the fully-hydrated call and keeps the exact filter so a
        # resume walks the same parent result set.
        assert saved.fanout_state["completed"] == ["v1/calls/c1"]
        assert saved.fanout_state["current"] is None
        assert saved.start_date == "2026-01-05T00:00:00+00:00"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_already_hydrated_calls(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response(
                    {
                        "total_count": 2,
                        "count": 2,
                        "calls": [
                            {"call_id": "c1", "created_at": "2026-01-01T00:00:00+00:00"},
                            {"call_id": "c2", "created_at": "2026-01-02T00:00:00+00:00"},
                        ],
                    }
                ),
                _response({"call_id": "c2", "transcripts": [{"id": 7, "text": "yo"}]}),
            ],
        )

        manager = _make_manager(
            BlandAIResumeConfig(
                start_date=None,
                fanout_state={"completed": ["v1/calls/c1"], "current": None, "child_state": None},
            )
        )
        rows = _rows(_source("call_transcripts", manager))

        # c1 was fully hydrated before the interruption — only c2 is fetched again.
        assert [r["id"] for r in rows] == [7]
        assert all(r["call_id"] == "c2" for r in rows)
        assert [s["url"] for s in snapshots] == [f"{BASE_URL}/v1/calls", f"{BASE_URL}/v1/calls/c2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_old_format_resume_state_restarts_fanout_under_saved_filter(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        saved_filter = "2026-01-05T00:00:00+00:00"
        snapshots = _wire(
            session,
            [
                _response(
                    {
                        "total_count": 1,
                        "count": 1,
                        "calls": [{"call_id": "c1", "created_at": "2026-01-05T00:00:00+00:00"}],
                    }
                ),
                _response({"call_id": "c1", "transcripts": [{"id": 1}]}),
            ],
        )

        # State saved before fanout_state existed (offset-only): the fan-out restarts from the top
        # but keeps the frozen filter so it walks the same result set (merge dedupes re-yields).
        manager = _make_manager(BlandAIResumeConfig(offset=5, start_date=saved_filter))
        rows = _rows(
            _source(
                "call_transcripts",
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 7, tzinfo=UTC),
            )
        )

        assert [r["id"] for r in rows] == [1]
        assert snapshots[0]["params"]["from"] == 0
        assert snapshots[0]["params"]["start_date"] == saved_filter


class TestPathways:
    @parameterized.expand(
        [
            # Bare list of pathway objects.
            ("bare_list", [{"id": "p1"}, {"id": "p2"}], ["p1", "p2"]),
            # Wrapped list variants.
            ("wrapped_pathways", {"pathways": [{"id": "p1"}]}, ["p1"]),
            ("wrapped_data", {"data": [{"id": "p1"}]}, ["p1"]),
            # A single bare object (the shape the docs' response example shows).
            ("single_object", {"id": "p1", "name": "Demo", "nodes": []}, ["p1"]),
        ]
    )
    def test_normalizes_response_shapes(self, _name: str, api_response: Any, expected_ids: list[str]) -> None:
        with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            snapshots = _wire(session, [_response(api_response)])

            rows = _rows(_source("pathways", _make_manager()))

            assert [r["id"] for r in rows] == expected_ids
            # A single unordered page on a full-refresh-only endpoint.
            assert session.send.call_count == 1
            assert snapshots[0]["url"] == f"{BASE_URL}/v1/pathway"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_pathway_list_yields_nothing(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        assert _rows(_source("pathways", _make_manager())) == []


class TestBlandAISourceResponse:
    def test_endpoints_inventory(self) -> None:
        assert ENDPOINTS == ("calls", "call_transcripts", "pathways")

    @parameterized.expand(
        [
            ("calls", ["call_id"], ["created_at"]),
            # The composite key keeps utterances unique table-wide; partitioning uses the parent
            # call's stable creation time.
            ("call_transcripts", ["call_id", "id"], ["call_created_at"]),
            ("pathways", ["id"], None),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, primary_keys: list[str], partition_keys: list[str] | None
    ) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == partition_keys
        assert response.partition_mode == ("datetime" if partition_keys else None)
        # Call listings request ascending=true&sort_by=created_at.
        assert response.sort_mode == "asc"
