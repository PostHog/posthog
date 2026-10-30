from datetime import UTC, datetime
from typing import Any

import pytest

from requests.exceptions import ConnectionError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.demodesk.demodesk import (
    DemodeskResumeConfig,
    to_iso8601,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.demodesk.source import DemodeskSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.demodesk import (
    DemodeskSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(DemodeskSource(), DemodeskSourceConfig(api_key="test-key"))


class TestDemodeskV1Demos:
    def _pages(self) -> list[ScriptedResponse]:
        return [
            ScriptedResponse(
                json={
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
            ScriptedResponse(
                json={
                    "data": [{"id": "2", "type": "demos", "attributes": {"account": "Acme follow-up"}}],
                    "meta": {"currentPage": 2, "hasNextPage": False},
                }
            ),
        ]

    def test_attributes_are_flattened_into_row_root(self) -> None:
        result = _driver().run("demos", self._pages())

        assert result.raised is None
        assert result.rows[0]["id"] == "1"
        assert result.rows[0]["account"] == "Acme intro"
        assert "attributes" not in result.rows[0]
        assert result.rows[0]["relationships"]["user"]["data"]["id"] == "9"

    def test_resume_seeds_page(self) -> None:
        result = _driver().run(
            "demos",
            [ScriptedResponse(json={"data": [], "meta": {"currentPage": 7, "hasNextPage": False}})],
            resume_state=DemodeskResumeConfig(page=7),
        )

        assert result.raised is None
        assert result.params("page") == ["7"]


class TestDemodeskV2Recordings:
    def _pages(self) -> list[ScriptedResponse]:
        return [
            ScriptedResponse(
                json={
                    "data": [{"recordingId": "10", "recordingToken": "tokA", "createdAt": "2026-01-01T00:00:00Z"}],
                    "meta": {"hasNext": True, "limit": 100, "nextCursor": "cur-1"},
                }
            ),
            ScriptedResponse(
                json={
                    "data": [{"recordingId": "11", "recordingToken": "tokB", "createdAt": "2026-01-02T00:00:00Z"}],
                    "meta": {"hasNext": False, "limit": 100, "nextCursor": None},
                }
            ),
        ]

    def test_cursor_pagination_follows_next_cursor_and_checkpoints(self) -> None:
        result = _driver().run("recordings", self._pages())

        assert result.raised is None
        assert result.params("cursor") == [None, "cur-1"]
        assert result.params("limit") == ["100", "100"]
        assert result.saved_states == [DemodeskResumeConfig(cursor="cur-1")]
        assert [row["recordingId"] for row in result.rows] == ["10", "11"]

    def test_resume_seeds_cursor(self) -> None:
        result = _driver().run(
            "recordings",
            [ScriptedResponse(json={"data": [], "meta": {"hasNext": False, "limit": 100}})],
            resume_state=DemodeskResumeConfig(cursor="cur-resumed"),
        )

        assert result.raised is None
        assert result.params("cursor") == ["cur-resumed"]

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
        result = _driver().run(
            "recordings",
            [ScriptedResponse(json={"data": [], "meta": {"hasNext": False, "limit": 100}})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 15, 12, 30, tzinfo=UTC),
            incremental_field=incremental_field_name,
        )

        assert result.raised is None
        assert result.requests[0].param(expected_param) == "2026-01-15T12:30:00Z"


class TestDemodeskFanout:
    def test_resume_skips_already_completed_parent(self) -> None:
        result = _driver().run(
            "recording_summaries",
            route(
                {
                    "/v2/recordings": [
                        ScriptedResponse(
                            json={
                                "data": [{"recordingToken": "tokA"}, {"recordingToken": "tokB"}],
                                "meta": {"hasNext": False, "limit": 100},
                            }
                        )
                    ],
                    # No entry for tokA's summaries: a request there would fail,
                    # proving a resumed run does not re-fetch an already-completed parent.
                    "/v2/recordings/tokB/summaries": [ScriptedResponse(json={"data": [{"summaryId": "sB"}]})],
                }
            ),
            resume_state=DemodeskResumeConfig(
                fanout_state={"completed": ["/v2/recordings/tokA/summaries"], "current": None, "child_state": None}
            ),
        )

        assert result.raised is None
        assert result.paths == ["/api/v2/recordings", "/api/v2/recordings/tokB/summaries"]
        assert [row["summaryId"] for row in result.rows] == ["sB"]

    def test_recording_transcripts_skip_unready_transcripts(self) -> None:
        result = _driver().run(
            "recording_transcripts",
            route(
                {
                    "/v2/recordings": [
                        ScriptedResponse(
                            json={
                                "data": [
                                    {"recordingToken": "tokA"},
                                    {"recordingToken": "tokB"},
                                    {"recordingToken": "tokC"},
                                ],
                                "meta": {"hasNext": False, "limit": 100},
                            }
                        )
                    ],
                    "/v2/recordings/tokA/transcript": [
                        ScriptedResponse(json={"data": {"language": "en", "paragraphs": []}})
                    ],
                    "/v2/recordings/tokB/transcript": [
                        ScriptedResponse(status=202, json={"error": {"message": "processing"}})
                    ],
                    "/v2/recordings/tokC/transcript": [ScriptedResponse(status=204)],
                }
            ),
        )

        assert result.raised is None
        assert [(row["recordingToken"], row["language"]) for row in result.rows] == [("tokA", "en")]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid", "expected_message_part"),
        [
            (200, True, None),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_valid: bool, expected_message_part: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))) as network:
            is_valid, message = validate_credentials("test-key")

        assert {request.path for request in network.requests_log} == {"/api/v2/me"}
        assert is_valid is expected_valid
        if expected_message_part is None:
            assert message is None
        else:
            assert message is not None and expected_message_part in message

    def test_network_error_returns_false_instead_of_raising(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            is_valid, message = validate_credentials("test-key")

        assert {request.path for request in network.requests_log} == {"/api/v2/me"}
        assert is_valid is False
        assert message is not None and "boom" in message


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
