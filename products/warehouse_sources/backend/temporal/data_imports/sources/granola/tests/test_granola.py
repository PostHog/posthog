import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.granola.granola import (
    GRANOLA_BASE_URL,
    GranolaResumeConfig,
    _format_timestamp,
    granola_source,
    validate_credentials,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.granola.granola"
# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _mock_response(status: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status
    return resp


def _response(body: dict[str, Any], status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = f"{GRANOLA_BASE_URL}/v1/notes"
    return resp


def _make_manager(resume_state: Optional[GranolaResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's url + params AT SEND TIME.

    The client mutates a single ``Request`` object in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    seen: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        seen.append({"url": request.url, "params": dict(request.params or {})})
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return seen


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestFormatTimestamp:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 1, 27, 15, 30, 0, tzinfo=UTC), "2026-01-27T15:30:00Z"),
            (datetime(2026, 1, 27, 15, 30, 0), "2026-01-27T15:30:00Z"),
            (date(2026, 1, 27), "2026-01-27T00:00:00Z"),
            ("already-a-string", "already-a-string"),
        ],
    )
    def test_format_timestamp(self, value: Any, expected: str) -> None:
        assert _format_timestamp(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, schema_name, expected_valid",
        [
            (200, None, True),
            (200, "notes", True),
            (401, None, False),
            (401, "notes", False),
            (403, None, True),  # valid key, scope not granted - accepted at source-create
            (403, "notes", False),  # scope required for the specific schema
            (500, None, False),
        ],
    )
    def test_status_mapping(self, status, schema_name, expected_valid) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _mock_response(status)

            is_valid, _ = validate_credentials("grn_test", schema_name)

        assert is_valid is expected_valid

    def test_network_error_is_invalid(self) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")

            is_valid, message = validate_credentials("grn_test")

        assert is_valid is False
        assert message is not None

    @pytest.mark.parametrize(
        "schema_name, expected_path",
        [
            (None, "/v1/notes"),
            ("notes", "/v1/notes"),
            ("folders", "/v1/folders"),
            ("transcripts", "/v1/notes"),  # fan-out child probes its parent listing
            ("unknown", "/v1/notes"),
        ],
    )
    def test_probes_path_matching_schema(self, schema_name, expected_path) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _mock_response(200)

            validate_credentials("grn_test", schema_name)

            called_url = mock_session.return_value.get.call_args[0][0]

        assert called_url.startswith(f"{GRANOLA_BASE_URL}{expected_path}?")


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_url(self, MockSession) -> None:
        session = MockSession.return_value
        resume_url = f"{GRANOLA_BASE_URL}/v1/notes?page_size=30&cursor=resume_token"
        seen = _wire(session, [_response({"notes": [{"id": "not_9"}], "hasMore": False, "cursor": None})])

        manager = _make_manager(GranolaResumeConfig(next_url=resume_url))
        _rows(granola_source("grn_test", "notes", team_id=1, job_id="j", resumable_source_manager=manager))

        assert seen[0]["url"] == resume_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_filter_in_first_request_and_next_url(self, MockSession) -> None:
        session = MockSession.return_value
        seen = _wire(
            session,
            [
                _response({"notes": [{"id": "not_1"}], "hasMore": True, "cursor": "c1"}),
                _response({"notes": [{"id": "not_2"}], "hasMore": False, "cursor": None}),
            ],
        )

        manager = _make_manager()
        _rows(
            granola_source(
                "grn_test",
                "notes",
                team_id=1,
                job_id="j",
                resumable_source_manager=manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 27, 15, 30, 0, tzinfo=UTC),
                incremental_field="updated_at",
            )
        )

        # Server-side filter is present on the initial request...
        assert seen[0]["params"]["updated_after"] == "2026-01-27T15:30:00Z"
        # ...and persists into the self-contained next-page URL so it isn't dropped after page 1.
        saved = manager.save_state.call_args.args[0]
        assert "updated_after=2026-01-27T15%3A30%3A00Z" in saved.next_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_forbidden_status_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "forbidden"}, status=403)])

        with pytest.raises(HTTPError):
            _rows(granola_source("grn_test", "notes", team_id=1, job_id="j", resumable_source_manager=_make_manager()))


class TestTranscriptsFanout:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_each_note_transcript_and_skips_deleted_notes(self, MockSession) -> None:
        session = MockSession.return_value
        seen = _wire(
            session,
            [
                _response({"notes": [{"id": "not_1"}, {"id": "not_2"}], "hasMore": False, "cursor": None}),
                _response({"transcript": [{"text": "a"}], "hasMore": True, "cursor": "t1"}),
                # A cursor alongside hasMore=false still ends the transcript.
                _response({"transcript": [{"text": "b"}], "hasMore": False, "cursor": "t2"}),
                _response({"message": "Not found"}, status=404),
            ],
        )

        manager = _make_manager()
        rows = _rows(granola_source("grn_test", "transcripts", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [(row["note_id"], row["text"]) for row in rows] == [("not_1", "a"), ("not_1", "b")]
        assert all("_notes_id" not in row for row in rows)
        child_requests = seen[1:]
        assert [r["url"].removeprefix(GRANOLA_BASE_URL) for r in child_requests] == [
            "/v1/notes/not_1/transcript",
            "/v1/notes/not_1/transcript",
            "/v1/notes/not_2/transcript",
        ]
        assert child_requests[0]["params"] == {"page_size": 100}
        assert child_requests[1]["params"] == {"page_size": 100, "cursor": "t1"}
        assert manager.save_state.call_args.args[0].completed == [
            "/v1/notes/not_1/transcript",
            "/v1/notes/not_2/transcript",
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_completed_notes_and_continues_current_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        seen = _wire(
            session,
            [
                _response({"notes": [{"id": "not_1"}, {"id": "not_2"}], "hasMore": False, "cursor": None}),
                _response({"transcript": [{"text": "c"}], "hasMore": False, "cursor": None}),
            ],
        )

        manager = _make_manager(
            GranolaResumeConfig(
                completed=["/v1/notes/not_1/transcript"],
                current="/v1/notes/not_2/transcript",
                child_state={"cursor": "t5"},
            )
        )
        rows = _rows(granola_source("grn_test", "transcripts", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == [{"text": "c", "note_id": "not_2"}]
        assert seen[1]["url"] == f"{GRANOLA_BASE_URL}/v1/notes/not_2/transcript"
        assert seen[1]["params"]["cursor"] == "t5"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_repeated_transcript_cursor_fails_instead_of_looping(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"notes": [{"id": "not_1"}], "hasMore": False, "cursor": None}),
                _response({"transcript": [{"text": "a"}], "hasMore": True, "cursor": "t1"}),
                _response({"transcript": [{"text": "a"}], "hasMore": True, "cursor": "t1"}),
            ],
        )

        with pytest.raises(ValueError, match="not advancing"):
            _rows(
                granola_source(
                    "grn_test", "transcripts", team_id=1, job_id="j", resumable_source_manager=_make_manager()
                )
            )
        assert session.send.call_count == 3
