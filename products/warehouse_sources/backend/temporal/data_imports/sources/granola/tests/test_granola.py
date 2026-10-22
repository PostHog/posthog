from datetime import UTC, date, datetime
from typing import Any

import pytest

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.granola import (
    GranolaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.granola.granola import (
    GRANOLA_BASE_URL,
    GranolaResumeConfig,
    _format_timestamp,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.granola.source import GranolaSource


def _driver() -> SourceDriver:
    return SourceDriver(GranolaSource(), GranolaSourceConfig(api_key="grn_test"))


def _response(body: dict[str, Any], status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


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
    def test_status_mapping(self, status: int, schema_name: str | None, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status))):
            is_valid, _ = validate_credentials("grn_test", schema_name)

        assert is_valid is expected_valid

    def test_network_error_is_invalid(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))):
            is_valid, message = validate_credentials("grn_test")

        assert is_valid is False
        assert message is not None

    @pytest.mark.parametrize(
        "schema_name, expected_path",
        [
            (None, "/v1/notes"),
            ("notes", "/v1/notes"),
            ("folders", "/v1/folders"),
            ("spaces", "/v1/spaces"),
            ("transcripts", "/v1/notes"),  # fan-out child probes its parent listing
            ("unknown", "/v1/notes"),
        ],
    )
    def test_probes_path_matching_schema(self, schema_name: str | None, expected_path: str) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("grn_test", schema_name)

        assert network.requests_log[0].path == expected_path
        assert network.requests_log[0].param("page_size") == "1"


class TestPagination:
    def test_resumes_from_saved_url(self) -> None:
        resume_url = f"{GRANOLA_BASE_URL}/v1/notes?page_size=30&cursor=resume_token"
        result = _driver().run(
            "notes",
            [_response({"notes": [{"id": "not_9"}], "hasMore": False, "cursor": None})],
            resume_state=GranolaResumeConfig(next_url=resume_url),
        )

        assert result.raised is None
        assert result.urls[0] == resume_url

    def test_incremental_filter_in_first_request_and_next_url(self) -> None:
        result = _driver().run(
            "notes",
            [
                _response({"notes": [{"id": "not_1"}], "hasMore": True, "cursor": "c1"}),
                _response({"notes": [{"id": "not_2"}], "hasMore": False, "cursor": None}),
            ],
            incremental_field="updated_at",
            db_incremental_field_last_value=datetime(2026, 1, 27, 15, 30, 0, tzinfo=UTC),
        )

        assert result.raised is None
        # Server-side filter is present on the initial request...
        assert result.requests[0].param("updated_after") == "2026-01-27T15:30:00Z"
        # ...and persists into the self-contained next-page URL so it isn't dropped after page 1.
        saved = result.saved_states[0]
        assert "updated_after=2026-01-27T15%3A30%3A00Z" in saved.next_url

    def test_forbidden_status_raises_loudly(self) -> None:
        result = _driver().run("notes", [_response({"error": "forbidden"}, status=403)])

        assert isinstance(result.raised, HTTPError)


class TestTranscriptsFanout:
    def test_paginates_each_note_transcript_and_skips_deleted_notes(self) -> None:
        result = _driver().run(
            "transcripts",
            [
                _response({"notes": [{"id": "not_1"}, {"id": "not_2"}], "hasMore": False, "cursor": None}),
                _response({"transcript": [{"text": "a"}], "hasMore": True, "cursor": "t1"}),
                # A cursor alongside hasMore=false still ends the transcript.
                _response({"transcript": [{"text": "b"}], "hasMore": False, "cursor": "t2"}),
                _response({"message": "Not found"}, status=404),
            ],
        )

        assert result.raised is None
        assert [(row["note_id"], row["text"]) for row in result.rows] == [("not_1", "a"), ("not_1", "b")]
        assert all("_notes_id" not in row for row in result.rows)
        assert result.paths[1:] == [
            "/v1/notes/not_1/transcript",
            "/v1/notes/not_1/transcript",
            "/v1/notes/not_2/transcript",
        ]
        assert result.queries[1] == {"page_size": ("100",)}
        assert result.queries[2] == {"page_size": ("100",), "cursor": ("t1",)}
        assert result.saved_states[-1].completed == [
            "/v1/notes/not_1/transcript",
            "/v1/notes/not_2/transcript",
        ]

    def test_resume_skips_completed_notes_and_continues_current_cursor(self) -> None:
        result = _driver().run(
            "transcripts",
            [
                _response({"notes": [{"id": "not_1"}, {"id": "not_2"}], "hasMore": False, "cursor": None}),
                _response({"transcript": [{"text": "c"}], "hasMore": False, "cursor": None}),
            ],
            resume_state=GranolaResumeConfig(
                completed=["/v1/notes/not_1/transcript"],
                current="/v1/notes/not_2/transcript",
                child_state={"cursor": "t5"},
            ),
        )

        assert result.raised is None
        assert result.rows == [{"text": "c", "note_id": "not_2"}]
        assert result.paths[1] == "/v1/notes/not_2/transcript"
        assert result.requests[1].param("cursor") == "t5"

    def test_repeated_transcript_cursor_fails_instead_of_looping(self) -> None:
        result = _driver().run(
            "transcripts",
            [
                _response({"notes": [{"id": "not_1"}], "hasMore": False, "cursor": None}),
                _response({"transcript": [{"text": "a"}], "hasMore": True, "cursor": "t1"}),
                _response({"transcript": [{"text": "a"}], "hasMore": True, "cursor": "t1"}),
            ],
        )

        assert isinstance(result.raised, ValueError)
        assert "not advancing" in str(result.raised)
        assert len(result.requests) == 3
